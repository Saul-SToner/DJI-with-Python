from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from diagnose_ray_failure_surfaces import (
    _field_key,
    _field_number,
    _field_table,
    _fmt,
    _pupil_key,
    _safe_get,
    _to_float,
    _trace_one,
)
from zosapi_cleanup import close_all_analysis_windows


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
FIELDS_DEG = (49.0, 63.0, 70.0)
PUPIL_SAMPLES = (
    (0.0, 0.0),
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (0.707, 0.707),
    (0.707, -0.707),
    (-0.707, 0.707),
    (-0.707, -0.707),
    (0.5, 0.0),
    (-0.5, 0.0),
    (0.0, 0.5),
    (0.0, -0.5),
)
TARGET_SURFACES = (4, 6)
PAIR_BY_TARGET = {4: (4, 5), 6: (6, 7)}
SAFETY_MARGIN = 0.05
SAFETY_GAPS = (0.05, 0.10)
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
SAMPLE_COUNT = 500
TTL_LIMIT_MM = 18.0


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


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "mbcs"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(errors="replace")


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


def _is_plane(radius: float | None) -> bool:
    return radius is None or radius == 0.0 or math.isinf(radius)


def _formula_sag(surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    radius = surface.radius
    conic = surface.conic or 0.0
    if _is_plane(radius):
        base = 0.0
    else:
        assert radius is not None
        c = 1.0 / radius
        sqrt_arg = 1.0 - (1.0 + conic) * c * c * r * r
        if sqrt_arg < 0:
            return None, f"invalid sag sqrt argument {sqrt_arg:g}"
        denom = 1.0 + math.sqrt(sqrt_arg)
        if denom == 0:
            return None, "invalid sag denominator zero"
        base = c * r * r / denom
    asphere = 0.0
    for term, coeff in surface.even_terms.items():
        if coeff is not None:
            asphere += coeff * (r**term)
    return base + asphere, None


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
    fallback, fallback_warning = _formula_sag(surface, r)
    if fallback is not None:
        return fallback, f"formula fallback after {zemax_warning}"
    return None, f"{zemax_warning}; {fallback_warning}"


def _min_gap_to_radius(
    lde: Any,
    a: SurfaceData,
    b: SurfaceData,
    radius_max: float | None,
) -> tuple[float | None, float | None, str]:
    if radius_max is None:
        return None, None, "radius_max unknown"
    if radius_max < 0:
        return None, None, "radius_max negative"
    if a.thickness is None:
        return None, None, f"S{a.surface_number} thickness unknown"

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
    note = f"{len(invalid)} invalid samples; first: {invalid[0]}" if invalid else ""
    return min_gap, min_radius, note


def _ttl_s1_to_image(surfaces: list[SurfaceData]) -> float | None:
    total = 0.0
    found = False
    for surface in surfaces[1:-1]:
        if surface.thickness is not None and math.isfinite(surface.thickness):
            total += surface.thickness
            found = True
    return total if found else None


def _required_increase(min_gap: float | None, target_gap: float) -> float | None:
    if min_gap is None:
        return None
    return max(0.0, target_gap - min_gap)


def _gap_status(min_gap: float | None) -> str:
    if min_gap is None:
        return "unknown"
    if min_gap < 0:
        return "overlap"
    if min_gap < 0.05:
        return "dangerously_small_gap"
    return "clear"


def _parse_trace_points(raw_path: Path) -> dict[int, tuple[float, float]]:
    from diagnose_ray_failure_surfaces import _parse_trace_rows

    if not raw_path.exists():
        return {}
    rows = _parse_trace_rows(_read_text_file(raw_path))
    points: dict[int, tuple[float, float]] = {}
    for surface, row in rows.items():
        x = _to_float(row.get("x"))
        y = _to_float(row.get("y"))
        if x is not None and y is not None:
            points[surface] = (x, y)
    return points


def _trace_rows(
    oss: Any,
    raw_dir: Path,
    *,
    fields: list[dict[str, Any]],
    image_surface: int,
) -> list[dict[str, Any]]:
    field_numbers = {field: _field_number(fields, field) for field in FIELDS_DEG}
    rows: list[dict[str, Any]] = []
    for field in FIELDS_DEG:
        field_number = field_numbers[field]
        for px, py in PUPIL_SAMPLES:
            raw_path = raw_dir / f"field_{_field_key(field)}_{_pupil_key(px, py)}.txt"
            if field_number is None:
                trace = {
                    "field_deg": field,
                    "field_number": None,
                    "px": px,
                    "py": py,
                    "status": "failed",
                    "failed_surface": None,
                    "failure_reason": "Requested field not present in lens field table.",
                    "last_success_surface": None,
                    "raw_trace_file": str(raw_path),
                }
            else:
                trace, _text = _trace_one(
                    oss,
                    field_number=field_number,
                    field_deg=field,
                    px=px,
                    py=py,
                    image_surface=image_surface,
                    raw_path=raw_path,
                )
            points = _parse_trace_points(raw_path)
            for target in TARGET_SURFACES:
                point = points.get(target)
                trace[f"s{target}_ray_radius"] = None if point is None else math.hypot(point[0], point[1])
            last_success = trace.get("last_success_surface")
            try:
                last_success_int = int(last_success) if last_success is not None else None
            except (TypeError, ValueError):
                last_success_int = None
            if last_success_int is not None:
                point = points.get(last_success_int)
                trace["last_success_ray_radius"] = None if point is None else math.hypot(point[0], point[1])
            else:
                trace["last_success_ray_radius"] = None
            rows.append(trace)
    return rows


def _required_radius_by_field(trace_rows: list[dict[str, Any]], target_surface: int) -> dict[float, dict[str, Any]]:
    result: dict[float, dict[str, Any]] = {}
    for field in FIELDS_DEG:
        exact_values: list[float] = []
        lower_bound_values: list[float] = []
        failures_on_target = 0
        for row in trace_rows:
            if _to_float(row.get("field_deg")) != field:
                continue
            exact = _to_float(row.get(f"s{target_surface}_ray_radius"))
            if exact is not None:
                exact_values.append(exact)
            failed_surface = row.get("failed_surface")
            try:
                failed_surface_int = int(failed_surface) if failed_surface is not None else None
            except (TypeError, ValueError):
                failed_surface_int = None
            if failed_surface_int == target_surface:
                failures_on_target += 1
                if exact is not None:
                    lower_bound_values.append(exact)
                else:
                    lower = _to_float(row.get("last_success_ray_radius"))
                    if lower is not None:
                        lower_bound_values.append(lower)
        all_values = exact_values + lower_bound_values
        required = max(all_values) if all_values else None
        result[field] = {
            "required_radius": required,
            "exact_max_radius": max(exact_values) if exact_values else None,
            "failure_lower_bound_radius": max(lower_bound_values) if lower_bound_values else None,
            "failures_on_surface": failures_on_target,
            "estimate_note": (
                "includes lower-bound estimate from failed rays"
                if lower_bound_values
                else "exact traced surface heights only"
            ),
        }
    return result


def _overall_required(field_data: dict[float, dict[str, Any]]) -> float | None:
    values = [_to_float(row.get("required_radius")) for row in field_data.values()]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "surface",
        "field_deg",
        "current_semi_diameter",
        "required_radius",
        "exact_max_radius",
        "failure_lower_bound_radius",
        "failures_on_surface",
        "recommended_clear_semi_diameter",
        "adjacent_pair",
        "adjacent_surface_semi_diameter",
        "common_radius_used_for_gap",
        "min_gap_at_recommended_clear",
        "min_gap_radius",
        "gap_status",
        "increase_for_gap_ge_0p05",
        "estimated_ttl_if_0p05",
        "ttl_lt_18_if_0p05",
        "increase_for_gap_ge_0p10",
        "estimated_ttl_if_0p10",
        "ttl_lt_18_if_0p10",
        "estimate_note",
        "gap_note",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    ttl: float | None,
    surface_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
) -> None:
    by_surface = {row["surface"]: row for row in surface_rows if row["field_deg"] == "overall"}
    s4 = by_surface.get("S4")
    s6 = by_surface.get("S6")
    s6_limited = False
    if s6:
        min_gap = _to_float(s6.get("min_gap_at_recommended_clear"))
        inc_005 = _to_float(s6.get("increase_for_gap_ge_0p05"))
        s6_limited = (min_gap is not None and min_gap < 0.05) or (inc_005 is not None and inc_005 > 0)

    failed_rows = [row for row in trace_rows if row.get("status") == "failed"]
    lines = [
        "S4/S6 Required Aperture Diagnostic",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        f"current_ttl_s1_to_image: {_fmt(ttl)}",
        "",
        "[overall]",
    ]
    for row in (s4, s6):
        if not row:
            continue
        lines.extend(
            [
                f"{row['surface']}:",
                f"  current_semi_diameter: {_fmt(row.get('current_semi_diameter'))}",
                f"  required_radius: {_fmt(row.get('required_radius'))}",
                f"  recommended_clear_semi_diameter: {_fmt(row.get('recommended_clear_semi_diameter'))}",
                f"  adjacent_pair: {row.get('adjacent_pair')}",
                f"  common_radius_used_for_gap: {_fmt(row.get('common_radius_used_for_gap'))}",
                f"  min_gap_at_recommended_clear: {_fmt(row.get('min_gap_at_recommended_clear'))} ({row.get('gap_status')})",
                f"  increase_for_gap>=0.05: {_fmt(row.get('increase_for_gap_ge_0p05'))}",
                f"  estimated_ttl_if_0.05: {_fmt(row.get('estimated_ttl_if_0p05'))}; TTL<18={row.get('ttl_lt_18_if_0p05')}",
                f"  increase_for_gap>=0.10: {_fmt(row.get('increase_for_gap_ge_0p10'))}",
                f"  estimated_ttl_if_0.10: {_fmt(row.get('estimated_ttl_if_0p10'))}; TTL<18={row.get('ttl_lt_18_if_0p10')}",
            ]
        )

    lines.extend(["", "[by_field]"])
    for row in surface_rows:
        if row["field_deg"] == "overall":
            continue
        lines.append(
            f"{row['surface']} field={_fmt(row.get('field_deg'))}: "
            f"required={_fmt(row.get('required_radius'))}, failures={row.get('failures_on_surface')}, "
            f"recommended={_fmt(row.get('recommended_clear_semi_diameter'))}, note={row.get('estimate_note')}"
        )

    lines.extend(["", "[trace_failure_context]"])
    if failed_rows:
        for row in failed_rows:
            if row.get("failed_surface") in (4, 6, "4", "6"):
                lines.append(
                    "  "
                    f"field={_fmt(row.get('field_deg'))}, pupil=({_fmt(row.get('px'))},{_fmt(row.get('py'))}), "
                    f"failed_surface=S{row.get('failed_surface')}, "
                    f"last_success=S{row.get('last_success_surface')}, "
                    f"last_success_radius={_fmt(row.get('last_success_ray_radius'))}"
                )
    else:
        lines.append("  no failed sampled rays")

    lines.extend(["", "[conclusion]"])
    if s4:
        s4_gap = _to_float(s4.get("min_gap_at_recommended_clear"))
        feasible = s4_gap is not None and s4_gap >= 0.05
        lines.append(f"S4 aperture expansion feasible without extra S4 thickness? {str(feasible).lower()}")
    if s6:
        s6_gap = _to_float(s6.get("min_gap_at_recommended_clear"))
        feasible = s6_gap is not None and s6_gap >= 0.05
        lines.append(f"S6 aperture expansion feasible without extra S6/S7 gap? {str(feasible).lower()}")
    lines.append(f"S6/S7 0.05 mm air gap appears limiting? {str(s6_limited).lower()}")
    if s6_limited:
        lines.append("S6 failures are likely tied to the very small S6->S7 air gap / clear aperture interaction; pure aperture enlargement may reintroduce overlap.")
    lines.append("If required apertures exceed overlap-safe radii with large thickness increases, the repair is trending toward front/mid-group structural redesign rather than aperture-only adjustment.")
    lines.extend(
        [
            "",
            "[files]",
            f"s4_s6_required_aperture_table: {path.parent / 's4_s6_required_aperture_table.csv'}",
            f"s4_s6_required_aperture_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_surface_rows(
    *,
    lde: Any,
    surfaces: dict[int, SurfaceData],
    ttl: float | None,
    required_by_surface: dict[int, dict[float, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in TARGET_SURFACES:
        pair = PAIR_BY_TARGET[target]
        a = surfaces[pair[0]]
        b = surfaces[pair[1]]
        adjacent_sd = b.semi_diameter
        field_data = required_by_surface[target]
        overall_required = _overall_required(field_data)
        recommended = None if overall_required is None else overall_required + SAFETY_MARGIN
        common_radius = None
        if recommended is not None and adjacent_sd is not None:
            common_radius = min(recommended, adjacent_sd)
        elif recommended is not None:
            common_radius = recommended
        min_gap, min_radius, gap_note = _min_gap_to_radius(lde, a, b, common_radius)
        inc_005 = _required_increase(min_gap, 0.05)
        inc_010 = _required_increase(min_gap, 0.10)
        ttl_005 = None if ttl is None or inc_005 is None else ttl + inc_005
        ttl_010 = None if ttl is None or inc_010 is None else ttl + inc_010

        for field, data in field_data.items():
            req = _to_float(data.get("required_radius"))
            rows.append(
                {
                    "surface": f"S{target}",
                    "field_deg": field,
                    "current_semi_diameter": a.semi_diameter,
                    "required_radius": req,
                    "exact_max_radius": data.get("exact_max_radius"),
                    "failure_lower_bound_radius": data.get("failure_lower_bound_radius"),
                    "failures_on_surface": data.get("failures_on_surface"),
                    "recommended_clear_semi_diameter": None if req is None else req + SAFETY_MARGIN,
                    "adjacent_pair": f"S{pair[0]}->S{pair[1]}",
                    "adjacent_surface_semi_diameter": adjacent_sd,
                    "common_radius_used_for_gap": common_radius,
                    "min_gap_at_recommended_clear": min_gap,
                    "min_gap_radius": min_radius,
                    "gap_status": _gap_status(min_gap),
                    "increase_for_gap_ge_0p05": inc_005,
                    "estimated_ttl_if_0p05": ttl_005,
                    "ttl_lt_18_if_0p05": None if ttl_005 is None else ttl_005 < TTL_LIMIT_MM,
                    "increase_for_gap_ge_0p10": inc_010,
                    "estimated_ttl_if_0p10": ttl_010,
                    "ttl_lt_18_if_0p10": None if ttl_010 is None else ttl_010 < TTL_LIMIT_MM,
                    "estimate_note": data.get("estimate_note"),
                    "gap_note": gap_note,
                }
            )
        rows.append(
            {
                "surface": f"S{target}",
                "field_deg": "overall",
                "current_semi_diameter": a.semi_diameter,
                "required_radius": overall_required,
                "exact_max_radius": max(
                    [_to_float(data.get("exact_max_radius")) for data in field_data.values() if _to_float(data.get("exact_max_radius")) is not None],
                    default=None,
                ),
                "failure_lower_bound_radius": max(
                    [
                        _to_float(data.get("failure_lower_bound_radius"))
                        for data in field_data.values()
                        if _to_float(data.get("failure_lower_bound_radius")) is not None
                    ],
                    default=None,
                ),
                "failures_on_surface": sum(int(data.get("failures_on_surface") or 0) for data in field_data.values()),
                "recommended_clear_semi_diameter": recommended,
                "adjacent_pair": f"S{pair[0]}->S{pair[1]}",
                "adjacent_surface_semi_diameter": adjacent_sd,
                "common_radius_used_for_gap": common_radius,
                "min_gap_at_recommended_clear": min_gap,
                "min_gap_radius": min_radius,
                "gap_status": _gap_status(min_gap),
                "increase_for_gap_ge_0p05": inc_005,
                "estimated_ttl_if_0p05": ttl_005,
                "ttl_lt_18_if_0p05": None if ttl_005 is None else ttl_005 < TTL_LIMIT_MM,
                "increase_for_gap_ge_0p10": inc_010,
                "estimated_ttl_if_0p10": ttl_010,
                "ttl_lt_18_if_0p10": None if ttl_010 is None else ttl_010 < TTL_LIMIT_MM,
                "estimate_note": "overall max across fields",
                "gap_note": gap_note,
            }
        )
    return rows


def diagnose_s4_s6_required_aperture(lens_path: str) -> None:
    lens = Path(lens_path)
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "s4_s6_required_aperture" / run_id
    raw_dir = out_dir / "raw_single_ray_traces"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"actual lens path: {lens}", flush=True)
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    print("Loading lens read-only...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    image_surface = count - 1
    surfaces_list = [_read_surface(lde.GetSurfaceAt(index)) for index in range(count)]
    surfaces = {surface.surface_number: surface for surface in surfaces_list}
    ttl = _ttl_s1_to_image(surfaces_list)
    fields = _field_table(oss)

    trace_rows = _trace_rows(oss, raw_dir, fields=fields, image_surface=image_surface)
    required_by_surface = {
        target: _required_radius_by_field(trace_rows, target) for target in TARGET_SURFACES
    }
    table_rows = _make_surface_rows(lde=lde, surfaces=surfaces, ttl=ttl, required_by_surface=required_by_surface)

    table_path = out_dir / "s4_s6_required_aperture_table.csv"
    report_path = out_dir / "s4_s6_required_aperture_report.txt"
    _write_csv(table_path, table_rows)
    _write_report(report_path, lens=lens, run_id=run_id, ttl=ttl, surface_rows=table_rows, trace_rows=trace_rows)
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "lens": str(lens),
                "output_folder": str(out_dir),
                "read_only": True,
                "saved_lens": False,
                "optimized": False,
                "fields": list(FIELDS_DEG),
                "pupil_samples": list(PUPIL_SAMPLES),
                "target_surfaces": list(TARGET_SURFACES),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    close_all_analysis_windows(oss)

    print(f"table: {table_path}", flush=True)
    print(f"report: {report_path}", flush=True)
    for row in table_rows:
        if row["field_deg"] == "overall":
            print(
                f"{row['surface']}: required={_fmt(row['required_radius'])}, "
                f"recommended={_fmt(row['recommended_clear_semi_diameter'])}, "
                f"min_gap={_fmt(row['min_gap_at_recommended_clear'])}, "
                f"gap_status={row['gap_status']}",
                flush=True,
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only S4/S6 required aperture and overlap feasibility diagnostic.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script does not save or modify it.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_s4_s6_required_aperture(args.lens)
