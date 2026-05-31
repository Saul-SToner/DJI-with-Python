from __future__ import annotations

import csv
import argparse
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
SAMPLE_COUNT = 200
DANGEROUS_GAP_MM = 0.03
EVEN_TERMS = (4, 6, 8, 10, 12)


@dataclass
class SurfaceGeometry:
    surface_number: int
    comment: str | None
    type_name: str | None
    radius: float | None
    thickness: float | None
    material: str | None
    conic: float | None
    semi_diameter: float | None
    even_terms: dict[int, float | None]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _is_plane(radius: float | None) -> bool:
    return radius is None or radius == 0 or math.isinf(radius)


def _get_even_term(surface: Any, term: int) -> float | None:
    data = _safe_get(surface, "SurfaceData")
    if data is not None:
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


def _read_surface_geometry(surface: Any) -> SurfaceGeometry:
    return SurfaceGeometry(
        surface_number=int(_safe_get(surface, "SurfaceNumber", -1)),
        comment=str(_safe_get(surface, "Comment", "") or ""),
        type_name=str(_safe_get(surface, "TypeName", "") or ""),
        radius=_to_float(_safe_get(surface, "Radius")),
        thickness=_to_float(_safe_get(surface, "Thickness")),
        material=str(_safe_get(surface, "Material", "") or ""),
        conic=_to_float(_safe_get(surface, "Conic")),
        semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
        even_terms={term: _get_even_term(surface, term) for term in EVEN_TERMS},
    )


def _zemax_sag(lde: Any, surface_number: int, r: float) -> tuple[float | None, str | None]:
    try:
        result = lde.GetSag(surface_number, r, 0.0)
    except Exception as exc:
        return None, f"Zemax GetSag failed: {type(exc).__name__}: {exc!r}"

    if not isinstance(result, tuple) or not result:
        return None, f"Zemax GetSag returned unexpected result: {result!r}"

    success = result[0]
    if isinstance(success, bool) and not success:
        return None, f"Zemax GetSag returned success=False: {result!r}"

    for item in result[1:]:
        value = _to_float(item)
        if value is not None and math.isfinite(value):
            return value, None

    return None, f"Zemax GetSag returned no finite sag value: {result!r}"


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
            return None, f"invalid sag: sqrt argument is negative ({sqrt_arg:g})"
        denominator = 1.0 + math.sqrt(sqrt_arg)
        if denominator == 0:
            return None, "invalid sag: denominator is zero"
        base_sag = c * r * r / denominator

    asphere = 0.0
    for term, coefficient in surface.even_terms.items():
        if coefficient is not None:
            asphere += coefficient * (r**term)
    return base_sag + asphere, None


def _surface_sag(
    lde: Any,
    surface: SurfaceGeometry,
    r: float,
) -> tuple[float | None, str]:
    sag, warning = _zemax_sag(lde, surface.surface_number, r)
    if sag is not None:
        return sag, "zemax"

    formula_sag, formula_warning = _formula_sag(surface, r)
    if formula_sag is not None:
        return formula_sag, f"formula fallback after {warning}"
    return None, f"{warning}; {formula_warning}"


def _pair_classification(a: SurfaceGeometry, b: SurfaceGeometry) -> str:
    material = (a.material or "").strip()
    comments = f"{a.comment or ''} {b.comment or ''}".lower()
    if material:
        if "filter" in comments or "cover" in comments or (_is_plane(a.radius) and _is_plane(b.radius)):
            return "filter / cover glass internal thickness"
        return "glass element internal edge thickness"
    if "filter" in comments or "cover" in comments:
        return "filter / cover glass gap"
    return "air gap between separate elements"


def _gap_status(min_gap: float | None) -> str:
    if min_gap is None:
        return "unknown"
    if min_gap < 0:
        return "overlap"
    if min_gap < DANGEROUS_GAP_MM:
        return "dangerously small gap"
    return "ok"


