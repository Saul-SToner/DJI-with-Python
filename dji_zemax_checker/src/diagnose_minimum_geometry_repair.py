from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
SAMPLE_COUNT = 500
TTL_LIMIT_MM = 18.0
BFL_LIMIT_MM = 2.3

PAIR_INPUTS = {
    (2, 3): {
        "required_ray_radius": 3.855,
        "safe_radius": 3.97992,
        "margin": 0.124918,
        "conclusion": "PASS_clear_aperture_clamp_possible",
    },
    (4, 5): {
        "required_ray_radius": 2.86167,
        "safe_radius": 2.54095,
        "margin": -0.320719,
        "conclusion": "FAIL_geometry_must_change",
    },
    (7, 8): {
        "required_ray_radius": 3.33926,
        "safe_radius": 3.35093,
        "margin": 0.0116665,
        "conclusion": "BORDERLINE",
    },
    (9, 10): {
        "required_ray_radius": 2.19885,
        "safe_radius": 2.20994,
        "margin": 0.0110862,
        "conclusion": "BORDERLINE",
    },
}

PLAN_TARGETS = {
    "Plan A": 0.05,
    "Plan B": 0.10,
    "Plan C": 0.20,
}


@dataclass
class SurfaceData:
    surface_number: int
    radius: float | None
    thickness: float | None
    glass: str
    semi_diameter: float | None
    conic: float | None
    even_terms: dict[int, float | None]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, digits: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    return f"{number:.{digits}g}"


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _is_plane(radius: float | None) -> bool:
    return radius is None or radius == 0.0 or math.isinf(radius)


def _get_even_term(surface: Any, term: int) -> float | None:
    data = _safe_get(surface, "SurfaceData")
    if data is None:
        return None
    method = _safe_get(data, "GetNthEvenOrderTerm")
    if callable(method):
        try:
            return _to_float(method(term))
        except Exception:
            pass
    cell_method = _safe_get(data, "NthEvenOrderTermCell")
    if callable(cell_method):
        try:
            cell = cell_method(term)
            for attr in ("DoubleValue", "Value"):
                value = _to_float(_safe_get(cell, attr))
                if value is not None:
                    return value
        except Exception:
            pass
    return None


def _read_surface(surface: Any) -> SurfaceData:
    return SurfaceData(
        surface_number=int(_safe_get(surface, "SurfaceNumber", -1)),
        radius=_to_float(_safe_get(surface, "Radius")),
        thickness=_to_float(_safe_get(surface, "Thickness")),
        glass=str(_safe_get(surface, "Material", "") or ""),
        semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
        conic=_to_float(_safe_get(surface, "Conic")),
        even_terms={term: _get_even_term(surface, term) for term in EVEN_TERMS},
    )


