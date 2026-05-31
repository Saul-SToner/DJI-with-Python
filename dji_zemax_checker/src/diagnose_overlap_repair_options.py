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
SAMPLE_COUNT = 300
SAFETY_GAPS_MM = (0.0, 0.05, 0.10, 0.20)
SEMI_DIAMETER_SCALES = (1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70)
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
TTL_LIMIT_MM = 18.0
BFL_LIMIT_MM = 2.3


@dataclass
class SurfaceGeometry:
    surface_number: int
    comment: str
    type_name: str
    radius: float | None
    thickness: float | None
    material: str
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


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _is_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


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


def _read_surface(surface: Any) -> SurfaceGeometry:
    return SurfaceGeometry(
        surface_number=int(_safe_get(surface, "SurfaceNumber", -1)),
        comment=str(_safe_get(surface, "Comment", "") or ""),
        type_name=str(_safe_get(surface, "TypeName", "") or ""),
        radius=_to_float(_safe_get(surface, "Radius")),
        thickness=_to_float(_safe_get(surface, "Thickness")),
        material=str(_safe_get(surface, "Material", "") or ""),
        semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
        conic=_to_float(_safe_get(surface, "Conic")),
        even_terms={term: _get_even_term(surface, term) for term in EVEN_TERMS},
    )


def _formula_sag(surface: SurfaceGeometry, r: float) -> tuple[float | None, str | None]:
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
    for term, coefficient in surface.even_terms.items():
        if coefficient is not None:
            asphere += coefficient * (r**term)
    return base_sag + asphere, None


def _zemax_sag(lde: Any, surface: SurfaceGeometry, r: float) -> tuple[float | None, str | None]:
    try:
        result = lde.GetSag(surface.surface_number, r, 0.0)
    except Exception as exc:
        return None, f"GetSag failed: {type(exc).__name__}: {exc!r}"
    if not isinstance(result, tuple) or not result:
        return None, f"GetSag returned unexpected result: {result!r}"
    if isinstance(result[0], bool) and not result[0]:
        return None, f"GetSag success=False: {result!r}"
    for item in result[1:]:
        value = _to_float(item)
        if value is not None:
            return value, None
    return None, f"GetSag returned no finite sag: {result!r}"


def _surface_sag(lde: Any, surface: SurfaceGeometry, r: float) -> tuple[float | None, str | None]:
    sag, warning = _zemax_sag(lde, surface, r)
    if sag is not None:
        return sag, None
    fallback, fallback_warning = _formula_sag(surface, r)
    if fallback is not None:
        return fallback, f"formula fallback after {warning}"
    return None, f"{warning}; {fallback_warning}"


def _pair_classification(a: SurfaceGeometry, b: SurfaceGeometry) -> str:
    if a.surface_number in (2, 4):
        return "air gap problem"
    if a.surface_number in (7, 9):
        return "glass element internal edge thickness problem"
    material = a.material.strip()
    comments = f"{a.comment} {b.comment}".lower()
    if material:
        if "filter" in comments or "cover" in comments or (_is_plane(a.radius) and _is_plane(b.radius)):
            return "filter / cover glass internal thickness"
        return "glass element internal edge thickness problem"
    if "filter" in comments or "cover" in comments:
        return "filter / cover glass gap"
    return "air gap problem"


def _min_gap_for_radius(
    lde: Any,
    a: SurfaceGeometry,
    b: SurfaceGeometry,
    common_radius: float,
) -> tuple[float | None, float | None, int, str]:
    thickness = a.thickness
    if thickness is None or not math.isfinite(thickness):
        return None, None, 0, "surface thickness unknown"

    min_gap: float | None = None
    min_gap_radius: float | None = None
    invalid: list[str] = []
    valid_count = 0
    for index in range(SAMPLE_COUNT + 1):
        r = common_radius * index / SAMPLE_COUNT
        sag_a, warn_a = _surface_sag(lde, a, r)
        sag_b, warn_b = _surface_sag(lde, b, r)
        if sag_a is None or sag_b is None:
            invalid.append(f"r={r:g}: S{a.surface_number} {warn_a}; S{b.surface_number} {warn_b}")
            continue
        gap = thickness + sag_b - sag_a
        valid_count += 1
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_gap_radius = r
    note = ""
    if invalid:
        note = f"{len(invalid)} invalid sag samples; first: {invalid[0]}"
    return min_gap, min_gap_radius, valid_count, note