def _check_adjacent_pair(
    lde: Any,
    a: SurfaceGeometry,
    b: SurfaceGeometry,
) -> dict[str, Any]:
    common_radius = None
    if _finite(a.semi_diameter) and _finite(b.semi_diameter):
        assert a.semi_diameter is not None and b.semi_diameter is not None
        common_radius = min(a.semi_diameter, b.semi_diameter)

    if common_radius is None or common_radius <= 0:
        return {
            "surface_a": a.surface_number,
            "surface_b": b.surface_number,
            "classification": _pair_classification(a, b),
            "sample_radius_max": common_radius,
            "sample_count": 0,
            "min_gap": None,
            "min_gap_radius": None,
            "status": "unknown",
            "invalid_sag_count": 0,
            "notes": "semi-diameter unknown or non-positive; sampling skipped",
        }

    thickness = a.thickness
    if thickness is None or not math.isfinite(thickness):
        return {
            "surface_a": a.surface_number,
            "surface_b": b.surface_number,
            "classification": _pair_classification(a, b),
            "sample_radius_max": common_radius,
            "sample_count": 0,
            "min_gap": None,
            "min_gap_radius": None,
            "status": "unknown",
            "invalid_sag_count": 0,
            "notes": "surface thickness is unknown or non-finite; sampling skipped",
        }

    min_gap: float | None = None
    min_gap_radius: float | None = None
    invalid_messages: list[str] = []
    valid_count = 0

    for index in range(SAMPLE_COUNT + 1):
        r = common_radius * index / SAMPLE_COUNT
        sag_a, source_a = _surface_sag(lde, a, r)
        sag_b, source_b = _surface_sag(lde, b, r)
        if sag_a is None or sag_b is None:
            invalid_messages.append(f"r={r:g}: S{a.surface_number} {source_a}; S{b.surface_number} {source_b}")
            continue

        gap = thickness + sag_b - sag_a
        valid_count += 1
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_gap_radius = r

    status = _gap_status(min_gap)
    note = ""
    if invalid_messages:
        note = f"{len(invalid_messages)} invalid sag samples; first: {invalid_messages[0]}"

    return {
        "surface_a": a.surface_number,
        "surface_b": b.surface_number,
        "classification": _pair_classification(a, b),
        "sample_radius_max": common_radius,
        "sample_count": valid_count,
        "min_gap": min_gap,
        "min_gap_radius": min_gap_radius,
        "status": status,
        "invalid_sag_count": len(invalid_messages),
        "notes": note,
    }