def _formula_sag(surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    radius = surface.radius
    conic = surface.conic or 0.0
    if _is_plane(radius):
        base_sag = 0.0
    else:
        assert radius is not None
        c = 1.0 / radius
        sqrt_arg = 1.0 - (1.0 + conic) * c * c * r * r
        if sqrt_arg < 0:
            return None, f"invalid sag sqrt argument {sqrt_arg:g}"
        denom = 1.0 + math.sqrt(sqrt_arg)
        if denom == 0:
            return None, "invalid sag denominator zero"
        base_sag = c * r * r / denom
    asphere = 0.0
    for term, coeff in surface.even_terms.items():
        if coeff is not None:
            asphere += coeff * (r**term)
    return base_sag + asphere, None


def _surface_sag(lde: Any, surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    try:
        result = lde.GetSag(surface.surface_number, r, 0.0)
        if isinstance(result, tuple) and result and not (isinstance(result[0], bool) and not result[0]):
            for item in result[1:]:
                value = _to_float(item)
                if value is not None:
                    return value, None
    except Exception as exc:
        zemax_warning = f"GetSag failed: {type(exc).__name__}: {exc!r}"
    else:
        zemax_warning = f"GetSag returned no finite sag: {result!r}"

    sag, warning = _formula_sag(surface, r)
    if sag is not None:
        return sag, f"formula fallback after {zemax_warning}"
    return None, f"{zemax_warning}; {warning}"


def _min_gap_to_radius(
    lde: Any,
    a: SurfaceData,
    b: SurfaceData,
    radius_max: float,
) -> tuple[float | None, float | None, str]:
    if a.thickness is None:
        return None, None, "surface A thickness unknown"
    min_gap: float | None = None
    min_radius: float | None = None
    invalid: list[str] = []
    for index in range(SAMPLE_COUNT + 1):
        r = radius_max * index / SAMPLE_COUNT
        sag_a, warn_a = _surface_sag(lde, a, r)
        sag_b, warn_b = _surface_sag(lde, b, r)
        if sag_a is None or sag_b is None:
            invalid.append(f"r={r:g}: S{a.surface_number} {warn_a}; S{b.surface_number} {warn_b}")
            continue
        gap = a.thickness + sag_b - sag_a
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_radius = r
    note = ""
    if invalid:
        note = f"{len(invalid)} invalid samples; first: {invalid[0]}"
    return min_gap, min_radius, note


def _ttl_s1_to_image(surfaces: list[SurfaceData]) -> float | None:
    total = 0.0
    used = False
    for surface in surfaces[1:-1]:
        if surface.thickness is not None and math.isfinite(surface.thickness):
            total += surface.thickness
            used = True
    return total if used else None


def _bfl(surfaces: list[SurfaceData]) -> float | None:
    if len(surfaces) < 2:
        return None
    return surfaces[-2].thickness


def _required_increase(current_min_gap: float | None, target_gap: float) -> float | None:
    if current_min_gap is None:
        return None
    return max(0.0, target_gap - current_min_gap)


def _recommended_clear_sd(required_ray_radius: float, safe_radius: float, margin: float) -> tuple[float | None, str]:
    lower = required_ray_radius + margin
    if lower < safe_radius:
        return (lower + safe_radius) / 2.0, "ok"
    return None, "fail_no_interval"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "plan",
        "target_margin",
        "s2_s3_recommended_clear_semi_diameter",
        "s2_s3_status",
        "s4_thickness_increase",
        "s4_min_gap_at_required_radius",
        "s4_min_gap_radius",
        "s7_thickness_increase",
        "s7_min_gap_at_required_radius",
        "s7_min_gap_radius",
        "s9_thickness_increase",
        "s9_min_gap_at_required_radius",
        "s9_min_gap_radius",
        "estimated_ttl",
        "ttl_lt_18",
        "current_bfl",
        "bfl_gt_2p3",
        "still_need_bfl_optimization",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    lens_path: str,
    ttl: float | None,
    bfl: float | None,
    pair_metrics: dict[tuple[int, int], dict[str, Any]],
    plan_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "Minimum Geometry Repair Diagnostic",
        f"lens_path: {lens_path}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        f"current_ttl_s1_to_image_mm: {_fmt(ttl)}",
        f"ttl_limit_mm: {TTL_LIMIT_MM}",
        f"current_bfl_mm: {_fmt(bfl)}",
        f"bfl_limit_mm: {BFL_LIMIT_MM}",
        "",
        "Pair metrics at actual required ray radius + 0.05 mm",
    ]
    for pair, metrics in pair_metrics.items():
        lines.extend(
            [
                "",
                f"S{pair[0]}->S{pair[1]}",
                f"sample_radius_max_mm: {_fmt(metrics.get('sample_radius'))}",
                f"min_gap_mm: {_fmt(metrics.get('min_gap'))}",
                f"min_gap_radius_mm: {_fmt(metrics.get('min_gap_radius'))}",
                f"note: {metrics.get('note') or ''}",
            ]
        )

    lines.extend(["", "Repair plans"])
    for row in plan_rows:
        lines.extend(
            [
                "",
                f"{row['plan']} target_margin={_fmt(row['target_margin'])} mm",
                f"S2/S3 recommended clear semi-diameter: {_fmt(row['s2_s3_recommended_clear_semi_diameter'])} ({row['s2_s3_status']})",
                f"S4 thickness increase: {_fmt(row['s4_thickness_increase'])} mm",
                f"S7 thickness increase: {_fmt(row['s7_thickness_increase'])} mm",
                f"S9 thickness increase: {_fmt(row['s9_thickness_increase'])} mm",
                f"estimated TTL: {_fmt(row['estimated_ttl'])} mm; TTL<18: {row['ttl_lt_18']}",
                f"current BFL: {_fmt(row['current_bfl'])} mm; BFL>2.3: {row['bfl_gt_2p3']}",
                f"still need BFL optimization: {row['still_need_bfl_optimization']}",
                f"notes: {row['notes']}",
            ]
        )

    lines.extend(
        [
            "",
            "Interpretation",
            "S2->S3 is treated as a clear semi-diameter clamp candidate because the prior ray-footprint margin was positive.",
            "S4->S5 requires geometry change because the actual ray footprint exceeded the safe overlap radius.",
            "S7->S8 and S9->S10 are internal edge-thickness repairs; increasing air gaps alone does not fix them.",
            "BFL remains a separate constraint because thickness increases improve overlap but do not directly make BFL >2.3 mm.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_minimum_geometry_repair(lens_path: str) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "minimum_geometry_repair" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"actual lens path: {lens_path}", flush=True)
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    try:
        oss.load(lens_path, saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens read-only/no-save session: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    surfaces = [_read_surface(lde.GetSurfaceAt(index)) for index in range(count)]
    by_number = {surface.surface_number: surface for surface in surfaces}
    ttl = _ttl_s1_to_image(surfaces)
    bfl = _bfl(surfaces)

    pair_metrics: dict[tuple[int, int], dict[str, Any]] = {}
    for pair in ((4, 5), (7, 8), (9, 10)):
        required = float(PAIR_INPUTS[pair]["required_ray_radius"])
        sample_radius = required + 0.05
        min_gap, min_radius, note = _min_gap_to_radius(lde, by_number[pair[0]], by_number[pair[1]], sample_radius)
        pair_metrics[pair] = {
            "sample_radius": sample_radius,
            "min_gap": min_gap,
            "min_gap_radius": min_radius,
            "note": note,
        }

    plan_rows: list[dict[str, Any]] = []
    for plan, target_margin in PLAN_TARGETS.items():
        s2_sd, s2_status = _recommended_clear_sd(
            float(PAIR_INPUTS[(2, 3)]["required_ray_radius"]),
            float(PAIR_INPUTS[(2, 3)]["safe_radius"]),
            target_margin,
        )
        s4_inc = _required_increase(pair_metrics[(4, 5)]["min_gap"], target_margin)
        s7_inc = _required_increase(pair_metrics[(7, 8)]["min_gap"], target_margin)
        s9_inc = _required_increase(pair_metrics[(9, 10)]["min_gap"], target_margin)
        increments = [item for item in (s4_inc, s7_inc, s9_inc) if item is not None]
        estimated_ttl = None if ttl is None or len(increments) != 3 else ttl + sum(increments)
        ttl_ok = None if estimated_ttl is None else estimated_ttl < TTL_LIMIT_MM
        bfl_ok = None if bfl is None else bfl > BFL_LIMIT_MM
        notes: list[str] = []
        if s2_status != "ok":
            notes.append("S2/S3 has no clear semi-diameter interval for requested margin")
        if bfl_ok is False:
            notes.append("BFL remains below 2.3 mm")
        if ttl_ok is False:
            notes.append("estimated TTL exceeds 18 mm")
        plan_rows.append(
            {
                "plan": plan,
                "target_margin": target_margin,
                "s2_s3_recommended_clear_semi_diameter": s2_sd,
                "s2_s3_status": s2_status,
                "s4_thickness_increase": s4_inc,
                "s4_min_gap_at_required_radius": pair_metrics[(4, 5)]["min_gap"],
                "s4_min_gap_radius": pair_metrics[(4, 5)]["min_gap_radius"],
                "s7_thickness_increase": s7_inc,
                "s7_min_gap_at_required_radius": pair_metrics[(7, 8)]["min_gap"],
                "s7_min_gap_radius": pair_metrics[(7, 8)]["min_gap_radius"],
                "s9_thickness_increase": s9_inc,
                "s9_min_gap_at_required_radius": pair_metrics[(9, 10)]["min_gap"],
                "s9_min_gap_radius": pair_metrics[(9, 10)]["min_gap_radius"],
                "estimated_ttl": estimated_ttl,
                "ttl_lt_18": ttl_ok,
                "current_bfl": bfl,
                "bfl_gt_2p3": bfl_ok,
                "still_need_bfl_optimization": bfl_ok is not True,
                "notes": "; ".join(notes),
            }
        )

    csv_path = out_dir / "minimum_geometry_repair_table.csv"
    report_path = out_dir / "minimum_geometry_repair_report.txt"
    _write_csv(csv_path, plan_rows)
    _write_report(report_path, lens_path, ttl, bfl, pair_metrics, plan_rows)

    print(f"current_ttl_s1_to_image: {_fmt(ttl)}", flush=True)
    print(f"current_bfl: {_fmt(bfl)}", flush=True)
    print(f"table: {csv_path}", flush=True)
    print(f"report: {report_path}", flush=True)
    for row in plan_rows:
        print(
            f"{row['plan']}: S4+{_fmt(row['s4_thickness_increase'])}, "
            f"S7+{_fmt(row['s7_thickness_increase'])}, "
            f"S9+{_fmt(row['s9_thickness_increase'])}, "
            f"TTL={_fmt(row['estimated_ttl'])}, TTL<18={row['ttl_lt_18']}, "
            f"BFL>2.3={row['bfl_gt_2p3']}",
            flush=True,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only minimum geometry repair diagnostic for current overlap pairs."
    )
    parser.add_argument(
        "--lens",
        required=True,
        help="Path to the lens file to analyze. The script does not modify or save the lens.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_minimum_geometry_repair(args.lens)
