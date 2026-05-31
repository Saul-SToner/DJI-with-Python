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
from pandas import DataFrame
from zospy.analyses.raysandspots.single_ray_trace import SingleRayTrace

from diagnose_mtf_field import _run_fft_mtf_dataframe
from export_chatgpt_summary import _interpolate, _is_real_mtf_curve, _read_mtf
from scan_radius import _safe_label
from zosapi_cleanup import close_all_analysis_windows


FIELDS_DEG = (0.0, 21.0, 35.0, 49.0, 63.0, 70.0)
MTF_FIELDS = (0.0, 21.0, 35.0)
MTF_FREQS = (20.0, 30.0)
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


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _raw_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None


def _fmt(value: Any, digits: int = 6) -> str:
    number = _raw_float(value)
    if number is None:
        return "null" if value is None else str(value)
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    if math.isnan(number):
        return "nan"
    return f"{number:.{digits}g}"


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _unique_run_dir(project_root: Path, label: str) -> tuple[str, Path]:
    root = project_root / "results" / "object_condition_effects"
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


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
            row.update({"l": numbers[4], "m": numbers[5], "n": numbers[6]})
        elif len(numbers) >= 6:
            row.update({"l": numbers[3], "m": numbers[4], "n": numbers[5]})
        rows[surface] = row
    return rows


def _field_table(oss: Any) -> list[dict[str, Any]]:
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
    number = _raw_float(value)
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


def _direct_efl(oss: Any) -> float | None:
    for obj in (_safe_get(oss, "SystemData"), _safe_get(oss, "LDE"), oss):
        if obj is None:
            continue
        for name in ("EffectiveFocalLength", "EffectiveFocalLengthAir", "EFL", "ParaxialEffectiveFocalLength"):
            value = _to_float(_safe_get(obj, name))
            if value is not None:
                return value
    return None


def _system_metrics(oss: Any) -> dict[str, Any]:
    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    image_surface = count - 1
    last_surface = image_surface - 1
    aperture = _safe_get(_safe_get(oss, "SystemData"), "Aperture")
    return {
        "f_number": _to_float(_safe_get(aperture, "ApertureValue")),
        "efl": _direct_efl(oss),
        "ttl": _ttl_from_lde(oss),
        "bfl": _to_float(lde.GetSurfaceAt(last_surface).Thickness),
        "image_surface": image_surface,
        "image_semi_diameter": _to_float(lde.GetSurfaceAt(image_surface).SemiDiameter),
        "number_of_surfaces": count,
    }


