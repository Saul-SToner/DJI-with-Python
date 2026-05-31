from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from zospy.analyses.raysandspots.single_ray_trace import SingleRayTrace

from scan_radius import _safe_label
from zosapi_cleanup import close_all_analysis_windows


FIELDS_DEG = (0.0, 21.0, 35.0, 49.0, 63.0, 70.0)
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
)
DEFAULT_IMAGE_DISTANCES = (0.2, 0.3, 0.5, 0.696, 0.7, 1.0, 1.5, 2.0, 2.3, 2.5, 3.0)


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, digits: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "null" if value is None else str(value)
    return f"{number:.{digits}g}"


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _run_id(label: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"


def _unique_run_dir(project_root: Path, label: str) -> tuple[str, Path]:
    root = project_root / "results" / "focus_raytrace_spot_scan"
    base = _run_id(label)
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


def _safe_distance_label(value: float) -> str:
    text = f"{value:g}".replace("-", "m").replace("+", "p").replace(".", "p")
    return text or "0"


def _field_key(field: float) -> str:
    return f"{field:g}".replace(".", "p")


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "mbcs"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(errors="replace")


def _numbers_from_line(line: str) -> list[float]:
    values: list[float] = []
    pattern = r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?|[-+]?\.\d+(?:[Ee][-+]?\d+)?"
    for token in re.findall(pattern, line):
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


def _parse_trace_rows(text: str) -> dict[int, dict[str, float]]:
    rows: dict[int, dict[str, float]] = {}
    for line in _actual_ray_trace_lines(text):
        stripped = line.strip()
        if not re.match(r"^\d+\s", stripped):
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 3:
            continue
        surface = int(numbers[0])
        row = {"x": numbers[1], "y": numbers[2]}
        if len(numbers) >= 7:
            # Direction-cosine text normally has: surface, X, Y, Z, L, M, N.
            row.update({"l": numbers[4], "m": numbers[5], "n": numbers[6]})
        elif len(numbers) >= 6:
            row.update({"l": numbers[3], "m": numbers[4], "n": numbers[5]})
        rows[surface] = row
    return rows


def _field_rows(oss: Any) -> list[dict[str, Any]]:
    fields = _safe_get(_safe_get(oss, "SystemData"), "Fields")
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


def _field_number(fields: list[dict[str, Any]], field_deg: float) -> int | None:
    candidates: list[tuple[float, int]] = []
    for row in fields:
        y = _to_float(row.get("y"))
        number = row.get("number")
        if y is not None and number is not None:
            candidates.append((abs(y - field_deg), int(number)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] < 1e-6 else None


def _finite_thickness(value: Any) -> float | None:
    number = _to_float(value)
    if number is None or not math.isfinite(number):
        return None
    return number


def _ttl_from_lde(oss: Any) -> float | None:
    """Prescription TTL: sum finite thicknesses from S1 through image-1, excluding OBJ."""
    lde = _safe_get(oss, "LDE")
    try:
        count = int(lde.NumberOfSurfaces)
    except Exception:
        return None
    total = 0.0
    found = False
    for surface_number in range(1, count - 1):
        try:
            thickness = _finite_thickness(lde.GetSurfaceAt(surface_number).Thickness)
        except Exception:
            thickness = None
        if thickness is None:
            continue
        total += thickness
        found = True
    return total if found else None


def _lens_summary(oss: Any) -> dict[str, Any]:
    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    image_surface = count - 1
    last_surface = image_surface - 1
    image_distance = _to_float(lde.GetSurfaceAt(last_surface).Thickness)
    aperture = _safe_get(_safe_get(oss, "SystemData"), "Aperture")
    efl = None
    for obj in (_safe_get(oss, "SystemData"), lde, oss):
        if obj is None:
            continue
        for name in ("EffectiveFocalLength", "EffectiveFocalLengthAir", "EFL", "ParaxialEffectiveFocalLength"):
            efl = _to_float(_safe_get(obj, name))
            if efl is not None:
                break
        if efl is not None:
            break
    return {
        "number_of_surfaces": count,
        "image_surface": image_surface,
        "last_surface_before_image": last_surface,
        "original_image_distance": image_distance,
        "ttl": _ttl_from_lde(oss),
        "bfl": image_distance,
        "efl": efl,
        "f_number": _to_float(_safe_get(aperture, "ApertureValue")),
    }


def _trace_ray(
    oss: Any,
    *,
    field_number: int,
    field_deg: float,
    px: float,
    py: float,
    image_surface: int,
    raw_path: Path,
) -> tuple[dict[str, float] | None, str | None]:
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
            rows = _parse_trace_rows(_read_text_file(raw_path))
            if image_surface in rows:
                return rows[image_surface], f"wrapper raised but raw text parsed: {type(exc).__name__}: {exc!r}"
        return None, f"Px={px:g}, Py={py:g}: {type(exc).__name__}: {exc!r}"

    if not raw_path.exists():
        close_all_analysis_windows(oss)
        return None, f"Px={px:g}, Py={py:g}: no raw trace file was created"

    rows = _parse_trace_rows(_read_text_file(raw_path))
    if image_surface not in rows:
        close_all_analysis_windows(oss)
        return None, f"Px={px:g}, Py={py:g}: no parseable image-surface row"
    close_all_analysis_windows(oss)
    return rows[image_surface], None


def _rms_spot(points: list[tuple[float, float]]) -> tuple[float | None, float | None, float | None, float | None]:
    if not points:
        return None, None, None, None
    centroid_x = sum(x for x, _ in points) / len(points)
    centroid_y = sum(y for _, y in points) / len(points)
    squared = [(x - centroid_x) ** 2 + (y - centroid_y) ** 2 for x, y in points]
    rms = math.sqrt(sum(squared) / len(squared))
    max_radius = max(math.hypot(x, y) for x, y in points)
    return centroid_x, centroid_y, rms, max_radius


def _chief_ray_angle(row: dict[str, float] | None) -> float | None:
    if row is None:
        return None
    l = _to_float(row.get("l"))
    m = _to_float(row.get("m"))
    n = _to_float(row.get("n"))
    if l is None or m is None or n is None or abs(n) < 1e-12:
        return None
    return math.degrees(math.atan2(math.sqrt(l * l + m * m), abs(n)))


def _scan_field(
    oss: Any,
    raw_dir: Path,
    *,
    image_distance: float,
    field_deg: float,
    field_number: int | None,
    image_surface: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "image_distance": image_distance,
        "field_deg": field_deg,
        "field_number": field_number,
        "ray_trace_success_count": 0,
        "ray_trace_failure_count": 0,
        "failed_pupil_coordinates": "",
        "centroid_x": None,
        "centroid_y": None,
        "geometric_rms_spot_radius": None,
        "max_ray_radius_on_image": None,
        "chief_ray_x": None,
        "chief_ray_y": None,
        "chief_ray_angle_deg": None,
        "status": "failed",
        "failure_reason": None,
    }
    if field_number is None:
        row["failure_reason"] = "Requested field is not present in current lens field table."
        row["ray_trace_failure_count"] = len(PUPIL_SAMPLES)
        row["failed_pupil_coordinates"] = "; ".join(f"({px:g},{py:g})" for px, py in PUPIL_SAMPLES)
        return row

    hits: list[tuple[float, float]] = []
    failures: list[str] = []
    warning_notes: list[str] = []
    chief_row: dict[str, float] | None = None
    for px, py in PUPIL_SAMPLES:
        raw_path = raw_dir / (
            f"ray_d{_safe_distance_label(image_distance)}_f{_field_key(field_deg)}_"
            f"px{_safe_distance_label(px)}_py{_safe_distance_label(py)}.txt"
        )
        trace_row, failure = _trace_ray(
            oss,
            field_number=field_number,
            field_deg=field_deg,
            px=px,
            py=py,
            image_surface=image_surface,
            raw_path=raw_path,
        )
        if trace_row is None:
            failures.append(f"({px:g},{py:g}) {failure}")
            continue
        x = _to_float(trace_row.get("x"))
        y = _to_float(trace_row.get("y"))
        if x is None or y is None:
            failures.append(f"({px:g},{py:g}) no finite image x/y")
            continue
        hits.append((x, y))
        if failure:
            warning_notes.append(f"({px:g},{py:g}) {failure}")
        if abs(px) < 1e-12 and abs(py) < 1e-12:
            chief_row = trace_row
            row["chief_ray_x"] = x
            row["chief_ray_y"] = y

    centroid_x, centroid_y, rms, max_radius = _rms_spot(hits)
    row.update(
        {
            "ray_trace_success_count": len(hits),
            "ray_trace_failure_count": len(failures),
            "failed_pupil_coordinates": "; ".join(failures),
            "centroid_x": centroid_x,
            "centroid_y": centroid_y,
            "geometric_rms_spot_radius": rms,
            "max_ray_radius_on_image": max_radius,
            "chief_ray_angle_deg": _chief_ray_angle(chief_row),
        }
    )
    if not hits:
        row["status"] = "failed"
        row["failure_reason"] = "All sampled rays failed."
    elif failures:
        row["status"] = "partial"
        row["failure_reason"] = "Some sampled rays failed."
    else:
        row["status"] = "success"
    if warning_notes:
        extra = " | ".join(warning_notes)
        row["failure_reason"] = f"{row['failure_reason']}; {extra}" if row["failure_reason"] else extra
    return row


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "image_distance",
        "estimated_TTL",
        "BFL",
        "field_deg",
        "field_number",
        "ray_trace_success_count",
        "ray_trace_failure_count",
        "failed_pupil_coordinates",
        "centroid_x",
        "centroid_y",
        "geometric_rms_spot_radius",
        "max_ray_radius_on_image",
        "chief_ray_x",
        "chief_ray_y",
        "chief_ray_angle_deg",
        "status",
        "failure_reason",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _distance_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        distance = _to_float(row.get("image_distance"))
        if distance is not None:
            grouped.setdefault(distance, []).append(row)
    summary: list[dict[str, Any]] = []
    for distance, group in sorted(grouped.items()):
        finite_rms = [_to_float(row.get("geometric_rms_spot_radius")) for row in group]
        finite_rms = [value for value in finite_rms if value is not None]
        center_rows = [row for row in group if _to_float(row.get("field_deg")) == 0.0]
        center_rms = _to_float(center_rows[0].get("geometric_rms_spot_radius")) if center_rows else None
        low_mid_values = [
            _to_float(row.get("geometric_rms_spot_radius"))
            for row in group
            if _to_float(row.get("field_deg")) in {0.0, 21.0, 35.0, 49.0}
        ]
        low_mid_values = [value for value in low_mid_values if value is not None]
        summary.append(
            {
                "image_distance": distance,
                "center_rms": center_rms,
                "mean_rms_all_successful_fields": sum(finite_rms) / len(finite_rms) if finite_rms else None,
                "mean_rms_0_21_35_49": sum(low_mid_values) / len(low_mid_values) if low_mid_values else None,
                "success_fields": sum(1 for row in group if row.get("status") == "success"),
                "partial_fields": sum(1 for row in group if row.get("status") == "partial"),
                "failed_fields": sum(1 for row in group if row.get("status") == "failed"),
                "estimated_TTL": group[0].get("estimated_TTL"),
                "BFL": group[0].get("BFL"),
            }
        )
    return summary


def _best_by(summary: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [row for row in summary if _to_float(row.get(key)) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda row: _to_float(row.get(key)) or float("inf"))


def _line_for_best(label: str, row: dict[str, Any] | None, key: str) -> str:
    if row is None:
        return f"{label}: none"
    ttl = _to_float(row.get("estimated_TTL"))
    bfl = _to_float(row.get("BFL"))
    return (
        f"{label}: image_distance={_fmt(row.get('image_distance'))}, "
        f"{key}={_fmt(row.get(key))}, TTL={_fmt(ttl)}, BFL={_fmt(bfl)}, "
        f"TTL<18={str(ttl is not None and ttl < 18).lower()}, "
        f"BFL>2.3={str(bfl is not None and bfl > 2.3).lower()}"
    )


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    base_summary: dict[str, Any],
    field_table: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    restored: bool,
) -> None:
    distance_rows = _distance_summary(rows)
    center_best = _best_by(distance_rows, "center_rms")
    low_mid_best = _best_by(distance_rows, "mean_rms_0_21_35_49")
    all_best = _best_by(distance_rows, "mean_rms_all_successful_fields")
    total_failed_rays = sum(int(row.get("ray_trace_failure_count") or 0) for row in rows)
    failed_field_rows = [row for row in rows if row.get("status") == "failed"]
    partial_field_rows = [row for row in rows if row.get("status") == "partial"]
    bfl_23_row = min(distance_rows, key=lambda row: abs((_to_float(row.get("BFL")) or 0) - 2.3), default=None)

    lines = [
        "Image Distance Ray Trace / Spot Diagnostic After Geometry Repair",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        f"original_image_distance_restored: {str(restored).lower()}",
        "",
        "[base_system]",
        f"EFL: {_fmt(base_summary.get('efl'))}",
        f"F_number: {_fmt(base_summary.get('f_number'))}",
        f"TTL: {_fmt(base_summary.get('ttl'))}",
        f"BFL: {_fmt(base_summary.get('bfl'))}",
        f"image_surface: {_fmt(base_summary.get('image_surface'))}",
        f"last_surface_before_image: {_fmt(base_summary.get('last_surface_before_image'))}",
        f"original_image_distance: {_fmt(base_summary.get('original_image_distance'))}",
        "field_table: "
        + (
            ", ".join(f"#{row.get('number')}={_fmt(row.get('y'))}deg" for row in field_table)
            if field_table
            else "unknown"
        ),
        "",
        "[best_focus_by_spot]",
        _line_for_best("center_field_best", center_best, "center_rms"),
        _line_for_best("0_21_35_49_combined_best", low_mid_best, "mean_rms_0_21_35_49"),
        _line_for_best("all_successful_fields_best", all_best, "mean_rms_all_successful_fields"),
        "",
        "[bfl_ttl_check]",
    ]
    if bfl_23_row is not None:
        ttl = _to_float(bfl_23_row.get("estimated_TTL"))
        lines.append(
            f"nearest_BFL_2p3_point: image_distance={_fmt(bfl_23_row.get('image_distance'))}, "
            f"TTL={_fmt(ttl)}, TTL<18={str(ttl is not None and ttl < 18).lower()}"
        )
    else:
        lines.append("nearest_BFL_2p3_point: none")

    lines.extend(
        [
            "",
            "[ray_trace_failure_diagnosis]",
            f"total_failed_rays: {total_failed_rays}",
            f"failed_field_rows: {len(failed_field_rows)}",
            f"partial_field_rows: {len(partial_field_rows)}",
        ]
    )
    if total_failed_rays > 0:
        lines.append(
            "FFT_MTF_failure_possible_cause: ray trace failures exist in the sampled fields/pupils, "
            "so FFT MTF failures may be caused by ray tracing, vignetting, or field setup problems."
        )
    else:
        lines.append(
            "FFT_MTF_failure_possible_cause: sampled ray trace did not fail; FFT MTF failure is more likely analysis/export-specific or due to denser pupil sampling."
        )

    lines.extend(["", "[distance_summary]"])
    for row in distance_rows:
        lines.append(
            "  "
            f"d={_fmt(row.get('image_distance'))}: "
            f"center_rms={_fmt(row.get('center_rms'))}, "
            f"mean_0_21_35_49={_fmt(row.get('mean_rms_0_21_35_49'))}, "
            f"mean_all={_fmt(row.get('mean_rms_all_successful_fields'))}, "
            f"success/partial/failed={row.get('success_fields')}/{row.get('partial_fields')}/{row.get('failed_fields')}, "
            f"TTL={_fmt(row.get('estimated_TTL'))}, BFL={_fmt(row.get('BFL'))}"
        )

    lines.extend(["", "[interpretation]"])
    if low_mid_best is None:
        lines.append("No valid low/mid-field spot result was generated; current focus state cannot be diagnosed.")
    else:
        original = _to_float(base_summary.get("original_image_distance"))
        best_distance = _to_float(low_mid_best.get("image_distance"))
        if original is not None and best_distance is not None:
            delta = best_distance - original
            if abs(delta) <= 0.05:
                lines.append("The low/mid-field best spot is close to the current image distance; pure defocus is unlikely to be the only issue.")
            else:
                lines.append(f"The low/mid-field best spot shifts image distance by {delta:.6g} mm; the current structure may be focus-position limited.")
        if bfl_23_row is not None:
            ttl = _to_float(bfl_23_row.get("estimated_TTL"))
            if ttl is not None and ttl < 18:
                lines.append("BFL near 2.3 mm is geometrically compatible with TTL < 18 in this temporary focus scan.")
            elif ttl is not None:
                lines.append("BFL near 2.3 mm would exceed TTL < 18 in this temporary focus scan.")
        if total_failed_rays == 0 and low_mid_best is not None:
            lines.append("If spot sizes remain large at all image distances, the rear group likely needs power redistribution rather than focus-only repair.")

    lines.extend(
        [
            "",
            "[files]",
            f"focus_raytrace_spot_summary: {path.parent / 'focus_raytrace_spot_summary.csv'}",
            f"focus_raytrace_spot_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _distances(current: float | None) -> list[float]:
    values = set(DEFAULT_IMAGE_DISTANCES)
    if current is not None:
        values.add(round(current, 10))
    return sorted(values)


def scan_focus_raytrace(project_root: Path, lens: Path, label: str) -> Path:
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id, run_dir = _unique_run_dir(project_root, label)
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = run_dir / "raw_single_ray_traces"
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

    print("Loading lens for temporary in-memory scan...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    base_summary = _lens_summary(oss)
    original_distance = _to_float(base_summary.get("original_image_distance"))
    last_surface = base_summary.get("last_surface_before_image")
    image_surface = base_summary.get("image_surface")
    if original_distance is None or not isinstance(last_surface, int) or not isinstance(image_surface, int):
        raise RuntimeError("Could not identify image distance / image surface.")

    field_table = _field_rows(oss)
    field_numbers = {field: _field_number(field_table, field) for field in FIELDS_DEG}
    target_surface = lde.GetSurfaceAt(last_surface)
    rows: list[dict[str, Any]] = []
    restored = False

    try:
        for distance in _distances(original_distance):
            print(f"Scanning image_distance={distance:g} mm", flush=True)
            target_surface.Thickness = distance
            try:
                oss.update_status()
            except Exception:
                pass

            estimated_ttl = (
                base_summary["ttl"] + (distance - original_distance)
                if _to_float(base_summary.get("ttl")) is not None
                else None
            )
            for field in FIELDS_DEG:
                row = _scan_field(
                    oss,
                    raw_dir,
                    image_distance=distance,
                    field_deg=field,
                    field_number=field_numbers[field],
                    image_surface=image_surface,
                )
                row["estimated_TTL"] = estimated_ttl
                row["BFL"] = distance
                rows.append(row)
    finally:
        try:
            target_surface.Thickness = original_distance
            try:
                oss.update_status()
            except Exception:
                pass
            restored = _to_float(target_surface.Thickness) == original_distance
        except Exception:
            restored = False
        close_all_analysis_windows(oss)

    metadata = {
        "run_id": run_id,
        "lens": str(lens),
        "output_folder": str(run_dir),
        "read_only": True,
        "saved_lens": False,
        "optimized": False,
        "allowed_temporary_change": "image surface previous thickness only",
        "original_image_distance": original_distance,
        "scan_distances": _distances(original_distance),
        "fields": list(FIELDS_DEG),
        "pupil_samples": list(PUPIL_SAMPLES),
        "base_summary": base_summary,
        "field_table": field_table,
        "original_image_distance_restored": restored,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(run_dir / "focus_raytrace_spot_summary.csv", rows)
    _write_report(
        run_dir / "focus_raytrace_spot_report.txt",
        lens=lens,
        run_id=run_id,
        base_summary=base_summary,
        field_table=field_table,
        rows=rows,
        restored=restored,
    )

    print(f"run_id: {run_id}", flush=True)
    print(f"output_folder: {run_dir}", flush=True)
    print(f"focus_raytrace_spot_summary: {run_dir / 'focus_raytrace_spot_summary.csv'}", flush=True)
    print(f"focus_raytrace_spot_report: {run_dir / 'focus_raytrace_spot_report.txt'}", flush=True)
    print(f"original_image_distance_restored: {str(restored).lower()}", flush=True)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Temporarily scan image distance and diagnose focus using single-ray trace spot statistics."
    )
    parser.add_argument("--lens", required=True, type=Path, help="Lens path. The script does not save or modify the file.")
    parser.add_argument("--label", default="focus_raytrace_spot_after_geometry_repair", help="Label used in output run_id.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    scan_focus_raytrace(project_root, args.lens, args.label)


if __name__ == "__main__":
    main()
