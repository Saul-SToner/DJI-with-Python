from __future__ import annotations

import argparse
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from zosapi_cleanup import close_all_analysis_windows

from export_system_summary import _analysis_summary, _direct_optical_summary, _read_fields

PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
DIAGNOSTIC_FIELDS = [0.0, 21.0, 35.0, 49.0, 63.0, 70.0]

CSV_FIELDS = ["item", "field_deg", "value", "unit", "status", "criterion", "source", "note"]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_hard_constraints")


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.8g}"
    if value is None:
        return "unknown"
    return str(value)


def _field_key(value: float) -> str:
    return f"{value:g}"


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
    numbers: list[float] = []
    for token in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?|[-+]?\.\d+(?:[Ee][-+]?\d+)?", line):
        value = _to_float(token)
        if value is not None:
            numbers.append(value)
    return numbers


def _status_threshold(value: float | None, criterion: str) -> str:
    if value is None:
        return "UNKNOWN"
    if criterion == "<=2.0":
        return "PASS" if value <= 2.0 else "FAIL"
    if criterion == "<18 mm":
        return "PASS" if value < 18.0 else "FAIL"
    if criterion == ">2.3 mm":
        return "PASS" if value > 2.3 else "FAIL"
    if criterion == ">=70 deg":
        return "PASS" if value >= 70.0 else "FAIL"
    if criterion == "<70%":
        return "PASS" if abs(value) < 70.0 else "FAIL"
    if criterion == "<40 deg":
        return "PASS" if value < 40.0 else "FAIL"
    if criterion == ">30%":
        return "PASS" if value > 30.0 else "FAIL"
    return "UNKNOWN"


def _append_row(
    rows: list[dict[str, Any]],
    item: str,
    value: Any,
    unit: str,
    status: str,
    criterion: str,
    source: str,
    note: str = "",
    field_deg: float | None = None,
) -> None:
    rows.append(
        {
            "item": item,
            "field_deg": "" if field_deg is None else f"{field_deg:g}",
            "value": _fmt(value),
            "unit": unit,
            "status": status,
            "criterion": criterion,
            "source": source,
            "note": note,
        }
    )


def _debug_object(name: str, obj: Any, lines: list[str]) -> None:
    lines.append(f"[{name}]")
    if obj is None:
        lines.append("object: None")
        return
    lines.append(f"type: {type(obj).__name__}")
    attrs = [attr for attr in dir(obj) if not attr.startswith("_")]
    lines.append("attrs_methods: " + ", ".join(attrs[:240]))
    for method_name in ("ApplyAndWaitForCompletion", "Apply", "WaitForCompletion", "GetResults", "ToFile", "Close"):
        lines.append(f"has_{method_name}: {callable(getattr(obj, method_name, None))}")
    try:
        results = obj.GetResults() if callable(getattr(obj, "GetResults", None)) else None
        lines.append(f"GetResults_type: {type(results).__name__ if results is not None else 'None'}")
        if results is not None:
            lines.append(f"results_has_GetTextFile: {callable(getattr(results, 'GetTextFile', None))}")
            lines.append(f"results_NumberOfDataSeries: {_safe_get(results, 'NumberOfDataSeries')}")
            lines.append(f"results_NumberOfDataGrids: {_safe_get(results, 'NumberOfDataGrids')}")
            lines.append(f"results_NumberOfRayData: {_safe_get(results, 'NumberOfRayData')}")
    except Exception as exc:
        lines.append(f"GetResults_exception: {type(exc).__name__}: {exc!r}")


