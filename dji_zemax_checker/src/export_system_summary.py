from __future__ import annotations

import json
import math
import os
import re
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

from zospy.analyses.base import OnComplete
from zospy.analyses.reports import SystemData

from analysis_debug import update_analysis_debug
from export_surfaces import json_safe, safe_get
from run_metadata import load_run_metadata
from run_files import find_run_file, run_file


_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?")


class _SystemDataRaw(SystemData, analysis_type="SystemData", needs_text_output_file=True):
    def run_analysis(self) -> str:
        self.analysis.ApplyAndWaitForCompletion()
        return self.get_text_output()


def _dump_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_warning(output_dir: Path, message: str, run_id: str | None = None) -> None:
    path = run_file(output_dir, run_id, "warnings") if run_id else output_dir / "warnings.log"
    with path.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None


def _raw_line_value(raw_text: str, labels: tuple[str, ...]) -> float | None:
    for line in raw_text.splitlines():
        line_lower = line.lower()
        for label in labels:
            index = line_lower.find(label.lower())
            if index < 0:
                continue

            tail = line[index + len(label) :]
            match = _NUMBER_PATTERN.search(tail)
            if match is not None:
                return _to_float(match.group(0))

    return None


def _raw_lens_file(raw_text: str) -> str | None:
    for line in raw_text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("file") or stripped.startswith("文件"):
            parts = re.split(r"\s*[:：]\s*", stripped, maxsplit=1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def _raw_optical_summary(raw_text: str) -> dict[str, Any]:
    efl = _raw_line_value(
        raw_text,
        (
            "Effective Focal Length (air)",
            "Effective Focal Length",
            "EFL",
            "有效焦距",
        ),
    )
    bfl = _raw_line_value(raw_text, ("Back Focal Length", "BFL", "后焦距"))
    ttl = _raw_line_value(raw_text, ("Total Track", "TTL", "总长"))
    f_number = _raw_line_value(
        raw_text,
        (
            "Image Space F/#",
            "F/#",
            "像方空间 F/#",
        ),
    )
    paraxial_working_f_number = _raw_line_value(raw_text, ("Paraxial Working F/#", "近轴处理 F/#"))
    working_f_number = _raw_line_value(raw_text, ("Working F/#", "工作F/#"))
    entrance_pupil_diameter = _raw_line_value(raw_text, ("Entrance Pupil Diameter", "入瞳直径"))

    return {
        "effective_focal_length_air": json_safe(efl),
        "effective_focal_length_image": None,
        "back_focal_length": json_safe(bfl),
        "total_track": json_safe(ttl),
        "image_space_f_number": json_safe(f_number),
        "paraxial_working_f_number": json_safe(paraxial_working_f_number),
        "working_f_number": json_safe(working_f_number),
        "entrance_pupil_diameter": json_safe(entrance_pupil_diameter),
        "efl": json_safe(efl),
        "bfl": json_safe(bfl),
        "ttl": json_safe(ttl),
        "f_number": json_safe(f_number),
    }


def _read_raw_text(raw_path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = raw_path.read_text(encoding=encoding)
        except UnicodeError:
            continue
        if text.count("\x00") < max(1, len(text) // 20):
            return text

    return raw_path.read_text(encoding="utf-8", errors="replace")


def _close_existing_system_data_analyses(oss: Any) -> None:
    analyses = safe_get(oss, "Analyses")
    count = safe_get(analyses, "NumberOfAnalyses", 0) or 0
    indexes = list(range(int(count) - 1, -1, -1)) + list(range(int(count), 0, -1))
    seen: set[int] = set()

    for index in indexes:
        if index in seen:
            continue
        seen.add(index)

        try:
            analysis = analyses.Get_AnalysisAtIndex(index)
        except Exception:
            continue

        analysis_type = str(safe_get(analysis, "AnalysisType", ""))
        analysis_name = str(safe_get(analysis, "GetAnalysisName", ""))
        if "SystemData" not in analysis_type and "System Data" not in analysis_name and "系统" not in analysis_name:
            continue

        try:
            analyses.CloseAnalysis(index)
        except Exception:
            try:
                analysis.Close()
            except Exception:
                pass


def _same_windows_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _validate_raw_lens_file(
    raw_text: str,
    expected_lens_file: str | None,
) -> tuple[bool, str | None, str | None]:
    if not expected_lens_file:
        return False, None, "ERROR: current_lens_file is missing from run metadata."

    raw_file = _raw_lens_file(raw_text)
    if raw_file is None:
        return False, None, "ERROR: system_data_raw.txt does not contain a file path line."

    if not _same_windows_path(raw_file, expected_lens_file):
        return False, raw_file, (
            "ERROR: system_data_raw.txt lens file mismatch. "
            f"raw={raw_file}; metadata={expected_lens_file}"
        )

    return True, raw_file, None


def _write_invalid_raw_marker(raw_path: Path, message: str) -> None:
    raw_path.write_text(
        "ERROR: invalid System Data raw export\n"
        f"{message}\n"
        "The stale report was not retained as system_data_raw.txt.\n",
        encoding="utf-8",
    )


def _analysis_messages(analysis: Any) -> list[str]:
    try:
        return [f"{message.ErrorCode}: {message.Message}" for message in analysis.analysis.messages]
    except Exception:
        return []


def _analysis_header(analysis: Any) -> list[str]:
    try:
        return list(analysis.analysis.header_data)
    except Exception:
        return []


def _empty_optical_summary() -> dict[str, Any]:
    return {
        "effective_focal_length_air": None,
        "effective_focal_length_image": None,
        "back_focal_length": None,
        "total_track": None,
        "image_space_f_number": None,
        "paraxial_working_f_number": None,
        "working_f_number": None,
        "entrance_pupil_diameter": None,
        "efl": None,
        "bfl": None,
        "ttl": None,
        "f_number": None,
    }


def _first_existing_attr(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        value = safe_get(obj, name)
        if value is not None:
            return value
    return None


def _candidate_first_order_objects(oss: Any) -> list[Any]:
    system_data = safe_get(oss, "SystemData")
    lde = safe_get(oss, "LDE")
    candidates: list[Any] = []
    for obj in (system_data, lde, oss):
        if obj is None:
            continue
        candidates.append(obj)
        for attr in (
            "FirstOrderData",
            "FirstOrder",
            "ParaxialData",
            "Paraxial",
            "CardinalPoints",
            "SystemData",
        ):
            child = safe_get(obj, attr)
            if child is not None:
                candidates.append(child)
    return candidates


def _direct_numeric(oss: Any, names: tuple[str, ...]) -> float | None:
    for obj in _candidate_first_order_objects(oss):
        value = _to_float(_first_existing_attr(obj, names))
        if value is not None:
            return value
    return None


def _sum_finite_thicknesses_to_image(oss: Any) -> float | None:
    lde = safe_get(oss, "LDE")
    count = safe_get(lde, "NumberOfSurfaces")
    try:
        surface_count = int(count)
    except (TypeError, ValueError):
        return None

    total = 0.0
    found = False
    for index in range(surface_count - 1):
        try:
            thickness = _to_float(lde.GetSurfaceAt(index).Thickness)
        except Exception:
            thickness = None
        if thickness is None or not math.isfinite(thickness):
            continue
        total += thickness
        found = True
    return total if found else None


def _last_air_thickness_before_image(oss: Any) -> float | None:
    lde = safe_get(oss, "LDE")
    count = safe_get(lde, "NumberOfSurfaces")
    try:
        image_surface = int(count) - 1
    except (TypeError, ValueError):
        return None
    if image_surface <= 0:
        return None
    try:
        return _to_float(lde.GetSurfaceAt(image_surface - 1).Thickness)
    except Exception:
        return None


def _direct_optical_summary(oss: Any) -> dict[str, Any]:
    aperture = safe_get(safe_get(oss, "SystemData"), "Aperture")
    aperture_value = _to_float(safe_get(aperture, "ApertureValue"))
    efl = _direct_numeric(
        oss,
        (
            "EffectiveFocalLength",
            "EffectiveFocalLengthAir",
            "EFL",
            "ParaxialEffectiveFocalLength",
        ),
    )
    bfl = _direct_numeric(oss, ("BackFocalLength", "BFL", "ParaxialBackFocalLength"))
    ttl = _direct_numeric(oss, ("TotalTrack", "TotalTrackLength", "TTL"))
    f_number = _direct_numeric(oss, ("ImageSpaceFNum", "ImageSpaceFNumber", "FNumber", "FNum"))
    working_f_number = _direct_numeric(
        oss,
        ("WorkingFNumber", "WorkingFNum", "WorkingF/#", "ParaxialWorkingFNumber"),
    )
    entrance_pupil_diameter = _direct_numeric(oss, ("EntrancePupilDiameter", "EPD"))

    if bfl is None:
        bfl = _last_air_thickness_before_image(oss)
    if ttl is None:
        ttl = _sum_finite_thicknesses_to_image(oss)
    if f_number is None:
        f_number = aperture_value
    if working_f_number is None:
        working_f_number = f_number
    if entrance_pupil_diameter is None and efl is not None and f_number not in (None, 0):
        entrance_pupil_diameter = efl / f_number

    return {
        "effective_focal_length_air": json_safe(efl),
        "effective_focal_length_image": None,
        "back_focal_length": json_safe(bfl),
        "total_track": json_safe(ttl),
        "image_space_f_number": json_safe(f_number),
        "paraxial_working_f_number": None,
        "working_f_number": json_safe(working_f_number),
        "entrance_pupil_diameter": json_safe(entrance_pupil_diameter),
        "efl": json_safe(efl),
        "bfl": json_safe(bfl),
        "ttl": json_safe(ttl),
        "f_number": json_safe(f_number),
    }


def _read_fields(oss: Any) -> list[dict[str, Any]]:
    fields = safe_get(oss.SystemData, "Fields")
    count = safe_get(fields, "NumberOfFields", 0) or 0
    rows: list[dict[str, Any]] = []

    for i in range(1, int(count) + 1):
        field = safe_get(fields, "GetField")
        try:
            item = field(i) if callable(field) else fields.GetField(i)
        except Exception:
            rows.append({"number": i, "x": None, "y": None, "weight": None, "comment": None})
            continue

        rows.append(
            {
                "number": json_safe(safe_get(item, "FieldNumber", i)),
                "x": json_safe(safe_get(item, "X")),
                "y": json_safe(safe_get(item, "Y")),
                "weight": json_safe(safe_get(item, "Weight")),
                "comment": json_safe(safe_get(item, "Comment")),
            }
        )

    return rows


def _read_wavelengths(oss: Any) -> list[dict[str, Any]]:
    wavelengths = safe_get(oss.SystemData, "Wavelengths")
    count = safe_get(wavelengths, "NumberOfWavelengths", 0) or 0
    rows: list[dict[str, Any]] = []

    for i in range(1, int(count) + 1):
        getter = safe_get(wavelengths, "GetWavelength")
        try:
            item = getter(i) if callable(getter) else wavelengths.GetWavelength(i)
        except Exception:
            rows.append({"number": i, "wavelength": None, "weight": None, "is_primary": None})
            continue

        rows.append(
            {
                "number": json_safe(safe_get(item, "WavelengthNumber", i)),
                "wavelength": json_safe(safe_get(item, "Wavelength")),
                "weight": json_safe(safe_get(item, "Weight")),
                "is_primary": json_safe(safe_get(item, "IsPrimary")),
            }
        )

    return rows


def _analysis_summary(
    oss: Any,
    output_dir: Path,
    run_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    run_id = (run_metadata or {}).get("run_id")
    raw_path = run_file(output_dir, run_id, "system_data_raw") if run_id else output_dir / "system_data_raw.txt"
    warnings: list[str] = []
    raw_text: str | None = None
    expected_lens_file = (run_metadata or {}).get("current_lens_file")
    raw_status = {
        "system_data_raw_valid": False,
        "system_data_raw_lens_file": None,
        "current_lens_file": json_safe(expected_lens_file),
    }
    debug_status: dict[str, Any] = {
        "system_analysis_created": False,
        "system_analysis_ran": False,
        "system_text_exported": False,
        "system_parser_success": False,
        "system_direct_fallback_success": False,
        "system_error_message": None,
    }

    def direct_fallback() -> dict[str, Any] | None:
        fallback = _direct_optical_summary(oss)
        if any(value is not None for value in fallback.values()):
            debug_status["system_direct_fallback_success"] = True
            update_analysis_debug(output_dir, run_id, debug_status)
            return fallback
        debug_status["system_direct_fallback_success"] = False
        update_analysis_debug(output_dir, run_id, debug_status)
        return None

    raw_path.unlink(missing_ok=True)
    system_analysis = None
    try:
        _close_existing_system_data_analyses(oss)
        try:
            oss.update_status()
        except Exception:
            pass

        system_analysis = _SystemDataRaw()
        system_analysis._oss = weakref.proxy(oss)
        try:
            system_analysis._check_mode()
            system_analysis._create_analysis()
            debug_status["system_analysis_created"] = True
        except Exception as exc:
            debug_status["system_error_message"] = f"SystemData analysis creation failed: {type(exc).__name__}: {exc!r}"
            warnings.append(debug_status["system_error_message"])
            raise

        try:
            system_analysis.analysis.ApplyAndWaitForCompletion()
            debug_status["system_analysis_ran"] = True
            debug_status["system_messages"] = _analysis_messages(system_analysis)
            debug_status["system_header"] = _analysis_header(system_analysis)
        except Exception as exc:
            debug_status["system_error_message"] = f"SystemData analysis run failed: {type(exc).__name__}: {exc!r}"
            warnings.append(debug_status["system_error_message"])
            raise

        try:
            system_analysis.analysis.Results.GetTextFile(str(raw_path))
            debug_status["system_text_exported"] = raw_path.exists() and raw_path.stat().st_size > 0
            debug_status["system_messages"] = _analysis_messages(system_analysis)
            debug_status["system_header"] = _analysis_header(system_analysis)
            if not debug_status["system_text_exported"]:
                debug_status["system_error_message"] = "SystemData text export failed: output file was not created."
                warnings.append(debug_status["system_error_message"])
        except Exception as exc:
            debug_status["system_error_message"] = f"SystemData text export failed: {type(exc).__name__}: {exc!r}"
            warnings.append(debug_status["system_error_message"])
    except Exception as exc:
        if debug_status["system_error_message"] is None:
            debug_status["system_error_message"] = f"SystemData analysis failed: {type(exc).__name__}: {exc!r}"
            warnings.append(debug_status["system_error_message"])
        _close_existing_system_data_analyses(oss)
    finally:
        if system_analysis is not None:
            try:
                system_analysis._complete(OnComplete.Close)
            except Exception:
                pass

    if raw_path.exists():
        try:
            raw_text = _read_raw_text(raw_path)
            raw_is_valid, raw_lens_file, raw_error = _validate_raw_lens_file(raw_text, expected_lens_file)
            raw_status["system_data_raw_valid"] = raw_is_valid
            raw_status["system_data_raw_lens_file"] = json_safe(raw_lens_file)
            if raw_error:
                warnings.append(raw_error)
                debug_status["system_error_message"] = raw_error
                _write_invalid_raw_marker(raw_path, raw_error)
                update_analysis_debug(output_dir, run_id, debug_status)
                fallback = direct_fallback()
                if fallback is not None:
                    warnings.append("SystemData direct fallback used after raw lens validation failed.")
                return fallback, warnings, raw_status
        except Exception as exc:
            debug_status["system_error_message"] = f"SystemData parser failed: {type(exc).__name__}: {exc!r}"
            warnings.append(debug_status["system_error_message"])
    else:
        warnings.append("SystemData did not produce system_data_raw.txt.")
        if debug_status["system_error_message"] is None:
            debug_status["system_error_message"] = "SystemData text export failed: system_data_raw.txt was not produced."
        _write_invalid_raw_marker(
            raw_path,
            "ERROR: SystemData analysis did not create a raw text file for this run.",
        )
        fallback = direct_fallback()
        if fallback is not None:
            warnings.append("SystemData direct fallback used after text export failed.")
        return fallback, warnings, raw_status

    if raw_status["system_data_raw_valid"] and raw_text is not None:
        optical_summary = _raw_optical_summary(raw_text)
        if any(value is not None for value in optical_summary.values()):
            debug_status["system_parser_success"] = True
            update_analysis_debug(output_dir, run_id, debug_status)
            return optical_summary, warnings, raw_status

        debug_status["system_error_message"] = "SystemData parser failed: optical_summary parse returned only null fields."
        warnings.append(debug_status["system_error_message"])

    fallback = direct_fallback()
    if fallback is not None:
        warnings.append("SystemData direct fallback used after parser failure.")
    return fallback, warnings, raw_status


def build_system_summary(oss: Any, output_dir: Path, run_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata_path = find_run_file(output_dir, "run_metadata")
    if metadata_path.exists():
        run_metadata = load_run_metadata(metadata_path)

    analysis, warnings, raw_status = _analysis_summary(oss, output_dir, run_metadata=run_metadata)
    system_data = safe_get(oss, "SystemData")
    aperture = safe_get(system_data, "Aperture")
    units = safe_get(system_data, "Units")

    return {
        "run_metadata": run_metadata or {},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "system_name": json_safe(safe_get(oss, "SystemName")),
        "system_file": json_safe(safe_get(oss, "SystemFile")),
        "current_lens_file": raw_status["current_lens_file"],
        "system_data_raw_valid": raw_status["system_data_raw_valid"],
        "system_data_raw_lens_file": raw_status["system_data_raw_lens_file"],
        "mode": json_safe(safe_get(oss, "Mode")),
        "number_of_surfaces": json_safe(safe_get(safe_get(oss, "LDE"), "NumberOfSurfaces")),
        "aperture": {
            "type": json_safe(safe_get(aperture, "ApertureType")),
            "value": json_safe(safe_get(aperture, "ApertureValue")),
            "apodization_type": json_safe(safe_get(aperture, "ApodizationType")),
            "apodization_factor": json_safe(safe_get(aperture, "ApodizationFactor")),
        },
        "units": {
            "lens": json_safe(safe_get(units, "LensUnits")),
            "source": json_safe(safe_get(units, "SourceUnits")),
            "analysis": json_safe(safe_get(units, "AnalysisUnits")),
            "mtf": json_safe(safe_get(units, "MTFUnits")),
        },
        "optical_summary": analysis,
        "fields": _read_fields(oss),
        "wavelengths": _read_wavelengths(oss),
        "warnings": warnings,
    }


def export_system_summary(oss: Any, output_path: Path, run_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    output_path.unlink(missing_ok=True)
    metadata_path = find_run_file(output_path.parent, "run_metadata")
    if metadata_path.exists():
        run_metadata = load_run_metadata(metadata_path)

    summary = build_system_summary(oss, output_path.parent, run_metadata=run_metadata)
    expected_run_id = (run_metadata or {}).get("run_id")
    actual_run_id = (summary.get("run_metadata") or {}).get("run_id")
    if expected_run_id != actual_run_id:
        summary["warnings"].append(
            "ERROR: system_summary.json run_metadata mismatch before write. "
            f"expected={expected_run_id}; actual={actual_run_id}"
        )

    for warning in summary["warnings"]:
        _append_warning(output_path.parent, warning, run_id=(summary.get("run_metadata") or {}).get("run_id"))
    _dump_json(summary, output_path)
    return summary
