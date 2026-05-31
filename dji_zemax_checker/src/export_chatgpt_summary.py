from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from export_system_summary import _raw_optical_summary, _read_raw_text
from manufacturing_check import _edge_thickness, _find_lens_surfaces, _to_float
from run_files import find_run_file


MTF_TARGETS = (20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 60.0)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return f"{value:.6g}"
    return str(value)


def _surface_by_number(rows: list[dict[str, Any]], number: int) -> dict[str, Any]:
    for row in rows:
        try:
            if int(row.get("surface_number") or row.get("surface_index")) == number:
                return row
        except (TypeError, ValueError):
            continue
    return {}


def _read_surfaces(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parse_field(description: str) -> float | None:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", description)
    if match is None:
        return None
    return _to_float(match.group(0))


def _parse_orientation(label: str) -> str:
    normalized = label.strip().lower()
    if normalized in {"子午", "t", "tan", "tangential", "tangential mtf"}:
        return "T"
    if normalized in {"弧矢", "s", "sag", "sagittal", "sagittal mtf"}:
        return "S"
    return label.strip() or "unknown"


def _is_real_mtf_curve(item: dict[str, Any]) -> bool:
    text = f"{item.get('description', '')} {item.get('label', '')}".lower()
    return not any(token in text for token in ("diffraction", "limit", "衍射", "极限"))


def _read_mtf(path: Path) -> tuple[list[float], list[dict[str, Any]]]:
    if not path.exists():
        return [], []

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    if len(rows) < 4:
        return [], []

    metadata_columns = {"run_id", "current_lens_file"}
    source_columns = [
        index
        for index in range(1, len(rows[0]))
        if (rows[0][index] if index < len(rows[0]) else "") not in metadata_columns
    ]
    descriptions = [rows[0][index] if index < len(rows[0]) else "" for index in source_columns]
    labels = [rows[1][index] if index < len(rows[1]) else "" for index in source_columns]
    frequencies: list[float] = []
    series_values: list[list[float | None]] = [[] for _ in source_columns]

    for row in rows[3:]:
        frequency = _to_float(row[0] if row else None)
        if frequency is None:
            continue
        frequencies.append(frequency)

        for output_index, source_index in enumerate(source_columns):
            value = row[source_index] if source_index < len(row) else None
            series_values[output_index].append(_to_float(value))

    series = []
    for index, values in enumerate(series_values):
        series.append(
            {
                "field": _parse_field(descriptions[index]),
                "orientation": _parse_orientation(labels[index]),
                "description": descriptions[index],
                "label": labels[index],
                "values": values,
            }
        )

    return frequencies, series


def _interpolate(x_values: list[float], y_values: list[float | None], target: float) -> float | None:
    points = [(x, y) for x, y in zip(x_values, y_values, strict=False) if y is not None]
    if not points or target < points[0][0] or target > points[-1][0]:
        return None

    for index, (x, y) in enumerate(points):
        if x == target:
            return y
        if x > target and index > 0:
            x0, y0 = points[index - 1]
            x1, y1 = x, y
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (target - x0) / (x1 - x0)

    return None


def _mtf_values(path: Path) -> dict[str, Any]:
    frequencies, series = _read_mtf(path)
    real_series = [item for item in series if _is_real_mtf_curve(item)]
    values: dict[str, Any] = {}

    for target in MTF_TARGETS:
        target_values = []
        for item in real_series:
            value = _interpolate(frequencies, item["values"], target)
            if value is None:
                continue
            target_values.append(value)

            field = item.get("field")
            orientation = item.get("orientation")
            if field is None or orientation not in {"T", "S"}:
                continue

            field_key = f"{field:g}".replace(".", "p")
            values[f"mtf_{field_key}_{orientation.lower()}_{int(target)}"] = value

        values[f"mtf{int(target)}_min"] = min(target_values) if target_values else None
        values[f"mtf{int(target)}_mean"] = sum(target_values) / len(target_values) if target_values else None

    warnings: list[str] = []
    for item in real_series:
        field = item.get("field")
        orientation = item.get("orientation")
        if field is None or abs(field - 25.0) > 1e-6 or orientation not in {"T", "S"}:
            continue

        curve_points = [
            value
            for frequency, value in zip(frequencies, item["values"], strict=False)
            if value is not None and 20.0 <= frequency <= 50.0
        ]
        if not curve_points:
            continue
        curve_min = min(curve_points)
        for target in (25.0, 30.0):
            key = f"mtf_25_{orientation.lower()}_{int(target)}"
            point = values.get(key)
            if point is not None and abs(point) <= 1e-12 and curve_min > 0.005:
                warnings.append(
                    f"{key} is zero but full 25{orientation} curve min(20-50)={curve_min:.6g}; "
                    "summary extraction may be inconsistent."
                )

    values["summary_extraction_warning"] = " | ".join(warnings) if warnings else None
    return values


def _lens_edge(surfaces: list[dict[str, Any]], label: str) -> float | None:
    lens_surfaces = _find_lens_surfaces(surfaces, label)
    if len(lens_surfaces) < 2:
        return None

    front, back = lens_surfaces[0], lens_surfaces[1]
    front_sd = _to_float(front.get("semi_diameter"))
    back_sd = _to_float(back.get("semi_diameter"))
    if front_sd is None or back_sd is None:
        return None

    return _edge_thickness(front, back, min(front_sd, back_sd))


def _warnings(manufacturing: dict[str, Any], warnings_path: Path) -> list[str]:
    messages: list[str] = []
    for check in ((manufacturing.get("checks") or {}).values()):
        for item in check.get("findings") or []:
            if item.get("level") in {"warning", "fail"}:
                messages.append(f"{item.get('level')}: {item.get('message')}")

    if warnings_path.exists():
        for line in warnings_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                messages.append(line.strip())

    return messages


def _structure_status(bfl: Any, ttl: Any, l5_edge: Any, l6_edge: Any) -> str:
    bfl_value = _to_float(bfl)
    ttl_value = _to_float(ttl)
    l5_edge_value = _to_float(l5_edge)
    l6_edge_value = _to_float(l6_edge)

    if bfl_value is not None and bfl_value < 2.3:
        return "fail"
    if ttl_value is not None and ttl_value > 18.0:
        return "fail"
    if l5_edge_value is not None and l5_edge_value < 0.35:
        return "fail"
    if l6_edge_value is not None and l6_edge_value < 0.35:
        return "fail"
    if l5_edge_value is not None and l5_edge_value < 0.40:
        return "warning"
    return "pass"


def _mtf_status(mtf: dict[str, Any]) -> str:
    mtf40_mean = _to_float(mtf.get("mtf40_mean"))
    mtf50_mean = _to_float(mtf.get("mtf50_mean"))

    if (mtf40_mean or 0) >= 0.08 and (mtf50_mean or 0) >= 0.09:
        return "candidate"
    if (mtf40_mean or 0) >= 0.06 and (mtf50_mean or 0) >= 0.075:
        return "weak_candidate"
    return "reject"


def _final_status(structure_status: str, mtf_status: str) -> str:
    if structure_status == "fail":
        return "reject"
    if structure_status == "pass" and mtf_status == "candidate":
        return "candidate"
    if structure_status in {"pass", "warning"} and mtf_status in {"candidate", "weak_candidate"}:
        return "mtf_warning"
    if structure_status == "pass":
        return "structure_pass"
    return "reject"


def _notch_diagnostic(mtf: dict[str, Any]) -> str:
    t20 = _to_float(mtf.get("mtf_25_t_20"))
    t30 = _to_float(mtf.get("mtf_25_t_30"))
    t40 = _to_float(mtf.get("mtf_25_t_40"))
    t50 = _to_float(mtf.get("mtf_25_t_50"))

    if t40 is None:
        return "unknown"
    if t40 < 0.01:
        low_neighbors = sum(1 for value in (t20, t30, t50) if value is not None and value < 0.02)
        if low_neighbors >= 2:
            return "broad_collapse"
        if t30 is not None and t50 is not None and t30 > 0.03 and t50 > 0.03:
            return "local_notch"
    return "unknown"


def export_chatgpt_summary(run_dir: Path, run_id: str, output_path: Path | None = None) -> Path:
    output_path = output_path or run_dir / f"{run_id}_summary_for_chatgpt.txt"
    metadata = _load_json(find_run_file(run_dir, "run_metadata"))
    system = _load_json(find_run_file(run_dir, "system_summary"))
    manufacturing = _load_json(find_run_file(run_dir, "manufacturing_check"))
    surfaces = _read_surfaces(find_run_file(run_dir, "surfaces"))
    mtf = _mtf_values(find_run_file(run_dir, "mtf_fft"))

    optical = system.get("optical_summary") or {}
    raw_path = find_run_file(run_dir, "system_data_raw")
    if raw_path.exists() and system.get("system_data_raw_valid") is not False:
        raw_optical = _raw_optical_summary(_read_raw_text(raw_path))
        optical = {**raw_optical, **{key: value for key, value in optical.items() if value is not None}}
    aperture = system.get("aperture") or {}
    lens_file = metadata.get("current_lens_file") or system.get("current_lens_file")
    label = metadata.get("label")
    scanned_parameter = metadata.get("scanned_parameter")
    scanned_mode = metadata.get("scanned_mode")
    target_comment = metadata.get("target_comment")
    scanned_surface = metadata.get("scanned_surface")
    scanned_surface_comment = metadata.get("scanned_surface_comment")
    scanned_radius = metadata.get("scanned_radius")
    scanned_thickness = metadata.get("scanned_thickness")
    scanned_conic = metadata.get("scanned_conic")
    image_shift = metadata.get("image_shift")
    original_image_thickness = metadata.get("original_image_thickness")
    new_image_thickness = metadata.get("new_image_thickness")
    scanned_coefficient = metadata.get("scanned_coefficient")
    scanned_value = metadata.get("scanned_value")
    scanned_surface_a = metadata.get("scanned_surface_a")
    scanned_surface_comment_a = metadata.get("scanned_surface_comment_a")
    scanned_radius_a = metadata.get("scanned_radius_a")
    scanned_surface_b = metadata.get("scanned_surface_b")
    scanned_surface_comment_b = metadata.get("scanned_surface_comment_b")
    scanned_radius_b = metadata.get("scanned_radius_b")
    scanned_material = metadata.get("scanned_material")
    material_catalog = metadata.get("material_catalog")
    requested_glass_catalog_name = metadata.get("requested_glass_catalog_name")
    requested_glass_catalog_path = metadata.get("requested_glass_catalog_path")
    material_nd = metadata.get("material_nd")
    material_vd = metadata.get("material_vd")
    requested_material = metadata.get("requested_material")
    actual_glass_name_after_set = metadata.get("actual_glass_name_after_set")
    actual_catalog_if_available = metadata.get("actual_catalog_if_available")
    actual_nd_if_available = metadata.get("actual_nd_if_available")
    actual_vd_if_available = metadata.get("actual_vd_if_available")
    surface_data_material_glass = metadata.get("surface_data_material_glass")
    surface_data_best_fit_glass = metadata.get("surface_data_best_fit_glass")
    material_validation_error = metadata.get("material_validation_error")
    material_validation_warning = metadata.get("material_validation_warning")
    is_material_resolved = metadata.get("is_material_resolved")
    material_set_success = metadata.get("material_set_success")
    failure_reason = metadata.get("failure_reason")
    base_lens = metadata.get("base_lens")
    scan_lens = metadata.get("scan_lens") or metadata.get("scan_copy_file")
    quick_focus = metadata.get("quick_focus")

    s7 = _surface_by_number(surfaces, 7)
    s6 = _surface_by_number(surfaces, 6)
    s8 = _surface_by_number(surfaces, 8)
    s9 = _surface_by_number(surfaces, 9)
    s11 = _surface_by_number(surfaces, 11)
    s12 = _surface_by_number(surfaces, 12)
    s13 = _surface_by_number(surfaces, 13)
    s15 = _surface_by_number(surfaces, 15)

    l5_edge = ((manufacturing.get("checks") or {}).get("l5") or {}).get("edge_thickness_at_common_semi_diameter")
    l6_edge = _lens_edge(surfaces, "L6")
    manufacturing_status = manufacturing.get("status")
    warning_lines = _warnings(manufacturing, find_run_file(run_dir, "warnings"))
    bfl = optical.get("bfl") or optical.get("back_focal_length")
    ttl = optical.get("ttl") or optical.get("total_track")
    structure_status = _structure_status(bfl, ttl, l5_edge, l6_edge)
    mtf_status = _mtf_status(mtf)
    status = _final_status(structure_status, mtf_status)
    notch_diagnostic = _notch_diagnostic(mtf)

    lines = [
        f"run_id: {run_id}",
        f"label: {_fmt(label)}",
        f"lens_file: {_fmt(lens_file)}",
        f"scanned_parameter: {_fmt(scanned_parameter)}",
        f"scanned_mode: {_fmt(scanned_mode)}",
        f"target_comment: {_fmt(target_comment)}",
        f"scanned_surface: {_fmt(scanned_surface)}",
        f"scanned_surface_comment: {_fmt(scanned_surface_comment)}",
        f"scanned_radius: {_fmt(scanned_radius)}",
        f"scanned_thickness: {_fmt(scanned_thickness)}",
        f"scanned_conic: {_fmt(scanned_conic)}",
        f"image_shift: {_fmt(image_shift)}",
        f"original_image_thickness: {_fmt(original_image_thickness)}",
        f"new_image_thickness: {_fmt(new_image_thickness)}",
        f"scanned_coefficient: {_fmt(scanned_coefficient)}",
        f"scanned_value: {_fmt(scanned_value)}",
        f"scanned_surface_a: {_fmt(scanned_surface_a)}",
        f"scanned_surface_comment_a: {_fmt(scanned_surface_comment_a)}",
        f"scanned_radius_a: {_fmt(scanned_radius_a)}",
        f"scanned_surface_b: {_fmt(scanned_surface_b)}",
        f"scanned_surface_comment_b: {_fmt(scanned_surface_comment_b)}",
        f"scanned_radius_b: {_fmt(scanned_radius_b)}",
        f"scanned_material: {_fmt(scanned_material)}",
        f"material_catalog: {_fmt(material_catalog)}",
        f"requested_glass_catalog_name: {_fmt(requested_glass_catalog_name)}",
        f"requested_glass_catalog_path: {_fmt(requested_glass_catalog_path)}",
        f"material_nd: {_fmt(material_nd)}",
        f"material_vd: {_fmt(material_vd)}",
        f"requested_material: {_fmt(requested_material)}",
        f"actual_glass_name_after_set: {_fmt(actual_glass_name_after_set)}",
        f"actual_catalog_if_available: {_fmt(actual_catalog_if_available)}",
        f"actual_nd_if_available: {_fmt(actual_nd_if_available)}",
        f"actual_vd_if_available: {_fmt(actual_vd_if_available)}",
        f"surface_data_material_glass: {_fmt(surface_data_material_glass)}",
        f"surface_data_best_fit_glass: {_fmt(surface_data_best_fit_glass)}",
        f"material_validation_error: {_fmt(material_validation_error)}",
        f"material_validation_warning: {_fmt(material_validation_warning)}",
        f"is_material_resolved: {_fmt(is_material_resolved)}",
        f"material_set_success: {_fmt(material_set_success)}",
        f"failure_reason: {_fmt(failure_reason)}",
        f"base_lens: {_fmt(base_lens)}",
        f"scan_lens: {_fmt(scan_lens)}",
        f"quick_focus: {_fmt(bool(quick_focus)) if quick_focus is not None else 'false'}",
        "",
        "[optical]",
        f"current_f_number: {_fmt(aperture.get('value') or optical.get('f_number'))}",
        f"efl: {_fmt(optical.get('efl') or optical.get('effective_focal_length_air'))}",
        f"bfl: {_fmt(bfl)}",
        f"ttl: {_fmt(ttl)}",
        f"working_f_number: {_fmt(optical.get('working_f_number'))}",
        f"image_space_f_number: {_fmt(optical.get('image_space_f_number'))}",
        f"epd: {_fmt(optical.get('entrance_pupil_diameter'))}",
        "",
        "[surfaces]",
        f"S6R: {_fmt(s6.get('radius'))}",
        f"S6T: {_fmt(s6.get('thickness'))}",
        f"S7R: {_fmt(s7.get('radius'))}",
        f"S7T: {_fmt(s7.get('thickness'))}",
        f"S8R: {_fmt(s8.get('radius'))}",
        f"S9T: {_fmt(s9.get('thickness'))}",
        f"S11T: {_fmt(s11.get('thickness'))}",
        f"S12R: {_fmt(s12.get('radius'))}",
        f"S13R: {_fmt(s13.get('radius'))}",
        f"S13_conic: {_fmt(s13.get('conic'))}",
        f"S15T: {_fmt(s15.get('thickness'))}",
        "",
        "[manufacturing]",
        f"L5_edge: {_fmt(l5_edge)}",
        f"L6_edge: {_fmt(l6_edge)}",
        f"manufacturing_status: {_fmt(manufacturing_status)}",
        "warnings: " + ("none" if not warning_lines else " | ".join(warning_lines[:8])),
        "",
        "[mtf_summary]",
        f"MTF40_min: {_fmt(mtf.get('mtf40_min'))}",
        f"MTF40_mean: {_fmt(mtf.get('mtf40_mean'))}",
        f"MTF50_min: {_fmt(mtf.get('mtf50_min'))}",
        f"MTF50_mean: {_fmt(mtf.get('mtf50_mean'))}",
        "",
        "[mtf_key_points]",
        f"0T40: {_fmt(mtf.get('mtf_0_t_40'))}",
        f"0S40: {_fmt(mtf.get('mtf_0_s_40'))}",
        f"0T50: {_fmt(mtf.get('mtf_0_t_50'))}",
        f"0S50: {_fmt(mtf.get('mtf_0_s_50'))}",
        f"20S40: {_fmt(mtf.get('mtf_20_s_40'))}",
        f"20S50: {_fmt(mtf.get('mtf_20_s_50'))}",
        f"25T20: {_fmt(mtf.get('mtf_25_t_20'))}",
        f"25T25: {_fmt(mtf.get('mtf_25_t_25'))}",
        f"25T30: {_fmt(mtf.get('mtf_25_t_30'))}",
        f"25T35: {_fmt(mtf.get('mtf_25_t_35'))}",
        f"25T40: {_fmt(mtf.get('mtf_25_t_40'))}",
        f"25T45: {_fmt(mtf.get('mtf_25_t_45'))}",
        f"25T50: {_fmt(mtf.get('mtf_25_t_50'))}",
        f"25T60: {_fmt(mtf.get('mtf_25_t_60'))}",
        f"25S20: {_fmt(mtf.get('mtf_25_s_20'))}",
        f"25S30: {_fmt(mtf.get('mtf_25_s_30'))}",
        f"25S40: {_fmt(mtf.get('mtf_25_s_40'))}",
        f"25S50: {_fmt(mtf.get('mtf_25_s_50'))}",
        f"27p5T40: {_fmt(mtf.get('mtf_27p5_t_40'))}",
        f"28T40: {_fmt(mtf.get('mtf_28_t_40'))}",
        f"28T50: {_fmt(mtf.get('mtf_28_t_50'))}",
        "",
        "[diagnostics]",
        f"25T_notch_or_broad_collapse: {notch_diagnostic}",
        f"summary_extraction_warning: {_fmt(mtf.get('summary_extraction_warning'))}",
        "",
        f"structure_status: {structure_status}",
        f"mtf_status: {mtf_status}",
        f"status: {status}",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