def _trace_ray(
    oss: Any,
    *,
    field_number: int,
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


def _chief_ray_angle(row: dict[str, float] | None) -> float | None:
    if row is None:
        return None
    l = _to_float(row.get("l"))
    m = _to_float(row.get("m"))
    n = _to_float(row.get("n"))
    if l is None or m is None or n is None or abs(n) < 1e-12:
        return None
    return math.degrees(math.atan2(math.sqrt(l * l + m * m), abs(n)))


def _rms(points: list[tuple[float, float]]) -> tuple[float | None, float | None, float | None, float | None]:
    if not points:
        return None, None, None, None
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    rms = math.sqrt(sum((x - cx) ** 2 + (y - cy) ** 2 for x, y in points) / len(points))
    max_radius = max(math.hypot(x, y) for x, y in points)
    return cx, cy, rms, max_radius


def _raytrace_field(
    oss: Any,
    raw_dir: Path,
    *,
    case_name: str,
    field_deg: float,
    field_number: int | None,
    image_surface: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {
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
        "raytrace_status": "failed",
        "raytrace_failure_reason": None,
    }
    if field_number is None:
        row["ray_trace_failure_count"] = len(PUPIL_SAMPLES)
        row["failed_pupil_coordinates"] = "; ".join(f"({px:g},{py:g})" for px, py in PUPIL_SAMPLES)
        row["raytrace_failure_reason"] = "Requested field is not present in current lens field table."
        return row

    hits: list[tuple[float, float]] = []
    failures: list[str] = []
    warnings: list[str] = []
    chief: dict[str, float] | None = None
    for px, py in PUPIL_SAMPLES:
        raw_path = raw_dir / (
            f"{_safe_label(case_name)}_f{_field_key(field_deg)}_px{_field_key(px)}_py{_field_key(py)}.txt"
        )
        trace_row, failure = _trace_ray(
            oss,
            field_number=field_number,
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
            warnings.append(f"({px:g},{py:g}) {failure}")
        if abs(px) < 1e-12 and abs(py) < 1e-12:
            chief = trace_row
            row["chief_ray_x"] = x
            row["chief_ray_y"] = y

    cx, cy, rms, max_radius = _rms(hits)
    row.update(
        {
            "ray_trace_success_count": len(hits),
            "ray_trace_failure_count": len(failures),
            "failed_pupil_coordinates": "; ".join(failures),
            "centroid_x": cx,
            "centroid_y": cy,
            "geometric_rms_spot_radius": rms,
            "max_ray_radius_on_image": max_radius,
            "chief_ray_angle_deg": _chief_ray_angle(chief),
        }
    )
    if not hits:
        row["raytrace_status"] = "failed"
        row["raytrace_failure_reason"] = "All sampled rays failed."
    elif failures:
        row["raytrace_status"] = "partial"
        row["raytrace_failure_reason"] = "Some sampled rays failed."
    else:
        row["raytrace_status"] = "success"
    if warnings:
        extra = " | ".join(warnings)
        row["raytrace_failure_reason"] = (
            f"{row['raytrace_failure_reason']}; {extra}" if row["raytrace_failure_reason"] else extra
        )
    return row


def _nearest_series(series: list[dict[str, Any]], field: float, orientation: str) -> dict[str, Any] | None:
    candidates = [
        item
        for item in series
        if _is_real_mtf_curve(item)
        and item.get("orientation") == orientation
        and _to_float(item.get("field")) is not None
    ]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda item: abs(float(item["field"]) - field))
    if abs(float(nearest["field"]) - field) > 0.25:
        return None
    return nearest


def _run_lowfreq_mtf(oss: Any, case_dir: Path, case_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {"fft_mtf_usable_dataframe": False, "fft_mtf_failure_reason": None}
    try:
        data, warnings = _run_fft_mtf_dataframe(oss, max(MTF_FREQS))
        close_all_analysis_windows(oss)
        if warnings:
            result["fft_mtf_warnings"] = " | ".join(warnings)
        if data is None or not isinstance(data, DataFrame) or data.empty:
            raise RuntimeError("FFT MTF returned no usable DataFrame.")
        raw_path = case_dir / f"{_safe_label(case_name)}_lowfreq_fft_mtf_raw.csv"
        data.to_csv(raw_path, index=True, encoding="utf-8-sig")
        frequencies, series = _read_mtf(raw_path)
        if not frequencies or not series:
            raise RuntimeError("Could not parse FFT MTF raw CSV.")
        result["fft_mtf_usable_dataframe"] = True
        result["fft_mtf_raw_csv"] = str(raw_path)
        for field in MTF_FIELDS:
            for orientation in ("T", "S"):
                item = _nearest_series(series, field, orientation)
                for freq in MTF_FREQS:
                    key = f"mtf_{_field_key(field)}_{orientation}_{int(freq)}"
                    result[key] = _interpolate(frequencies, item["values"], freq) if item is not None else None
    except Exception as exc:
        close_all_analysis_windows(oss)
        result["fft_mtf_failure_reason"] = f"{type(exc).__name__}: {exc!r}"
    return result


def _set_obj(surface: Any, radius: float, thickness: float) -> str | None:
    try:
        surface.Radius = radius
        surface.Thickness = thickness
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc!r}"


def _case_definitions(current_radius: float, current_thickness: float) -> list[dict[str, Any]]:
    return [
        {
            "case_name": "Case A current_finite_curved_object",
            "case_key": "current_finite_curved_object",
            "obj_radius": current_radius,
            "obj_thickness": current_thickness,
            "note": "Original OBJ Radius and Thickness.",
        },
        {
            "case_name": "Case B finite_flat_object",
            "case_key": "finite_flat_object",
            "obj_radius": math.inf,
            "obj_thickness": current_thickness,
            "note": "OBJ Radius set to Zemax Infinity with current OBJ Thickness.",
        },
        {
            "case_name": "Case C infinite_object",
            "case_key": "infinite_object",
            "obj_radius": math.inf,
            "obj_thickness": math.inf,
            "note": "OBJ Radius and Thickness set to Zemax Infinity.",
        },
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    case_fields = [
        "case_key",
        "case_name",
        "obj_radius",
        "obj_thickness",
        "f_number",
        "efl",
        "ttl",
        "bfl",
        "image_semi_diameter",
        "field_list",
        "field_deg",
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
        "raytrace_status",
        "raytrace_failure_reason",
        "fft_mtf_usable_dataframe",
        "fft_mtf_failure_reason",
        "mtf_0_T_20",
        "mtf_0_T_30",
        "mtf_0_S_20",
        "mtf_0_S_30",
        "mtf_21_T_20",
        "mtf_21_T_30",
        "mtf_21_S_20",
        "mtf_21_S_30",
        "mtf_35_T_20",
        "mtf_35_T_30",
        "mtf_35_S_20",
        "mtf_35_S_30",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=case_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _case_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(str(row.get("case_key")), []).append(row)
    summary = []
    for case_key, group in by_case.items():
        rms_values = [_to_float(row.get("geometric_rms_spot_radius")) for row in group]
        rms_values = [value for value in rms_values if value is not None]
        summary.append(
            {
                "case_key": case_key,
                "case_name": group[0].get("case_name"),
                "ray_success_total": sum(int(row.get("ray_trace_success_count") or 0) for row in group),
                "ray_failure_total": sum(int(row.get("ray_trace_failure_count") or 0) for row in group),
                "mean_rms_spot": sum(rms_values) / len(rms_values) if rms_values else None,
                "max_rms_spot": max(rms_values) if rms_values else None,
                "fft_mtf_usable_dataframe": group[0].get("fft_mtf_usable_dataframe"),
                "fft_mtf_failure_reason": group[0].get("fft_mtf_failure_reason"),
                "ttl": group[0].get("ttl"),
                "bfl": group[0].get("bfl"),
            }
        )
    return summary


def _write_report(path: Path, *, lens: Path, run_id: str, rows: list[dict[str, Any]], restored: bool) -> None:
    summaries = _case_summary(rows)
    current = next((row for row in summaries if row["case_key"] == "current_finite_curved_object"), None)
    finite_flat = next((row for row in summaries if row["case_key"] == "finite_flat_object"), None)
    infinite = next((row for row in summaries if row["case_key"] == "infinite_object"), None)

    lines = [
        "Object Condition Effects Diagnostic",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        "allowed_temporary_change: OBJ Radius and OBJ Thickness only",
        f"original_OBJ_restored: {str(restored).lower()}",
        "",
        "[case_summary]",
    ]
    for item in summaries:
        lines.append(
            "  "
            f"{item['case_key']}: ray_success={item['ray_success_total']}, "
            f"ray_failure={item['ray_failure_total']}, "
            f"mean_rms_spot={_fmt(item['mean_rms_spot'])}, "
            f"max_rms_spot={_fmt(item['max_rms_spot'])}, "
            f"FFT_MTF_usable={item['fft_mtf_usable_dataframe']}, "
            f"TTL={_fmt(item['ttl'])}, BFL={_fmt(item['bfl'])}"
        )

    lines.extend(["", "[interpretation]"])
    if current and finite_flat:
        current_fail = int(current.get("ray_failure_total") or 0)
        flat_fail = int(finite_flat.get("ray_failure_total") or 0)
        current_rms = _to_float(current.get("mean_rms_spot"))
        flat_rms = _to_float(finite_flat.get("mean_rms_spot"))
        if flat_fail < current_fail or (
            current_rms is not None and flat_rms is not None and flat_rms < 0.8 * current_rms
        ):
            lines.append("OBJ Radius appears to materially affect ray trace / spot behavior; the current curved finite OBJ condition should not be ignored.")
        else:
            lines.append("Changing OBJ Radius from current finite curved to flat finite did not clearly improve sampled ray trace / spot behavior.")
    if infinite:
        inf_fail = int(infinite.get("ray_failure_total") or 0)
        inf_mtf = str(infinite.get("fft_mtf_usable_dataframe")).lower() == "true"
        if inf_fail == 0 and inf_mtf:
            lines.append("Infinite object condition is ray-trace and low-frequency FFT-MTF usable in this diagnostic; it is a reasonable primary condition for DJI-style distant-object work.")
        elif inf_fail == 0:
            lines.append("Infinite object ray trace is usable, but FFT MTF was not usable; keep INF as a candidate condition and inspect analysis/export details.")
        else:
            lines.append("Infinite object condition still has sampled ray trace failures; do not assume it fixes the current model.")
    lines.append("Future scan/report scripts should include OBJ Radius and OBJ Thickness in metadata to avoid mixing finite and infinity object conditions.")
    lines.append("For design work, keep separate configurations or copies for INF and finite/MOD object conditions rather than silently switching OBJ state.")

    failed_rows = [row for row in rows if row.get("raytrace_status") != "success"]
    if failed_rows:
        lines.extend(["", "[raytrace_failures]"])
        for row in failed_rows[:20]:
            lines.append(
                "  "
                f"{row.get('case_key')} field={_fmt(row.get('field_deg'))}: "
                f"status={row.get('raytrace_status')}, failure={row.get('raytrace_failure_reason')}"
            )
        if len(failed_rows) > 20:
            lines.append(f"  ... {len(failed_rows) - 20} more rows")

    lines.extend(
        [
            "",
            "[files]",
            f"object_condition_effects_summary: {path.parent / 'object_condition_effects_summary.csv'}",
            f"object_condition_effects_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_object_conditions(project_root: Path, lens: Path, label: str) -> Path:
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

    print("Loading lens for temporary OBJ-condition diagnostics...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    obj = lde.GetSurfaceAt(0)
    original_radius = _raw_float(obj.Radius)
    original_thickness = _raw_float(obj.Thickness)
    if original_radius is None or original_thickness is None:
        raise RuntimeError("Could not read original OBJ Radius/Thickness.")

    fields = _field_table(oss)
    field_numbers = {field: _field_number(fields, field) for field in FIELDS_DEG}
    rows: list[dict[str, Any]] = []
    restored = False

    try:
        for case in _case_definitions(original_radius, original_thickness):
            print(f"Running {case['case_name']}", flush=True)
            case_dir = run_dir / _safe_label(case["case_key"])
            case_dir.mkdir(parents=True, exist_ok=True)
            error = _set_obj(obj, case["obj_radius"], case["obj_thickness"])
            if error:
                metrics = {
                    "f_number": None,
                    "efl": None,
                    "ttl": None,
                    "bfl": None,
                    "image_semi_diameter": None,
                    "image_surface": None,
                    "number_of_surfaces": None,
                }
                mtf = {"fft_mtf_usable_dataframe": False, "fft_mtf_failure_reason": f"OBJ set failed: {error}"}
            else:
                try:
                    oss.update_status()
                except Exception:
                    pass
                metrics = _system_metrics(oss)
                mtf = _run_lowfreq_mtf(oss, case_dir, case["case_key"])

            for field in FIELDS_DEG:
                if error:
                    trace = {
                        "field_deg": field,
                        "field_number": field_numbers.get(field),
                        "ray_trace_success_count": 0,
                        "ray_trace_failure_count": len(PUPIL_SAMPLES),
                        "failed_pupil_coordinates": "OBJ set failed",
                        "centroid_x": None,
                        "centroid_y": None,
                        "geometric_rms_spot_radius": None,
                        "max_ray_radius_on_image": None,
                        "chief_ray_x": None,
                        "chief_ray_y": None,
                        "chief_ray_angle_deg": None,
                        "raytrace_status": "failed",
                        "raytrace_failure_reason": error,
                    }
                else:
                    trace = _raytrace_field(
                        oss,
                        raw_dir,
                        case_name=case["case_key"],
                        field_deg=field,
                        field_number=field_numbers.get(field),
                        image_surface=int(metrics["image_surface"]),
                    )
                rows.append(
                    {
                        **case,
                        **metrics,
                        **trace,
                        **mtf,
                        "obj_radius": _fmt(case["obj_radius"]),
                        "obj_thickness": _fmt(case["obj_thickness"]),
                        "field_list": ", ".join(_fmt(row.get("y")) for row in fields),
                    }
                )
    finally:
        try:
            obj.Radius = original_radius
            obj.Thickness = original_thickness
            try:
                oss.update_status()
            except Exception:
                pass
            restored = _raw_float(obj.Radius) == original_radius and _raw_float(obj.Thickness) == original_thickness
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
        "allowed_temporary_change": "OBJ Radius and OBJ Thickness only",
        "original_obj_radius": _fmt(original_radius),
        "original_obj_thickness": _fmt(original_thickness),
        "original_obj_restored": restored,
        "fields": fields,
        "diagnostic_fields": list(FIELDS_DEG),
        "pupil_samples": list(PUPIL_SAMPLES),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(run_dir / "object_condition_effects_summary.csv", rows)
    _write_report(run_dir / "object_condition_effects_report.txt", lens=lens, run_id=run_id, rows=rows, restored=restored)

    print(f"run_id: {run_id}", flush=True)
    print(f"output_folder: {run_dir}", flush=True)
    print(f"object_condition_effects_summary: {run_dir / 'object_condition_effects_summary.csv'}", flush=True)
    print(f"object_condition_effects_report: {run_dir / 'object_condition_effects_report.txt'}", flush=True)
    print(f"original_OBJ_restored: {str(restored).lower()}", flush=True)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Temporarily compare current/flat/infinite OBJ conditions using ray trace and low-frequency FFT MTF."
    )
    parser.add_argument("--lens", required=True, type=Path, help="Lens path. The script does not save or modify the file.")
    parser.add_argument("--label", default="object_condition_effects", help="Label used in output run_id.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    diagnose_object_conditions(project_root, args.lens, args.label)


if __name__ == "__main__":
    main()
