from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from zospy.analyses.raysandspots.single_ray_trace import SingleRayTrace
from zosapi_cleanup import close_all_analysis_windows


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
FIELDS_DEG = [0.0, 21.0, 35.0, 49.0, 63.0, 70.0]
PUPIL_SAMPLES = [
    (0.0, 0.0),
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (0.707, 0.707),
    (0.707, -0.707),
    (-0.707, 0.707),
    (-0.707, -0.707),
]
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
SURFACE_A = 7
SURFACE_B = 8
SAFETY_GAPS = (0.05, 0.10, 0.20)
SAMPLE_COUNT = 500


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


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "mbcs"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(errors="replace")


def _numbers_from_line(line: str) -> list[float]:
    values: list[float] = []
    for token in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?|[-+]?\.\d+(?:[Ee][-+]?\d+)?", line):
        number = _to_float(token)
        if number is not None:
            values.append(number)
    return values


def _actual_ray_trace_lines(text: str) -> list[str]:
    lines = text.splitlines()
    start = 0
    end = len(lines)
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "real ray trace data" in lowered or "实际光线追迹数据" in line:
            start = index + 1
            break
    for index in range(start, len(lines)):
        lowered = lines[index].lower()
        if "paraxial" in lowered or "近轴" in lines[index]:
            end = index
            break
    return lines[start:end]


def _parse_xy(text: str) -> dict[int, tuple[float, float]]:
    points: dict[int, tuple[float, float]] = {}
    for line in _actual_ray_trace_lines(text):
        stripped = line.strip()
        if not re.match(r"^\d+\s", stripped):
            continue
        nums = _numbers_from_line(stripped)
        if len(nums) < 3:
            continue
        points[int(nums[0])] = (nums[1], nums[2])
    return points


def _field_key(field: float) -> str:
    return f"{field:g}".replace(".", "p")


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


def _read_fields(oss: Any) -> list[dict[str, Any]]:
    fields = _safe_get(oss.SystemData, "Fields")
    count = int(_safe_get(fields, "NumberOfFields", 0) or 0)
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        try:
            item = fields.GetField(index)
        except Exception:
            continue
        rows.append({"number": index, "y": _to_float(_safe_get(item, "Y"))})
    return rows


