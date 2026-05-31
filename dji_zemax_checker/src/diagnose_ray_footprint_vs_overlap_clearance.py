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

OVERLAP_SAFE_RADII = {
    (2, 3): 3.97992,
    (4, 5): 2.54095,
    (7, 8): 3.35093,
    (9, 10): 2.20994,
}


@dataclass
class SurfaceInfo:
    surface_number: int
    radius: float | None
    thickness: float | None
    glass: str
    semi_diameter: float | None


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


def _field_key(field: float) -> str:
    text = f"{field:g}".replace(".", "p")
    return text


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


def _parse_surface_xy_from_trace(text: str) -> dict[int, tuple[float, float]]:
    points: dict[int, tuple[float, float]] = {}
    for line in _actual_ray_trace_lines(text):
        stripped = line.strip()
        if not re.match(r"^\d+\s", stripped):
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 3:
            continue
        surface_number = int(numbers[0])
        x = numbers[1]
        y = numbers[2]
        points[surface_number] = (x, y)
    return points


def _read_fields(oss: Any) -> list[dict[str, Any]]:
    fields = _safe_get(oss.SystemData, "Fields")
    count = int(_safe_get(fields, "NumberOfFields", 0) or 0)
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        try:
            item = fields.GetField(index)
        except Exception:
            continue
        rows.append(
            {
                "number": index,
                "x": _to_float(_safe_get(item, "X")),
                "y": _to_float(_safe_get(item, "Y")),
                "weight": _to_float(_safe_get(item, "Weight")),
            }
        )
    return rows