def _write_debug(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _vector_values(vector: Any) -> list[float]:
    data = _safe_get(vector, "Data")
    if data is not None:
        return [_to_float(value) for value in data if _to_float(value) is not None]
    length = int(_safe_get(vector, "Length", 0) or 0)
    values: list[float] = []
    for index in range(length):
        try:
            value = _to_float(vector.GetValueAt(index))
            if value is not None:
                values.append(value)
        except Exception:
            continue
    return values


def _matrix_values(matrix: Any) -> list[list[float | None]]:
    data = _safe_get(matrix, "Data")
    if data is not None:
        return [[_to_float(value) for value in row] for row in data]
    rows = int(_safe_get(matrix, "Rows", 0) or 0)
    cols = int(_safe_get(matrix, "Cols", 0) or 0)
    values: list[list[float | None]] = []
    for row in range(rows):
        out_row: list[float | None] = []
        for col in range(cols):
            try:
                out_row.append(_to_float(matrix.GetValueAt(row, col)))
            except Exception:
                out_row.append(None)
        values.append(out_row)
    return values


def _series_rows(results: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    count = int(_safe_get(results, "NumberOfDataSeries", 0) or 0)
    for index in range(count):
        try:
            series = results.GetDataSeries(index)
        except Exception:
            try:
                series = results.DataSeries[index]
            except Exception:
                continue
        x_values = _vector_values(_safe_get(series, "XData"))
        y_matrix = _matrix_values(_safe_get(series, "YData"))
        labels = [str(label) for label in (_safe_get(series, "SeriesLabels") or [])]
        description = str(_safe_get(series, "Description", "") or "")
        x_label = str(_safe_get(series, "XLabel", "") or "")
        if not labels:
            labels = [description or f"series_{index}"]

        if len(y_matrix) == len(labels):
            for label_index, label in enumerate(labels):
                for point_index, x_value in enumerate(x_values):
                    value = y_matrix[label_index][point_index] if point_index < len(y_matrix[label_index]) else None
                    rows.append({"x": x_value, "y": value, "label": label, "description": description, "x_label": x_label})
        elif len(y_matrix) == len(x_values):
            for point_index, x_value in enumerate(x_values):
                for label_index, label in enumerate(labels):
                    row = y_matrix[point_index]
                    value = row[label_index] if label_index < len(row) else None
                    rows.append({"x": x_value, "y": value, "label": label, "description": description, "x_label": x_label})
    return rows


def _analysis_text_and_results(
    oss: Any,
    factory_name: str,
    raw_path: Path,
    debug_lines: list[str],
) -> tuple[str | None, Any | None, str | None]:
    analysis = None
    errors: list[str] = []
    try:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            raw_path.unlink()
        factory = getattr(oss.Analyses, factory_name)
        analysis = factory()
        debug_lines.append(f"created_analysis: {factory_name}")
        _debug_object(factory_name + "_before_apply", analysis, debug_lines)
        try:
            analysis.ApplyAndWaitForCompletion()
            debug_lines.append(f"{factory_name}.ApplyAndWaitForCompletion: ok")
        except Exception as exc:
            errors.append(f"ApplyAndWaitForCompletion failed: {type(exc).__name__}: {exc!r}")

        results = None
        try:
            results = analysis.GetResults()
            debug_lines.append(f"{factory_name}.GetResults: {type(results).__name__ if results is not None else 'None'}")
        except Exception as exc:
            errors.append(f"GetResults failed: {type(exc).__name__}: {exc!r}")

        if results is not None:
            try:
                if results.GetTextFile(str(raw_path)) and raw_path.exists():
                    return _read_text_file(raw_path), results, None if not errors else " | ".join(errors)
                errors.append("GetResults().GetTextFile returned false or no file")
            except Exception as exc:
                errors.append(f"GetResults().GetTextFile failed: {type(exc).__name__}: {exc!r}")

        try:
            analysis.ToFile(str(raw_path), False, False)
            if raw_path.exists():
                return _read_text_file(raw_path), results, None if not errors else " | ".join(errors)
            errors.append("ToFile completed but no file was created")
        except Exception as exc:
            errors.append(f"ToFile failed: {type(exc).__name__}: {exc!r}")

        message = " | ".join(errors) if errors else "analysis produced no text"
        raw_path.write_text(message + "\n", encoding="utf-8")
        return None, results, message
    except Exception as exc:
        message = f"{factory_name} failed: {type(exc).__name__}: {exc!r}"
        try:
            raw_path.write_text(message + "\n", encoding="utf-8")
        except Exception:
            pass
        return None, None, message
    finally:
        _debug_object(factory_name + "_final", analysis, debug_lines)
        if analysis is not None:
            try:
                analysis.Close()
            except Exception:
                pass


def _nearest_field_value(rows: list[dict[str, Any]], field: float, label_keywords: tuple[str, ...]) -> float | None:
    candidates = []
    for row in rows:
        x = _to_float(row.get("x"))
        y = _to_float(row.get("y"))
        label_text = f"{row.get('label', '')} {row.get('description', '')}".lower()
        if x is None or y is None:
            continue
        if label_keywords and not any(keyword in label_text for keyword in label_keywords):
            continue
        candidates.append((abs(x - field), y))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] < 1e-3 else None


def _parse_table_field_values(text: str | None, fields: list[float], keywords: tuple[str, ...]) -> dict[str, float]:
    if not text:
        return {}
    found: dict[str, float] = {}
    lines = text.splitlines()
    header_recent = False
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            header_recent = True
            continue
        stripped = line.strip()
        if not stripped:
            header_recent = False
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 2:
            continue
        for field in fields:
            key = _field_key(field)
            if key in found:
                continue
            if abs(numbers[0] - field) < 1e-3 or (len(numbers) > 1 and abs(numbers[1] - field) < 1e-3):
                if header_recent or re.match(r"^[-+]?\d", stripped):
                    found[key] = numbers[-1]
    return found


def _interpolate(points: list[tuple[float, float]], x: float) -> float | None:
    if not points:
        return None
    points = sorted(points)
    for px, py in points:
        if abs(px - x) < 1e-9:
            return py
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1 and x1 != x0:
            fraction = (x - x0) / (x1 - x0)
            return y0 + fraction * (y1 - y0)
    return None


def _parse_distortion_curve_text(text: str | None) -> dict[str, float]:
    if not text:
        return {}
    sections: list[tuple[float | None, list[tuple[float, float]]]] = []
    current_wave: float | None = None
    current_points: list[tuple[float, float]] = []

    for line in text.splitlines():
        if "数据对于波长" in line or "wavelength" in line.lower():
            if current_points:
                sections.append((current_wave, current_points))
            current_points = []
            numbers = _numbers_from_line(line)
            current_wave = numbers[0] if numbers else None
            continue
        numbers = _numbers_from_line(line)
        if len(numbers) >= 6 and abs(numbers[0]) <= 90:
            current_points.append((numbers[0], numbers[-1]))
    if current_points:
        sections.append((current_wave, current_points))

    if not sections:
        return {}
    wave, points = min(
        sections,
        key=lambda item: abs((item[0] if item[0] is not None else 0.55) - 0.55),
    )
    values: dict[str, float] = {}
    for field in DIAGNOSTIC_FIELDS:
        interpolated = _interpolate(points, field)
        if interpolated is not None:
            values[_field_key(field)] = interpolated
    return values


def _distortion_by_field(oss: Any, output_dir: Path, debug_lines: list[str]) -> tuple[dict[str, float], list[str], str]:
    raw_path = output_dir / "raw_field_curvature_distortion.txt"
    text, results, error = _analysis_text_and_results(oss, "New_FieldCurvatureAndDistortion", raw_path, debug_lines)
    warnings: list[str] = []
    if error:
        warnings.append(error)
    values: dict[str, float] = {}
    if results is not None:
        series = _series_rows(results)
        for field in DIAGNOSTIC_FIELDS:
            value = _nearest_field_value(series, field, ("distortion",))
            if value is not None:
                values[_field_key(field)] = value
    text_values = _parse_table_field_values(text, DIAGNOSTIC_FIELDS, ("distortion",))
    for key, value in text_values.items():
        values.setdefault(key, value)
    curve_values = _parse_distortion_curve_text(text)
    for key, value in curve_values.items():
        values[key] = value
    if not values:
        warnings.append("distortion parse failed from DataSeries and raw text")
    return values, warnings, str(raw_path)


def _relative_illumination_by_field(oss: Any, output_dir: Path, debug_lines: list[str]) -> tuple[dict[str, float], list[str], str, bool]:
    raw_path = output_dir / "raw_relative_illumination.txt"
    text, results, error = _analysis_text_and_results(oss, "New_RelativeIllumination", raw_path, debug_lines)
    warnings: list[str] = []
    if error:
        warnings.append(error)
    raw_values: dict[str, float] = {}
    source_confirmed = False
    if results is not None:
        series = _series_rows(results)
        for field in DIAGNOSTIC_FIELDS:
            value = _nearest_field_value(series, field, ("relative", "illum"))
            if value is not None:
                raw_values[_field_key(field)] = value
                source_confirmed = True

    if not raw_values:
        text_values = _parse_table_field_values(text, DIAGNOSTIC_FIELDS, ("relative", "illum"))
        lower_text = (text or "").lower()
        if "%" in lower_text or "percent" in lower_text or "relative illumination" in lower_text:
            raw_values.update(text_values)
            source_confirmed = bool(text_values)
        elif text_values:
            warnings.append("relative illumination text contained numeric values but unit was not confirmed")

    values: dict[str, float] = {}
    if source_confirmed:
        finite = [abs(value) for value in raw_values.values()]
        if finite and max(finite) <= 1.5:
            values = {key: value * 100.0 for key, value in raw_values.items()}
        else:
            values = dict(raw_values)
    else:
        warnings.append("relative illumination unit/source could not be confirmed")

    suspicious_center = False
    center = values.get("0")
    if center is not None and center < 50.0:
        suspicious_center = True
        warnings.append(f"suspicious_relative_illumination_center: field 0 parsed as {center:g}%")
    return values, warnings, str(raw_path), suspicious_center


def _trace_with_wrapper(oss: Any, field_number: int, raw_path: Path, trace_type: str) -> tuple[str | None, str | None]:
    try:
        from zospy.analyses.raysandspots.single_ray_trace import SingleRayTrace

        if raw_path.exists():
            raw_path.unlink()
        SingleRayTrace(
            hx=0.0,
            hy=0.0,
            px=0.0,
            py=0.0,
            field=field_number,
            raytrace_type=trace_type,
            global_coordinates=False,
        ).run(oss, text_output_file=raw_path)
        close_all_analysis_windows(oss)
        if raw_path.exists():
            return _read_text_file(raw_path), None
        return None, "SingleRayTrace wrapper did not create text file"
    except Exception as exc:
        close_all_analysis_windows(oss)
        if raw_path.exists():
            return _read_text_file(raw_path), f"wrapper parser/run failed but text exists: {type(exc).__name__}: {exc!r}"
        return None, f"wrapper failed: {type(exc).__name__}: {exc!r}"


def _cra_from_direction_cosine_text(text: str) -> float | None:
    for line in reversed(_actual_ray_trace_lines(text)):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if not (upper.startswith("IMA") or upper.startswith("IMAGE") or re.match(r"^\d+\s", stripped)):
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 6:
            continue
        starts_numeric_surface = re.match(r"^\d+\s", stripped) is not None
        offset = 1 if starts_numeric_surface else 0
        if len(numbers) >= offset + 6:
            l, m, n = numbers[offset + 3], numbers[offset + 4], numbers[offset + 5]
            if abs(n) > 1e-12:
                return math.degrees(math.atan2(math.sqrt(l * l + m * m), abs(n)))
    return None


def _cra_from_tangent_text(text: str) -> float | None:
    for line in reversed(_actual_ray_trace_lines(text)):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if not (upper.startswith("IMA") or upper.startswith("IMAGE") or re.match(r"^\d+\s", stripped)):
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 5:
            continue
        starts_numeric_surface = re.match(r"^\d+\s", stripped) is not None
        offset = 1 if starts_numeric_surface else 0
        if len(numbers) >= offset + 5:
            tx, ty = numbers[offset + 3], numbers[offset + 4]
            return math.degrees(math.atan(math.sqrt(tx * tx + ty * ty)))
    return None


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


def _cra_by_field(oss: Any, fields: list[dict[str, Any]], output_dir: Path, debug_lines: list[str]) -> tuple[dict[str, float], list[str]]:
    values: dict[str, float] = {}
    warnings: list[str] = []
    for target in DIAGNOSTIC_FIELDS:
        field_rows = [row for row in fields if _to_float(row.get("y")) is not None and abs(float(row["y"]) - target) < 1e-6]
        if not field_rows:
            warnings.append(f"field {target:g} not found for CRA")
            continue
        field_number = int(field_rows[0].get("number") or 0)
        raw_path = output_dir / f"raw_single_ray_trace_field_{target:g}.txt"

        text, error = _trace_with_wrapper(oss, field_number, raw_path, "TangentAngle")
        if error:
            warnings.append(f"field {target:g} tangent trace: {error}")
        angle = _cra_from_tangent_text(text or "") if text else None
        if angle is None:
            text2, error2 = _trace_with_wrapper(oss, field_number, raw_path, "DirectionCosines")
            if error2:
                warnings.append(f"field {target:g} direction-cosine trace: {error2}")
            angle = _cra_from_direction_cosine_text(text2 or "") if text2 else None
        if angle is not None:
            values[_field_key(target)] = angle
            if target > 0 and abs(angle) < 1e-8:
                warnings.append(f"suspicious_cra_zero: field {target:g} CRA parsed as 0 deg")
        else:
            warnings.append(f"field {target:g} CRA parse failed from raw ray trace text")
        debug_lines.append(f"SingleRayTrace field={target:g} field_number={field_number} raw={raw_path}")
    return values, warnings


def _field_rows(oss: Any) -> tuple[list[dict[str, Any]], list[str], float | None]:
    fields = _read_fields(oss)
    warnings: list[str] = []
    seen: dict[str, int] = {}
    for row in fields:
        y = _to_float(row.get("y"))
        if y is None:
            continue
        key = _field_key(y)
        seen[key] = seen.get(key, 0) + 1
    duplicates = [key for key, count in seen.items() if count > 1]
    if duplicates:
        warnings.append("duplicate field values detected: " + ", ".join(duplicates))
    max_half_field = max((_to_float(row.get("y")) or 0.0 for row in fields), default=None)
    return fields, warnings, max_half_field


def _image_metrics(oss: Any) -> tuple[int | None, float | None, str | None]:
    try:
        image_surface = int(oss.LDE.NumberOfSurfaces) - 1
        semi = _to_float(oss.LDE.GetSurfaceAt(image_surface).SemiDiameter)
        return image_surface, semi, None
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc!r}"