def _common_radius(a: SurfaceGeometry, b: SurfaceGeometry) -> float | None:
    if _is_finite(a.semi_diameter) and _is_finite(b.semi_diameter):
        assert a.semi_diameter is not None and b.semi_diameter is not None
        return min(a.semi_diameter, b.semi_diameter)
    return None


def _largest_radius_without_overlap(
    lde: Any,
    a: SurfaceGeometry,
    b: SurfaceGeometry,
    full_radius: float,
) -> tuple[float | None, float | None]:
    center_gap, _r, _count, _note = _min_gap_for_radius(lde, a, b, 0.0)
    if center_gap is None or center_gap < 0:
        return None, None
    full_gap, _fr, _fc, _fn = _min_gap_for_radius(lde, a, b, full_radius)
    if full_gap is not None and full_gap >= 0:
        return full_radius, 1.0

    lo = 0.0
    hi = full_radius
    best = 0.0
    for _ in range(32):
        mid = (lo + hi) / 2.0
        gap, _mr, _count, _note = _min_gap_for_radius(lde, a, b, mid)
        if gap is not None and gap >= 0:
            best = mid
            lo = mid
        else:
            hi = mid
    return best, best / full_radius if full_radius else None


def _ttl_s1_to_image(surfaces: list[SurfaceGeometry]) -> float | None:
    if len(surfaces) <= 2:
        return None
    total = 0.0
    used = False
    # surfaces includes OBJ at index 0 and image as the last surface.
    for surface in surfaces[1:-1]:
        thickness = surface.thickness
        if thickness is not None and math.isfinite(thickness):
            total += thickness
            used = True
    return total if used else None


def _bfl_from_image_space(surfaces: list[SurfaceGeometry]) -> float | None:
    if len(surfaces) < 2:
        return None
    return surfaces[-2].thickness


def _status_for_gap(gap: float | None) -> str:
    if gap is None:
        return "unknown"
    return "ok" if gap >= 0 else "overlap"