def _write_surface_geometry(path: Path, surfaces: list[SurfaceGeometry]) -> None:
    fieldnames = [
        "surface_number",
        "comment",
        "type",
        "radius",
        "thickness",
        "glass_material",
        "conic",
        "semi_diameter",
        "A4",
        "A6",
        "A8",
        "A10",
        "A12",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for surface in surfaces:
            row = {
                "surface_number": surface.surface_number,
                "comment": surface.comment,
                "type": surface.type_name,
                "radius": surface.radius,
                "thickness": surface.thickness,
                "glass_material": surface.material,
                "conic": surface.conic,
                "semi_diameter": surface.semi_diameter,
            }
            for term in EVEN_TERMS:
                row[f"A{term}"] = surface.even_terms.get(term)
            writer.writerow(row)


def _write_gap_check(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "surface_a",
        "surface_b",
        "classification",
        "sample_radius_max",
        "sample_count",
        "min_gap",
        "min_gap_radius",
        "status",
        "invalid_sag_count",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _likely_reason(row: dict[str, Any], a: SurfaceGeometry, b: SurfaceGeometry) -> str:
    classification = str(row.get("classification") or "")
    min_gap_radius = _to_float(row.get("min_gap_radius"))
    max_radius = _to_float(row.get("sample_radius_max"))
    if max_radius and min_gap_radius is not None and min_gap_radius > 0.8 * max_radius:
        return "automatic semi-diameter may be too large or edge sag is excessive"
    if "air gap" in classification and (a.thickness or 0) < 0.2:
        return "air gap is too small for the adjacent surface sags"
    if "filter" in classification:
        return "filter-cover spacing or plane cover geometry should be checked"
    return "curvature sag is large relative to center thickness/gap"


def _write_report(
    path: Path,
    lens_path: str,
    surfaces: list[SurfaceGeometry],
    gap_rows: list[dict[str, Any]],
) -> None:
    valid_rows = [row for row in gap_rows if _to_float(row.get("min_gap")) is not None]
    worst = min(valid_rows, key=lambda row: float(row["min_gap"])) if valid_rows else None
    overlaps = [row for row in gap_rows if row.get("status") == "overlap"]
    dangerous = [row for row in gap_rows if row.get("status") == "dangerously small gap"]
    surface_by_number = {surface.surface_number: surface for surface in surfaces}

    lines: list[str] = []
    lines.append("Lens Overlap Diagnostic")
    lines.append(f"lens_path: {lens_path}")
    lines.append(f"number_of_surfaces: {len(surfaces)}")
    lines.append(f"sample_count_per_pair: {SAMPLE_COUNT + 1}")
    lines.append("")
    lines.append(f"overlap_found: {'yes' if overlaps else 'no'}")
    lines.append(f"dangerously_small_gap_count: {len(dangerous)}")
    lines.append("")

    if worst is None:
        lines.append("worst_pair: unknown")
        lines.append("reason: no adjacent pair had enough valid sag/semi-diameter data")
    else:
        a = surface_by_number[int(worst["surface_a"])]
        b = surface_by_number[int(worst["surface_b"])]
        lines.append("Worst Pair")
        lines.append(f"surfaces: S{a.surface_number} -> S{b.surface_number}")
        lines.append(f"classification: {worst['classification']}")
        lines.append(f"status: {worst['status']}")
        lines.append(f"min_gap_mm: {worst['min_gap']}")
        lines.append(f"min_gap_radius_mm: {worst['min_gap_radius']}")
        lines.append(f"sample_radius_max_mm: {worst['sample_radius_max']}")
        lines.append("")
        lines.append("Surface A")
        lines.append(f"radius: {a.radius}")
        lines.append(f"thickness: {a.thickness}")
        lines.append(f"semi_diameter: {a.semi_diameter if a.semi_diameter is not None else 'unknown'}")
        lines.append(f"glass: {a.material}")
        lines.append("")
        lines.append("Surface B")
        lines.append(f"radius: {b.radius}")
        lines.append(f"thickness: {b.thickness}")
        lines.append(f"semi_diameter: {b.semi_diameter if b.semi_diameter is not None else 'unknown'}")
        lines.append(f"glass: {b.material}")
        lines.append("")
        lines.append(f"priority_suspected_reason: {_likely_reason(worst, a, b)}")
        if worst.get("notes"):
            lines.append(f"notes: {worst['notes']}")

    lines.append("")
    lines.append("Flagged Pairs")
    flagged = overlaps + dangerous
    if not flagged:
        lines.append("none")
    for row in sorted(flagged, key=lambda item: float(item["min_gap"])):
        lines.append(
            f"S{row['surface_a']} -> S{row['surface_b']}: "
            f"status={row['status']}, min_gap={row['min_gap']}, "
            f"r={row['min_gap_radius']}, class={row['classification']}"
        )

    invalid_rows = [row for row in gap_rows if int(row.get("invalid_sag_count") or 0) > 0]
    if invalid_rows:
        lines.append("")
        lines.append("Invalid Sag Warnings")
        for row in invalid_rows[:20]:
            lines.append(f"S{row['surface_a']} -> S{row['surface_b']}: {row['notes']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_lens_overlap(lens_path: str) -> None:
    lens_file = Path(lens_path)
    run_id = _run_id()
    output_dir = PROJECT_ROOT / "results" / "geometry_diagnostics" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"actual lens path: {lens_path}", flush=True)
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print(
            "[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.",
            flush=True,
        )
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    try:
        oss.load(lens_path, saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens read-only/no-save session: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    lde = oss.LDE
    number_of_surfaces = int(lde.NumberOfSurfaces)
    surfaces = [_read_surface_geometry(lde.GetSurfaceAt(index)) for index in range(number_of_surfaces)]
    gap_rows = [
        _check_adjacent_pair(lde, surfaces[index], surfaces[index + 1])
        for index in range(number_of_surfaces - 1)
    ]

    surface_path = output_dir / "surface_geometry.csv"
    gap_path = output_dir / "adjacent_gap_check.csv"
    report_path = output_dir / "overlap_report.txt"

    _write_surface_geometry(surface_path, surfaces)
    _write_gap_check(gap_path, gap_rows)
    _write_report(report_path, lens_path, surfaces, gap_rows)

    valid_rows = [row for row in gap_rows if _to_float(row.get("min_gap")) is not None]
    worst = min(valid_rows, key=lambda row: float(row["min_gap"])) if valid_rows else None
    worst_pair = f"S{worst['surface_a']} -> S{worst['surface_b']}" if worst else "unknown"
    worst_gap = worst["min_gap"] if worst else "unknown"

    print(f"lens path: {lens_path}", flush=True)
    print(f"number of surfaces: {number_of_surfaces}", flush=True)
    print(f"worst pair: {worst_pair}", flush=True)
    print(f"worst min_gap: {worst_gap}", flush=True)
    print(f"report path: {report_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only geometry overlap diagnostic for a specified Zemax lens."
    )
    parser.add_argument(
        "--lens",
        required=True,
        help="Path to the lens file to analyze. Required; no default lens path is used.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_lens_overlap(args.lens)
