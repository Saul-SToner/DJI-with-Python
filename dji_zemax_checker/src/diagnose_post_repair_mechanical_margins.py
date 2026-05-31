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
PAIRS = [(2, 3), (4, 5), (7, 8), (9, 10)]
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
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
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 3:
            continue
        points[int(numbers[0])] = (numbers[1], numbers[2])
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


def _min_gap(lde: Any, a: SurfaceData, b: SurfaceData, radius_max: float | None) -> tuple[float | None, float | None, str]:
    if radius_max is None:
        return None, None, "radius_max unknown"
    if a.thickness is None:
        return None, None, "surface A thickness unknown"
    min_gap = None
    min_radius = None
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


def _level(margin: float | None) -> str:
    if margin is None:
        return "UNKNOWN"
    if margin < 0.05:
        return "DANGER"
    if margin <= 0.10:
        return "TIGHT"
    if margin <= 0.20:
        return "ACCEPTABLE"
    return "GOOD"


def _classification(pair: tuple[int, int]) -> str:
    if pair in ((2, 3), (4, 5)):
        return "air_gap"
    return "internal_edge_thickness"


def _note(pair: tuple[int, int], current_gap: float | None, footprint_gap: float | None) -> str:
    notes: list[str] = []
    if pair == (2, 3) and (current_gap is None or current_gap < 0.10):
        notes.append("S2/S3 air gap is tight; lock S2/S3 clear semi-diameter if using clamp repair.")
    if pair == (7, 8):
        notes.append("S7/S8 depends on clear semi-diameter clamp; lock S7/S8 semi-diameter during later optimization.")
    if pair in ((7, 8), (9, 10)) and (footprint_gap is None or footprint_gap < 0.10):
        notes.append("internal edge thickness is not robust; avoid reducing center thickness or increasing clear aperture.")
    if pair == (4, 5):
        notes.append("S4 thickness and S4/S5 clear aperture should remain locked after repair.")
    return " ".join(notes)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "pair",
        "classification",
        "surface_a",
        "surface_b",
        "current_common_semi_diameter",
        "max_ray_radius_field_0",
        "max_ray_radius_field_21",
        "max_ray_radius_field_35",
        "max_ray_radius_field_49",
        "max_ray_radius_field_63",
        "max_ray_radius_field_70",
        "overall_actual_ray_radius",
        "footprint_plus_0p05_radius",
        "min_gap_at_current_clear_sd",
        "min_gap_radius_at_current_clear_sd",
        "level_at_current_clear_sd",
        "min_gap_at_footprint_plus_0p05",
        "min_gap_radius_at_footprint_plus_0p05",
        "level_at_footprint_plus_0p05",
        "lock_recommendation",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, lens_path: str, rows: list[dict[str, Any]], failures: list[str]) -> None:
    lines = [
        "Post Repair Mechanical Margins Diagnostic",
        f"lens_path: {lens_path}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        "",
        "Levels: DANGER <0.05 mm, TIGHT 0.05-0.10 mm, ACCEPTABLE 0.10-0.20 mm, GOOD >0.20 mm",
        "",
        "Pair summary",
    ]
    for row in rows:
        lines.extend(
            [
                "",
                f"{row['pair']}:",
                f"classification: {row['classification']}",
                f"current_common_semi_diameter: {_fmt(row['current_common_semi_diameter'])} mm",
                f"overall_actual_ray_radius: {_fmt(row['overall_actual_ray_radius'])} mm",
                f"min_gap_at_current_clear_sd: {_fmt(row['min_gap_at_current_clear_sd'])} mm ({row['level_at_current_clear_sd']})",
                f"min_gap_at_footprint_plus_0p05: {_fmt(row['min_gap_at_footprint_plus_0p05'])} mm ({row['level_at_footprint_plus_0p05']})",
                f"lock_recommendation: {row['lock_recommendation']}",
                f"notes: {row['notes']}",
            ]
        )

    danger = [row["pair"] for row in rows if "DANGER" in (row["level_at_footprint_plus_0p05"], row["level_at_current_clear_sd"])]
    lines.extend(["", "Overall judgment"])
    if danger:
        lines.append("DANGER pairs remain: " + ", ".join(danger))
    else:
        lines.append("No checked pair is DANGER by the current thresholds.")

    lines.extend(["", "Trace failures"])
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_post_repair_mechanical_margins(lens_path: str) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "post_repair_mechanical_margins" / run_id
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
    surfaces = {index: _read_surface(lde.GetSurfaceAt(index)) for index in range(int(lde.NumberOfSurfaces))}
    fields = _read_fields(oss)
    failures: list[str] = []
    max_radius_by_pair_field: dict[tuple[int, int], dict[float, float | None]] = {
        pair: {field: None for field in FIELDS_DEG} for pair in PAIRS
    }

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
            for pair in PAIRS:
                radii: list[float] = []
                for surface_number in pair:
                    point = points.get(surface_number)
                    if point is not None:
                        radii.append(math.hypot(point[0], point[1]))
                if not radii:
                    continue
                value = max(radii)
                current = max_radius_by_pair_field[pair][field]
                if current is None or value > current:
                    max_radius_by_pair_field[pair][field] = value

    rows: list[dict[str, Any]] = []
    for pair in PAIRS:
        a = surfaces[pair[0]]
        b = surfaces[pair[1]]
        current_common = None
        if a.semi_diameter is not None and b.semi_diameter is not None:
            current_common = min(a.semi_diameter, b.semi_diameter)
        per_field = max_radius_by_pair_field[pair]
        finite = [value for value in per_field.values() if value is not None]
        overall = max(finite) if finite else None
        footprint_plus = None if overall is None else overall + 0.05
        gap_current, radius_current, note_current = _min_gap(lde, a, b, current_common)
        gap_footprint, radius_footprint, note_footprint = _min_gap(lde, a, b, footprint_plus)
        lock = []
        if pair in ((2, 3), (7, 8)):
            lock.append("lock clear semi-diameter")
        if pair in ((4, 5), (7, 8), (9, 10)):
            lock.append(f"lock S{pair[0]} thickness")
        row = {
            "pair": f"S{pair[0]}->S{pair[1]}",
            "classification": _classification(pair),
            "surface_a": pair[0],
            "surface_b": pair[1],
            "current_common_semi_diameter": current_common,
            "overall_actual_ray_radius": overall,
            "footprint_plus_0p05_radius": footprint_plus,
            "min_gap_at_current_clear_sd": gap_current,
            "min_gap_radius_at_current_clear_sd": radius_current,
            "level_at_current_clear_sd": _level(gap_current),
            "min_gap_at_footprint_plus_0p05": gap_footprint,
            "min_gap_radius_at_footprint_plus_0p05": radius_footprint,
            "level_at_footprint_plus_0p05": _level(gap_footprint),
            "lock_recommendation": "; ".join(lock),
            "notes": _note(pair, gap_current, gap_footprint),
        }
        for field in FIELDS_DEG:
            row[f"max_ray_radius_field_{_field_key(field)}"] = per_field[field]
        notes = [item for item in (note_current, note_footprint) if item]
        if notes:
            row["notes"] = (row["notes"] + " " + " ".join(notes)).strip()
        rows.append(row)

    csv_path = out_dir / "post_repair_mechanical_margins.csv"
    report_path = out_dir / "post_repair_mechanical_margins_report.txt"
    _write_csv(csv_path, rows)
    _write_report(report_path, lens_path, rows, failures)
    close_all_analysis_windows(oss)

    print(f"csv: {csv_path}", flush=True)
    print(f"report: {report_path}", flush=True)
    for row in rows:
        print(
            f"{row['pair']}: current={_fmt(row['min_gap_at_current_clear_sd'])} "
            f"({row['level_at_current_clear_sd']}), footprint+0.05={_fmt(row['min_gap_at_footprint_plus_0p05'])} "
            f"({row['level_at_footprint_plus_0p05']})",
            flush=True,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only post-repair mechanical margin diagnostic.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script is read-only.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_post_repair_mechanical_margins(args.lens)