def _analyze_pair(
    lde: Any,
    a: SurfaceGeometry,
    b: SurfaceGeometry,
    ttl: float | None,
) -> dict[str, Any]:
    common = _common_radius(a, b)
    if common is None or common <= 0:
        return {
            "surface_a": a.surface_number,
            "surface_b": b.surface_number,
            "classification": _pair_classification(a, b),
            "common_radius": common,
            "current_min_gap": None,
            "current_min_gap_radius": None,
            "status": "unknown",
            "notes": "semi-diameter unavailable; cannot sample",
        }

    min_gap, min_gap_radius, valid_count, note = _min_gap_for_radius(lde, a, b, common)
    largest_radius, largest_scale = _largest_radius_without_overlap(lde, a, b, common)
    row: dict[str, Any] = {
        "surface_a": a.surface_number,
        "surface_b": b.surface_number,
        "comment_a": a.comment,
        "comment_b": b.comment,
        "classification": _pair_classification(a, b),
        "radius_a": a.radius,
        "radius_b": b.radius,
        "thickness_a": a.thickness,
        "glass_after_a": a.material,
        "semi_diameter_a": a.semi_diameter,
        "semi_diameter_b": b.semi_diameter,
        "common_radius": common,
        "current_min_gap": min_gap,
        "current_min_gap_radius": min_gap_radius,
        "sample_count": valid_count,
        "status": _status_for_gap(min_gap),
        "max_common_radius_for_gap_ge_0": largest_radius,
        "max_common_radius_scale_for_gap_ge_0": largest_scale,
        "notes": note,
    }

    for safety_gap in SAFETY_GAPS_MM:
        label = str(safety_gap).replace(".", "p")
        add = None if min_gap is None else max(0.0, safety_gap - min_gap)
        ttl_after = None if ttl is None or add is None else ttl + add
        row[f"add_thickness_for_gap_{label}"] = add
        row[f"ttl_after_gap_{label}"] = ttl_after
        row[f"ttl_after_gap_{label}_lt_18"] = None if ttl_after is None else ttl_after < TTL_LIMIT_MM

    for scale in SEMI_DIAMETER_SCALES:
        label = f"{int(round(scale * 100))}pct"
        scaled_radius = common * scale
        gap, radius, count, scan_note = _min_gap_for_radius(lde, a, b, scaled_radius)
        row[f"sd_{label}_radius"] = scaled_radius
        row[f"sd_{label}_min_gap"] = gap
        row[f"sd_{label}_min_gap_radius"] = radius
        row[f"sd_{label}_gap_ge_0"] = None if gap is None else gap >= 0
        if scan_note and not row["notes"]:
            row["notes"] = scan_note
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    base_fields = [
        "surface_a",
        "surface_b",
        "comment_a",
        "comment_b",
        "classification",
        "radius_a",
        "radius_b",
        "thickness_a",
        "glass_after_a",
        "semi_diameter_a",
        "semi_diameter_b",
        "common_radius",
        "current_min_gap",
        "current_min_gap_radius",
        "sample_count",
        "status",
        "max_common_radius_for_gap_ge_0",
        "max_common_radius_scale_for_gap_ge_0",
    ]
    thickness_fields: list[str] = []
    for safety_gap in SAFETY_GAPS_MM:
        label = str(safety_gap).replace(".", "p")
        thickness_fields.extend(
            [
                f"add_thickness_for_gap_{label}",
                f"ttl_after_gap_{label}",
                f"ttl_after_gap_{label}_lt_18",
            ]
        )
    sd_fields: list[str] = []
    for scale in SEMI_DIAMETER_SCALES:
        label = f"{int(round(scale * 100))}pct"
        sd_fields.extend(
            [
                f"sd_{label}_radius",
                f"sd_{label}_min_gap",
                f"sd_{label}_min_gap_radius",
                f"sd_{label}_gap_ge_0",
            ]
        )
    fieldnames = base_fields + thickness_fields + sd_fields + ["notes"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: Any, digits: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    return f"{number:.{digits}g}"


def _write_report(
    path: Path,
    lens_path: str,
    ttl: float | None,
    bfl: float | None,
    rows: list[dict[str, Any]],
) -> None:
    overlaps = [row for row in rows if row.get("status") == "overlap"]
    air_overlaps = [row for row in overlaps if str(row.get("classification")) == "air gap problem"]
    internal_overlaps = [
        row for row in overlaps if "internal edge thickness" in str(row.get("classification"))
    ]
    ttl_margin = None if ttl is None else TTL_LIMIT_MM - ttl

    air_zero_add = sum(
        float(row.get("add_thickness_for_gap_0p0") or 0.0)
        for row in air_overlaps
        if row.get("add_thickness_for_gap_0p0") is not None
    )
    air_safe_005_add = sum(
        float(row.get("add_thickness_for_gap_0p05") or 0.0)
        for row in air_overlaps
        if row.get("add_thickness_for_gap_0p05") is not None
    )

    can_fix_air_zero = ttl is not None and ttl + air_zero_add < TTL_LIMIT_MM
    can_fix_air_005 = ttl is not None and ttl + air_safe_005_add < TTL_LIMIT_MM
    only_air_can_fix_all = bool(overlaps) and not internal_overlaps and can_fix_air_zero

    lines = [
        "Overlap Repair Options Diagnostic",
        f"lens_path: {lens_path}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        f"current_ttl_s1_to_image_mm: {_fmt(ttl)}",
        f"ttl_limit_mm: {TTL_LIMIT_MM}",
        f"ttl_margin_mm: {_fmt(ttl_margin)}",
        f"current_bfl_image_space_mm: {_fmt(bfl)}",
        f"bfl_limit_mm: {BFL_LIMIT_MM}",
        f"bfl_shortfall_mm: {_fmt(None if bfl is None else BFL_LIMIT_MM - bfl)}",
        "",
        "Known interpretation rules",
        "S2->S3 and S4->S5 are air gap problems.",
        "S7->S8 and S9->S10 are same-element internal edge-thickness problems.",
        "",
        "Overall judgment",
        f"overlap_pair_count: {len(overlaps)}",
        f"air_gap_overlap_count: {len(air_overlaps)}",
        f"internal_edge_overlap_count: {len(internal_overlaps)}",
        f"sum_air_gap_add_to_gap_0_mm: {_fmt(air_zero_add)}",
        f"ttl_after_air_gap_add_to_gap_0_mm: {_fmt(None if ttl is None else ttl + air_zero_add)}",
        f"air_gap_only_to_zero_keeps_ttl_lt_18: {can_fix_air_zero}",
        f"sum_air_gap_add_to_gap_0p05_mm: {_fmt(air_safe_005_add)}",
        f"ttl_after_air_gap_add_to_gap_0p05_mm: {_fmt(None if ttl is None else ttl + air_safe_005_add)}",
        f"air_gap_only_to_0p05_keeps_ttl_lt_18: {can_fix_air_005}",
        f"only_air_gap_repair_can_fix_all_overlaps: {only_air_can_fix_all}",
        "",
    ]

    if internal_overlaps:
        lines.append(
            "Conclusion: Air-gap increases alone cannot fix all reported overlaps because at least one same-element internal edge-thickness pair overlaps."
        )
    elif only_air_can_fix_all:
        lines.append("Conclusion: All overlap pairs are air gaps and can be cleared by spacing increases within TTL <18 mm.")
    else:
        lines.append("Conclusion: Air-gap repair is not sufficient or TTL margin is not enough.")

    if bfl is not None and bfl <= BFL_LIMIT_MM:
        lines.append(
            "BFL warning: increasing front/intermediate thickness may worsen total length pressure and does not solve BFL >2.3 mm."
        )

    lines.extend(["", "Per-pair options"])
    for row in overlaps:
        pair = f"S{row['surface_a']} -> S{row['surface_b']}"
        lines.extend(
            [
                "",
                pair,
                f"classification: {row['classification']}",
                f"current_min_gap_mm: {_fmt(row.get('current_min_gap'))}",
                f"current_min_gap_radius_mm: {_fmt(row.get('current_min_gap_radius'))}",
                f"common_radius_mm: {_fmt(row.get('common_radius'))}",
                f"add_thickness_for_gap_0_mm: {_fmt(row.get('add_thickness_for_gap_0p0'))}",
                f"add_thickness_for_gap_0p05_mm: {_fmt(row.get('add_thickness_for_gap_0p05'))}",
                f"add_thickness_for_gap_0p10_mm: {_fmt(row.get('add_thickness_for_gap_0p1'))}",
                f"add_thickness_for_gap_0p20_mm: {_fmt(row.get('add_thickness_for_gap_0p2'))}",
                f"ttl_after_gap_0p05_mm: {_fmt(row.get('ttl_after_gap_0p05'))}",
                f"max_common_radius_for_gap_ge_0_mm: {_fmt(row.get('max_common_radius_for_gap_ge_0'))}",
                f"max_common_radius_scale_for_gap_ge_0: {_fmt(row.get('max_common_radius_scale_for_gap_ge_0'))}",
            ]
        )
        sd_turns_positive = [
            f"{int(round(scale * 100))}%"
            for scale in SEMI_DIAMETER_SCALES
            if row.get(f"sd_{int(round(scale * 100))}pct_gap_ge_0") is True
        ]
        if sd_turns_positive:
            lines.append(f"semi_diameter_grid_first_safe: {sd_turns_positive[0]}")
        else:
            lines.append("semi_diameter_grid_first_safe: none among 100/95/90/85/80/75/70 percent")

        if row["classification"] == "air gap problem":
            lines.append("repair_note: candidate repair is increasing the preceding air thickness, but TTL/BFL must be rechecked.")
        elif "internal edge thickness" in str(row["classification"]):
            lines.append("repair_note: this cannot be solved by adjacent air spacing alone; center thickness, curvature, or clear aperture must change.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_overlap_repair_options(lens_path: str) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "overlap_repair_options" / run_id
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
    ttl = _ttl_s1_to_image(surfaces)
    bfl = _bfl_from_image_space(surfaces)

    rows: list[dict[str, Any]] = []
    for index in range(count - 1):
        row = _analyze_pair(lde, surfaces[index], surfaces[index + 1], ttl)
        if row.get("status") == "overlap":
            rows.append(row)

    csv_path = out_dir / "overlap_repair_options.csv"
    report_path = out_dir / "overlap_repair_options_report.txt"
    _write_csv(csv_path, rows)
    _write_report(report_path, lens_path, ttl, bfl, rows)

    print(f"overlap_pair_count: {len(rows)}", flush=True)
    print(f"ttl_s1_to_image: {_fmt(ttl)}", flush=True)
    print(f"bfl_image_space: {_fmt(bfl)}", flush=True)
    print(f"csv path: {csv_path}", flush=True)
    print(f"report path: {report_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostic for overlap repair options in a Zemax lens."
    )
    parser.add_argument(
        "--lens",
        required=True,
        help="Path to the lens file to analyze. The script does not modify or save the lens.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_overlap_repair_options(args.lens)