def _field_number_for_angle(fields: list[dict[str, Any]], field_deg: float) -> int | None:
    candidates: list[tuple[float, int]] = []
    for row in fields:
        y = _to_float(row.get("y"))
        number = row.get("number")
        if y is None or number is None:
            continue
        candidates.append((abs(y - field_deg), int(number)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] < 1e-6 else None


def _read_surfaces(oss: Any) -> list[SurfaceInfo]:
    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    surfaces: list[SurfaceInfo] = []
    for index in range(count):
        surface = lde.GetSurfaceAt(index)
        surfaces.append(
            SurfaceInfo(
                surface_number=int(_safe_get(surface, "SurfaceNumber", index)),
                radius=_to_float(_safe_get(surface, "Radius")),
                thickness=_to_float(_safe_get(surface, "Thickness")),
                glass=str(_safe_get(surface, "Material", "") or ""),
                semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
            )
        )
    return surfaces


def _trace_single_ray(
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
            text = _read_text_file(raw_path)
            points = _parse_surface_xy_from_trace(text)
            if points:
                return points, f"wrapper raised but raw text parsed: {type(exc).__name__}: {exc!r}"
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: {type(exc).__name__}: {exc!r}"

    if not raw_path.exists():
        close_all_analysis_windows(oss)
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: no raw trace file was created"

    text = _read_text_file(raw_path)
    points = _parse_surface_xy_from_trace(text)
    if not points:
        close_all_analysis_windows(oss)
        return {}, f"field={field_deg:g}, Px={px:g}, Py={py:g}: raw trace contained no parseable surface rows"
    close_all_analysis_windows(oss)
    return points, None


def _classify_margin(margin: float | None) -> str:
    if margin is None:
        return "UNKNOWN"
    if margin > 0.10:
        return "PASS_clear_aperture_clamp_possible"
    if margin >= 0.0:
        return "BORDERLINE"
    return "FAIL_geometry_must_change"


def _write_surface_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "surface_number",
        "radius",
        "thickness",
        "glass",
        "current_semi_diameter",
        "max_ray_radius_field_0",
        "max_ray_radius_field_21",
        "max_ray_radius_field_35",
        "max_ray_radius_field_49",
        "max_ray_radius_field_63",
        "max_ray_radius_field_70",
        "overall_max_ray_radius",
        "ray_trace_failure_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_pair_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "pair_name",
        "surface_a",
        "surface_b",
        "safe_common_radius_for_gap_ge_0",
        "current_common_semi_diameter",
        "surface_a_overall_ray_radius",
        "surface_b_overall_ray_radius",
        "actual_required_common_ray_radius",
        "clearance_margin",
        "conclusion",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    lens_path: str,
    field_failures: list[str],
    pair_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "Ray Footprint vs Overlap Clearance Diagnostic",
        f"lens_path: {lens_path}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        f"fields_deg: {', '.join(f'{field:g}' for field in FIELDS_DEG)}",
        f"pupil_sample_count: {len(PUPIL_SAMPLES)}",
        "",
        "Overlap pair clearance conclusions",
    ]
    for row in pair_rows:
        lines.extend(
            [
                "",
                f"{row['pair_name']}: {row['conclusion']}",
                f"safe_common_radius_for_gap_ge_0: {_fmt(row['safe_common_radius_for_gap_ge_0'])} mm",
                f"current_common_semi_diameter: {_fmt(row['current_common_semi_diameter'])} mm",
                f"actual_required_common_ray_radius: {_fmt(row['actual_required_common_ray_radius'])} mm",
                f"clearance_margin: {_fmt(row['clearance_margin'])} mm",
            ]
        )
        if row["conclusion"] == "FAIL_geometry_must_change":
            lines.append(
                "interpretation: actual ray footprint exceeds the safe common radius; do not rely on clear aperture clamping alone."
            )
        elif row["conclusion"] == "BORDERLINE":
            lines.append(
                "interpretation: aperture clamping may be possible but margin is <=0.10 mm; verify with layout and vignetting."
            )
        elif row["conclusion"] == "PASS_clear_aperture_clamp_possible":
            lines.append(
                "interpretation: current sampled rays fit inside the safe common radius with >0.10 mm margin."
            )

    failed_pairs = [row for row in pair_rows if row["conclusion"] == "FAIL_geometry_must_change"]
    lines.extend(["", "Overall judgment"])
    if failed_pairs:
        lines.append(
            "At least one overlap pair has ray footprint larger than the safe radius. Those pairs require curvature, center thickness, spacing, or structural changes."
        )
    else:
        lines.append(
            "No sampled overlap pair requires a larger radius than the safe clearance radius; clear aperture clamp remains plausible for the sampled ray set."
        )

    lines.extend(["", "Trace failures"])
    if field_failures:
        lines.extend(f"- {failure}" for failure in field_failures)
    else:
        lines.append("none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_ray_footprint_vs_overlap_clearance(lens_path: str) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "ray_footprint_vs_overlap" / run_id
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

    surfaces = _read_surfaces(oss)
    fields = _read_fields(oss)
    surface_by_number = {surface.surface_number: surface for surface in surfaces}

    max_by_surface_field: dict[int, dict[float, float | None]] = {
        surface.surface_number: {field: None for field in FIELDS_DEG} for surface in surfaces
    }
    failure_count_by_surface: dict[int, int] = {surface.surface_number: 0 for surface in surfaces}
    failures: list[str] = []

    for field_deg in FIELDS_DEG:
        field_number = _field_number_for_angle(fields, field_deg)
        if field_number is None:
            message = f"field {field_deg:g} deg not found in current lens field table"
            failures.append(message)
            for surface in surfaces:
                failure_count_by_surface[surface.surface_number] += len(PUPIL_SAMPLES)
            continue

        for sample_index, (px, py) in enumerate(PUPIL_SAMPLES):
            raw_path = raw_dir / f"field_{_field_key(field_deg)}_pupil_{sample_index:02d}_px_{px:+.3f}_py_{py:+.3f}.txt"
            points, failure = _trace_single_ray(oss, field_number, field_deg, px, py, raw_path)
            if failure:
                failures.append(failure)
            if not points:
                for surface in surfaces:
                    failure_count_by_surface[surface.surface_number] += 1
                continue

            for surface in surfaces:
                point = points.get(surface.surface_number)
                if point is None:
                    failure_count_by_surface[surface.surface_number] += 1
                    continue
                x, y = point
                radius = math.hypot(x, y)
                current = max_by_surface_field[surface.surface_number][field_deg]
                if current is None or radius > current:
                    max_by_surface_field[surface.surface_number][field_deg] = radius

    surface_rows: list[dict[str, Any]] = []
    overall_by_surface: dict[int, float | None] = {}
    for surface in surfaces:
        per_field = max_by_surface_field[surface.surface_number]
        finite_values = [value for value in per_field.values() if value is not None]
        overall = max(finite_values) if finite_values else None
        overall_by_surface[surface.surface_number] = overall
        row = {
            "surface_number": surface.surface_number,
            "radius": surface.radius,
            "thickness": surface.thickness,
            "glass": surface.glass,
            "current_semi_diameter": surface.semi_diameter,
            "overall_max_ray_radius": overall,
            "ray_trace_failure_count": failure_count_by_surface[surface.surface_number],
        }
        for field in FIELDS_DEG:
            row[f"max_ray_radius_field_{_field_key(field)}"] = per_field[field]
        surface_rows.append(row)

    pair_rows: list[dict[str, Any]] = []
    for (surface_a, surface_b), safe_radius in OVERLAP_SAFE_RADII.items():
        a = surface_by_number.get(surface_a)
        b = surface_by_number.get(surface_b)
        a_ray = overall_by_surface.get(surface_a)
        b_ray = overall_by_surface.get(surface_b)
        required = None
        if a_ray is not None and b_ray is not None:
            required = max(a_ray, b_ray)
        current_common = None
        if a is not None and b is not None and a.semi_diameter is not None and b.semi_diameter is not None:
            current_common = min(a.semi_diameter, b.semi_diameter)
        margin = None if required is None else safe_radius - required
        pair_rows.append(
            {
                "pair_name": f"S{surface_a}->S{surface_b}",
                "surface_a": surface_a,
                "surface_b": surface_b,
                "safe_common_radius_for_gap_ge_0": safe_radius,
                "current_common_semi_diameter": current_common,
                "surface_a_overall_ray_radius": a_ray,
                "surface_b_overall_ray_radius": b_ray,
                "actual_required_common_ray_radius": required,
                "clearance_margin": margin,
                "conclusion": _classify_margin(margin),
            }
        )

    surface_csv = out_dir / "ray_footprint_surface_summary.csv"
    pair_csv = out_dir / "ray_footprint_overlap_pairs.csv"
    report_path = out_dir / "ray_footprint_vs_overlap_report.txt"
    _write_surface_summary(surface_csv, surface_rows)
    _write_pair_summary(pair_csv, pair_rows)
    _write_report(report_path, lens_path, failures, pair_rows)

    print(f"surface_summary_csv: {surface_csv}", flush=True)
    print(f"overlap_pairs_csv: {pair_csv}", flush=True)
    print(f"report: {report_path}", flush=True)
    for row in pair_rows:
        print(
            f"{row['pair_name']}: required={_fmt(row['actual_required_common_ray_radius'])}, "
            f"safe={_fmt(row['safe_common_radius_for_gap_ge_0'])}, "
            f"margin={_fmt(row['clearance_margin'])}, conclusion={row['conclusion']}",
            flush=True,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only ray footprint vs overlap safe-clearance diagnostic."
    )
    parser.add_argument(
        "--lens",
        required=True,
        help="Path to the lens file to analyze. The script does not modify or save the lens.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_ray_footprint_vs_overlap_clearance(args.lens)