def _last_air_thickness_before_image(oss: Any) -> float | None:
    try:
        image_surface = int(oss.LDE.NumberOfSurfaces) - 1
        return _to_float(oss.LDE.GetSurfaceAt(image_surface - 1).Thickness)
    except Exception:
        return None


def _sum_ttl_from_lde(oss: Any) -> tuple[float | None, str]:
    try:
        image_surface = int(oss.LDE.NumberOfSurfaces) - 1
        values = []
        for surface_number in range(1, image_surface):
            thickness = _to_float(oss.LDE.GetSurfaceAt(surface_number).Thickness)
            if thickness is not None and math.isfinite(thickness):
                values.append(thickness)
        return sum(values), f"LDE thickness sum S1..S{image_surface - 1}; object infinity excluded"
    except Exception as exc:
        return None, f"TTL LDE fallback failed: {type(exc).__name__}: {exc!r}"


def _system_metrics(
    oss: Any,
    output_dir: Path,
    run_id: str,
    warnings: list[str],
    lens_path: str,
) -> dict[str, Any]:
    direct = _direct_optical_summary(oss)
    raw_optical, raw_warnings, _raw_status = _analysis_summary(
        oss,
        output_dir,
        run_metadata={"run_id": run_id, "current_lens_file": lens_path},
    )
    warnings.extend(f"SystemData: {warning}" for warning in raw_warnings)
    optical: dict[str, Any] = dict(direct)
    if raw_optical:
        for key, value in raw_optical.items():
            if value is not None:
                optical[key] = value

    ttl = _to_float(optical.get("ttl"))
    ttl_source = "SystemData/direct"
    ttl_note = "TTL definition: first real optical surface to image; object infinity excluded."
    if ttl is None:
        ttl, ttl_note = _sum_ttl_from_lde(oss)
        ttl_source = "LDE fallback"

    bfl = _to_float(raw_optical.get("bfl") if raw_optical else None)
    bfl_source = "SystemData"
    bfl_fallback_used = False
    if bfl is None:
        bfl = _last_air_thickness_before_image(oss)
        bfl_source = "LDE fallback"
        bfl_fallback_used = True

    return {
        "f_number": _to_float(optical.get("f_number")),
        "efl": _to_float(optical.get("efl")),
        "ttl": ttl,
        "ttl_source": ttl_source,
        "ttl_note": ttl_note,
        "bfl": bfl,
        "bfl_source": bfl_source,
        "bfl_fallback_used": bfl_fallback_used,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    warnings: list[str],
    system_metrics: dict[str, Any],
    image_surface: int | None,
    image_semi: float | None,
    lens_path: str,
) -> None:
    pass_count = sum(1 for row in rows if row["status"] == "PASS")
    fail_count = sum(1 for row in rows if row["status"] == "FAIL")
    unknown_count = sum(1 for row in rows if row["status"] == "UNKNOWN")
    field_values = ", ".join(_fmt(row.get("y")) for row in fields) if fields else "unknown"
    lines = [
        "DJI Hard Constraint Diagnostic",
        f"lens path: {lens_path}",
        "read-only confirmation: lens loaded with saveifneeded=False; script contains no save/save_as/optimization calls.",
        f"number of surfaces: {next((row['value'] for row in rows if row['item'] == 'number_of_surfaces'), 'unknown')}",
        f"F/#: {_fmt(system_metrics.get('f_number'))}",
        f"EFL: {_fmt(system_metrics.get('efl'))} mm",
        f"TTL: {_fmt(system_metrics.get('ttl'))} mm",
        f"BFL: {_fmt(system_metrics.get('bfl'))} mm",
        f"image surface: {_fmt(image_surface)}",
        f"image surface semi-diameter: {_fmt(image_semi)} mm",
        f"field list: {field_values}",
        "",
        "BFL definition: prefer OpticStudio System Data Back Focal Length; if unavailable, fallback is image surface preceding thickness.",
        f"BFL fallback used: {bool(system_metrics.get('bfl_fallback_used'))}",
        "TTL definition: from first real optical surface to image; object infinity excluded.",
        f"TTL source/detail: {system_metrics.get('ttl_source')} - {system_metrics.get('ttl_note')}",
        "",
        "[field table]",
        "field, distortion_signed_percent, distortion_status, CRA_deg, CRA_status, relative_illumination_percent, RI_status",
    ]
    for field in DIAGNOSTIC_FIELDS:
        key = _field_key(field)
        signed = _value_for(rows, "distortion_signed_percent", key)
        d_status = _status_for(rows, "distortion_abs_percent", key)
        cra = _value_for(rows, "cra_deg", key)
        cra_status = _status_for(rows, "cra_deg", key)
        ri = _value_for(rows, "relative_illumination_percent", key)
        ri_status = _status_for(rows, "relative_illumination_percent", key)
        lines.append(f"{field:g}, {signed}, {d_status}, {cra}, {cra_status}, {ri}, {ri_status}")

    lines.extend(
        [
            "",
            "[summary]",
            f"pass_count: {pass_count}",
            f"fail_count: {fail_count}",
            f"unknown_count: {unknown_count}",
            "",
            "[warnings]",
        ]
    )
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("none")

    lines.append("")
    lines.append("[interpretation]")
    if fail_count:
        lines.append("当前 lens 不满足至少一项已读取硬约束。TTL/BFL/F/# 等系统级失败项可信度最高。")
    elif unknown_count:
        lines.append("已读取项目未发现失败，但仍有 unknown 项，需要人工从 Zemax 对应图表确认。")
    else:
        lines.append("脚本可读取的硬约束均为 PASS。")
    if any("parse" in warning.lower() or "unknown" in warning.lower() for warning in warnings):
        lines.append("部分 field 指标依赖文本解析；unknown 项不可当作 pass。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _value_for(rows: list[dict[str, Any]], item: str, field_key: str) -> str:
    for row in rows:
        if row["item"] == item and row["field_deg"] == field_key:
            return row["value"]
    return "unknown"


def _status_for(rows: list[dict[str, Any]], item: str, field_key: str) -> str:
    for row in rows:
        if row["item"] == item and row["field_deg"] == field_key:
            return row["status"]
    return "UNKNOWN"


def diagnose_dji_hard_constraints(lens_path: str) -> None:
    lens_file = Path(lens_path)
    run_id = _run_id()
    output_dir = PROJECT_ROOT / "results" / "hard_constraints" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_lines: list[str] = [f"run_id: {run_id}", f"lens_path: {lens_path}"]

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

    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    try:
        oss.load(lens_path, saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    lde = oss.LDE
    number_of_surfaces = int(lde.NumberOfSurfaces)
    fields, field_warnings, max_half_field = _field_rows(oss)
    warnings.extend(field_warnings)
    image_surface, image_semi, image_error = _image_metrics(oss)
    if image_error:
        warnings.append(f"image surface semi-diameter unknown: {image_error}")
    metrics = _system_metrics(oss, output_dir, run_id, warnings, lens_path)

    _append_row(rows, "lens_path", lens_path, "", "PASS", "input path", "--lens")
    _append_row(rows, "number_of_surfaces", number_of_surfaces, "surfaces", "PASS", "record", "LDE")
    _append_row(rows, "f_number", metrics["f_number"], "", _status_threshold(metrics["f_number"], "<=2.0"), "<=2.0", "SystemData/direct")
    _append_row(rows, "efl", metrics["efl"], "mm", "PASS" if metrics["efl"] is not None else "UNKNOWN", "record", "SystemData/direct")
    _append_row(rows, "ttl", metrics["ttl"], "mm", _status_threshold(metrics["ttl"], "<18 mm"), "<18 mm", metrics["ttl_source"], metrics["ttl_note"])
    _append_row(rows, "bfl", metrics["bfl"], "mm", _status_threshold(metrics["bfl"], ">2.3 mm"), ">2.3 mm", metrics["bfl_source"], f"fallback_used={metrics['bfl_fallback_used']}")
    _append_row(rows, "image_surface_number", image_surface, "", "PASS" if image_surface is not None else "UNKNOWN", "record", "LDE")
    _append_row(rows, "image_surface_semi_diameter", image_semi, "mm", "PASS" if image_semi is not None else "UNKNOWN", "record", "LDE")
    _append_row(rows, "max_half_field", max_half_field, "deg", _status_threshold(max_half_field, ">=70 deg"), ">=70 deg", "SystemData.Fields")

    distortion, distortion_warnings, distortion_raw = _distortion_by_field(oss, output_dir, debug_lines)
    warnings.extend("distortion: " + warning for warning in distortion_warnings)
    ri, ri_warnings, ri_raw, _suspicious_center = _relative_illumination_by_field(oss, output_dir, debug_lines)
    warnings.extend("relative illumination: " + warning for warning in ri_warnings)
    cra, cra_warnings = _cra_by_field(oss, fields, output_dir, debug_lines)
    warnings.extend("CRA: " + warning for warning in cra_warnings)

    distortion_values_for_monotonic = []
    for field in DIAGNOSTIC_FIELDS:
        key = _field_key(field)
        signed = distortion.get(key)
        distortion_values_for_monotonic.append(signed)
        d_note = "parsed from DataSeries/text" if signed is not None else "parse failed"
        _append_row(rows, "distortion_signed_percent", signed, "%", "PASS" if signed is not None else "UNKNOWN", "record", "FieldCurvatureDistortion", d_note, field)
        _append_row(rows, "distortion_abs_percent", abs(signed) if signed is not None else None, "%", _status_threshold(abs(signed) if signed is not None else None, "<70%"), "<70%", "FieldCurvatureDistortion", d_note, field)

        cra_value = cra.get(key)
        cra_note = "chief ray Px=0 Py=0, image local angle" if cra_value is not None else "parse failed"
        if field > 0 and cra_value is not None and abs(cra_value) < 1e-8:
            cra_note += "; suspicious_cra_zero"
        _append_row(rows, "cra_deg", cra_value, "deg", _status_threshold(cra_value, "<40 deg"), "<40 deg", "SingleRayTrace", cra_note, field)

        ri_value = ri.get(key)
        ri_note = "confirmed percent or normalized-to-percent" if ri_value is not None else "unit not confirmed or parse failed"
        _append_row(rows, "relative_illumination_percent", ri_value, "%", _status_threshold(ri_value, ">30%"), ">30%", "RelativeIllumination", ri_note, field)

    if all(value is not None for value in distortion_values_for_monotonic):
        abs_values = [abs(float(value)) for value in distortion_values_for_monotonic if value is not None]
        monotonic = all(abs_values[i] <= abs_values[i + 1] + 1e-9 for i in range(len(abs_values) - 1))
        _append_row(rows, "distortion_abs_monotonic", str(monotonic), "", "PASS" if monotonic else "FAIL", "roughly monotonic", "FieldCurvatureDistortion")
    else:
        _append_row(rows, "distortion_abs_monotonic", None, "", "UNKNOWN", "roughly monotonic", "FieldCurvatureDistortion", "not enough parsed field values")

    summary_path = output_dir / "hard_constraint_summary.csv"
    report_path = output_dir / "hard_constraint_report.txt"
    debug_path = output_dir / "debug_api_methods.txt"
    _write_csv(summary_path, rows)
    _write_report(report_path, rows, fields, warnings, metrics, image_surface, image_semi, lens_path)
    _write_debug(debug_path, debug_lines)

    print(f"hard_constraint_report: {report_path}", flush=True)
    print(f"hard_constraint_summary: {summary_path}", flush=True)
    print(f"raw_field_curvature_distortion: {distortion_raw}", flush=True)
    print(f"raw_relative_illumination: {ri_raw}", flush=True)
    print(f"debug_api_methods: {debug_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only DJI hard-constraint diagnostic for a specified Zemax lens."
    )
    parser.add_argument(
        "--lens",
        required=True,
        help="Path to the lens file to analyze. Required; no default lens path is used.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_dji_hard_constraints(args.lens)