def _field_number(fields: list[dict[str, Any]], field_deg: float) -> int | None:
    candidates = []
    for row in fields:
        y = _to_float(row.get("y"))
        number = row.get("number")
        if y is not None and number is not None:
            candidates.append((abs(y - field_deg), int(number)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] < 1e-6 else None


def _trace_ray(
    oss: Any,
    field_number: int,
    field_deg: float,
    px: float,
    py: float,
    raw_path: Path,
) -> tuple[dict[int, tuple[float, float]], str | None]:
    try:
        if raw_path.exists():
            raw_path.unlink()
        SingleRayTrace(
            hx=0.0,
            hy=0.0,
            px=px,
            py=py,
            field=field_number,
            raytrace_type="DirectionCosines",
            global_coordinates=False,
        ).run(oss, text_output_file=raw_path)
    except Exception as exc:
        close_all_analysis_windows(oss)
        if raw_path.exists():
            points = _parse_xy(_read_text_file(raw_path))
            if points:
                return points, f"wrapper raised but raw text parsed: {type(exc).__name__}: {exc!r}"
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: {type(exc).__name__}: {exc!r}"
    if not raw_path.exists():
        close_all_analysis_windows(oss)
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: no raw trace file created"
    points = _parse_xy(_read_text_file(raw_path))
    if not points:
        close_all_analysis_windows(oss)
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: raw trace contained no parseable surface rows"
    close_all_analysis_windows(oss)
    return points, None


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
    asp = 0.0
    for term, coeff in surface.even_terms.items():
        if coeff is not None:
            asp += coeff * (r**term)
    return base + asp, None


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


def _min_internal_gap(
    lde: Any,
    s7: SurfaceData,
    s8: SurfaceData,
    radius_max: float,
) -> tuple[float | None, float | None, str]:
    if s7.thickness is None:
        return None, None, "S7 thickness unknown"
    min_gap = None
    min_radius = None
    invalid: list[str] = []
    for index in range(501):
        r = radius_max * index / 500.0
        sag7, warn7 = _surface_sag(lde, s7, r)
        sag8, warn8 = _surface_sag(lde, s8, r)
        if sag7 is None or sag8 is None:
            invalid.append(f"r={r:g}: S7 {warn7}; S8 {warn8}")
            continue
        gap = s7.thickness + sag8 - sag7
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_radius = r
    note = ""
    if invalid:
        note = f"{len(invalid)} invalid sag samples; first: {invalid[0]}"
    return min_gap, min_radius, note


def _write_csv(path: Path, row: dict[str, Any]) -> None:
    fields = [
        "s7_radius",
        "s7_thickness",
        "s7_glass",
        "s7_semi_diameter",
        "s7_conic",
        "s8_radius",
        "s8_thickness",
        "s8_glass",
        "s8_semi_diameter",
        "s8_conic",
        "s7_actual_max_ray_radius",
        "s8_actual_max_ray_radius",
        "actual_max_ray_radius",
        "sample_radius",
        "min_internal_edge_thickness",
        "min_internal_edge_radius",
        "clamp_safe_radius",
        "clamp_possible",
        "increase_for_edge_0p05",
        "target_s7_thickness_for_edge_0p05",
        "increase_for_edge_0p10",
        "target_s7_thickness_for_edge_0p10",
        "increase_for_edge_0p20",
        "target_s7_thickness_for_edge_0p20",
        "recommendation",
        "ray_trace_failure_count",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)


def _write_report(path: Path, lens_path: str, row: dict[str, Any], failures: list[str]) -> None:
    lines = [
        "S7->S8 Repair Diagnostic After Plan B",
        f"lens_path: {lens_path}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        "",
        "Surface data",
        f"S7 radius: {_fmt(row['s7_radius'])}",
        f"S7 thickness: {_fmt(row['s7_thickness'])}",
        f"S7 glass: {row['s7_glass']}",
        f"S7 semi-diameter: {_fmt(row['s7_semi_diameter'])}",
        f"S8 radius: {_fmt(row['s8_radius'])}",
        f"S8 semi-diameter: {_fmt(row['s8_semi_diameter'])}",
        "",
        "Ray footprint",
        f"S7 actual max ray radius: {_fmt(row['s7_actual_max_ray_radius'])} mm",
        f"S8 actual max ray radius: {_fmt(row['s8_actual_max_ray_radius'])} mm",
        f"actual max ray radius: {_fmt(row['actual_max_ray_radius'])} mm",
        f"sample radius actual+0.05: {_fmt(row['sample_radius'])} mm",
        "",
        "Internal edge thickness at sampled radius",
        f"min internal edge thickness: {_fmt(row['min_internal_edge_thickness'])} mm",
        f"min internal edge radius: {_fmt(row['min_internal_edge_radius'])} mm",
        "",
        "Clamp check",
        f"clamp safe radius: {_fmt(row['clamp_safe_radius'])} mm",
        f"clamp possible: {row['clamp_possible']}",
        f"recommendation: {row['recommendation']}",
        "",
        "Thickness repair targets",
        f"edge >= 0.05: increase S7 by {_fmt(row['increase_for_edge_0p05'])} mm -> target {_fmt(row['target_s7_thickness_for_edge_0p05'])} mm",
        f"edge >= 0.10: increase S7 by {_fmt(row['increase_for_edge_0p10'])} mm -> target {_fmt(row['target_s7_thickness_for_edge_0p10'])} mm",
        f"edge >= 0.20: increase S7 by {_fmt(row['increase_for_edge_0p20'])} mm -> target {_fmt(row['target_s7_thickness_for_edge_0p20'])} mm",
        "",
        "Trace failures",
    ]
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("none")
    if row.get("notes"):
        lines.extend(["", "Notes", str(row["notes"])])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_s7_s8_repair_after_plan_b(lens_path: str) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "s7_s8_repair_after_plan_b" / run_id
    raw_dir = out_dir / "raw_traces"
    raw_dir.mkdir(parents=True, exist_ok=True)

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
    s7 = _read_surface(lde.GetSurfaceAt(SURFACE_A))
    s8 = _read_surface(lde.GetSurfaceAt(SURFACE_B))
    fields = _read_fields(oss)
    failures: list[str] = []
    max_radius = {SURFACE_A: None, SURFACE_B: None}

    for field in FIELDS_DEG:
        field_number = _field_number(fields, field)
        if field_number is None:
            failures.append(f"field {field:g} deg not found")
            continue
        for sample_index, (px, py) in enumerate(PUPIL_SAMPLES):
            raw_path = raw_dir / f"field_{_field_key(field)}_pupil_{sample_index:02d}.txt"
            points, failure = _trace_ray(oss, field_number, field, px, py, raw_path)
            if failure:
                failures.append(failure)
            for surface_number in (SURFACE_A, SURFACE_B):
                point = points.get(surface_number)
                if point is None:
                    continue
                r = math.hypot(point[0], point[1])
                current = max_radius[surface_number]
                if current is None or r > current:
                    max_radius[surface_number] = r

    actual = None
    if max_radius[SURFACE_A] is not None and max_radius[SURFACE_B] is not None:
        actual = max(max_radius[SURFACE_A], max_radius[SURFACE_B])
    sample_radius = None if actual is None else actual + 0.05
    min_gap = min_gap_radius = None
    note = ""
    if sample_radius is not None:
        min_gap, min_gap_radius, note = _min_internal_gap(lde, s7, s8, sample_radius)

    safe_radius = sample_radius if sample_radius is not None else None
    # A clamp is useful only when actual+0.05 is still inside both current clear apertures
    # and the sampled internal edge is already non-negative at that radius.
    current_common = None
    if s7.semi_diameter is not None and s8.semi_diameter is not None:
        current_common = min(s7.semi_diameter, s8.semi_diameter)
    clamp_possible = (
        sample_radius is not None
        and current_common is not None
        and sample_radius < current_common
        and min_gap is not None
        and min_gap >= 0.0
    )

    row: dict[str, Any] = {
        "s7_radius": s7.radius,
        "s7_thickness": s7.thickness,
        "s7_glass": s7.glass,
        "s7_semi_diameter": s7.semi_diameter,
        "s7_conic": s7.conic,
        "s8_radius": s8.radius,
        "s8_thickness": s8.thickness,
        "s8_glass": s8.glass,
        "s8_semi_diameter": s8.semi_diameter,
        "s8_conic": s8.conic,
        "s7_actual_max_ray_radius": max_radius[SURFACE_A],
        "s8_actual_max_ray_radius": max_radius[SURFACE_B],
        "actual_max_ray_radius": actual,
        "sample_radius": sample_radius,
        "min_internal_edge_thickness": min_gap,
        "min_internal_edge_radius": min_gap_radius,
        "clamp_safe_radius": safe_radius,
        "clamp_possible": clamp_possible,
        "ray_trace_failure_count": len(failures),
        "notes": note,
    }
    for target in SAFETY_GAPS:
        label = f"{target:.2f}".replace(".", "p")
        increase = None if min_gap is None else max(0.0, target - min_gap)
        row[f"increase_for_edge_{label}"] = increase
        row[f"target_s7_thickness_for_edge_{label}"] = None if increase is None or s7.thickness is None else s7.thickness + increase

    if clamp_possible:
        row["recommendation"] = "clamp possible"
    else:
        target = row.get("target_s7_thickness_for_edge_0p10")
        row["recommendation"] = f"S7 thickness target value {target}" if target is not None else "must increase S7 thickness; target unknown"

    csv_path = out_dir / "s7_s8_repair_table.csv"
    report_path = out_dir / "s7_s8_repair_report.txt"
    _write_csv(csv_path, row)
    _write_report(report_path, lens_path, row, failures)

    print(f"s7_actual_max_ray_radius: {_fmt(max_radius[SURFACE_A])}", flush=True)
    print(f"s8_actual_max_ray_radius: {_fmt(max_radius[SURFACE_B])}", flush=True)
    print(f"min_internal_edge_thickness: {_fmt(min_gap)}", flush=True)
    print(f"clamp_possible: {clamp_possible}", flush=True)
    print(f"recommendation: {row['recommendation']}", flush=True)
    print(f"table: {csv_path}", flush=True)
    print(f"report: {report_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only S7->S8 repair diagnostic after Plan B.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script is read-only.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_s7_s8_repair_after_plan_b(args.lens)
