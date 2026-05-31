from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from pandas import DataFrame

from diagnose_mtf_field import _run_fft_mtf_dataframe
from diagnose_ray_failure_surfaces import (
    FIELDS_DEG,
    PUPIL_SAMPLES,
    _field_number,
    _field_table,
    _fmt,
    _likely_failure_type,
    _safe_get,
    _surface_table,
    _to_float,
    _trace_one,
)
from zosapi_cleanup import close_all_analysis_windows


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
RAY_AIMING_CASES = ("current", "Off", "Paraxial", "Real")


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_simple_value(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _ray_aiming_object(oss: Any) -> Any | None:
    system_data = _safe_get(oss, "SystemData")
    for attr in ("RayAiming", "RayAimingData", "RayAimingSettings"):
        value = _safe_get(system_data, attr)
        if value is not None:
            return value
    return None


def _public_attrs(obj: Any) -> list[str]:
    try:
        names = dir(obj)
    except Exception:
        return []
    return [name for name in names if not name.startswith("_")]


def _snapshot_ray_aiming(oss: Any) -> dict[str, Any]:
    ray = _ray_aiming_object(oss)
    snapshot: dict[str, Any] = {"object_exists": ray is not None, "values": {}}
    if ray is None:
        return snapshot
    for name in _public_attrs(ray):
        try:
            value = getattr(ray, name)
        except Exception:
            continue
        if callable(value):
            continue
        if _is_simple_value(value) or value.__class__.__module__.startswith(("System", "ZOSAPI")):
            snapshot["values"][name] = value
    return snapshot


def _restore_ray_aiming(oss: Any, snapshot: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    ray = _ray_aiming_object(oss)
    if ray is None:
        if snapshot.get("object_exists"):
            warnings.append("RayAiming object missing during restore.")
        return warnings
    for name, value in snapshot.get("values", {}).items():
        try:
            setattr(ray, name, value)
        except Exception:
            continue
    try:
        oss.update_status()
    except Exception as exc:
        warnings.append(f"update_status after Ray Aiming restore failed: {type(exc).__name__}: {exc!r}")
    return warnings


def _constant_candidates(case: str) -> list[Any]:
    if case == "current":
        return []
    candidates: list[Any] = []
    for path in (
        ("SystemData", "RayAimingMethod", case),
        ("SystemData", "RayAiming", case),
        ("SystemData", "ZemaxRayAimingMethod", case),
        ("SystemData", "RayAimingType", case),
    ):
        try:
            obj: Any = zp.constants
            for attr in path:
                obj = getattr(obj, attr)
            candidates.append(obj)
        except Exception:
            continue
    return candidates


def _set_bool_if_exists(obj: Any, names: tuple[str, ...], value: bool) -> bool:
    changed = False
    for name in names:
        if _safe_get(obj, name, None) is None:
            continue
        try:
            setattr(obj, name, value)
            changed = True
        except Exception:
            continue
    return changed


def _set_method_if_exists(obj: Any, case: str) -> tuple[bool, str | None]:
    if case == "current":
        return True, None
    method_attrs = ("RayAimingMethod", "Method", "Type", "RayAimingType")
    values = _constant_candidates(case) + [case]
    errors: list[str] = []
    for attr in method_attrs:
        if _safe_get(obj, attr, None) is None:
            continue
        for value in values:
            try:
                setattr(obj, attr, value)
                return True, None
            except Exception as exc:
                errors.append(f"{attr}={value!r}: {type(exc).__name__}")
    return False, "; ".join(errors) if errors else "No known Ray Aiming method property exists."


def _apply_ray_aiming_case(oss: Any, case: str) -> tuple[bool, str | None, dict[str, Any]]:
    ray = _ray_aiming_object(oss)
    if ray is None:
        return False, "SystemData RayAiming object was not found.", {}
    before = _snapshot_ray_aiming(oss)
    if case == "current":
        return True, None, before

    if case == "Off":
        bool_changed = _set_bool_if_exists(
            ray,
            ("UseRayAiming", "EnableRayAiming", "Enabled", "RayAiming"),
            False,
        )
        method_changed, method_error = _set_method_if_exists(ray, case)
        if not bool_changed and not method_changed:
            return False, method_error or "Could not disable Ray Aiming.", before
    else:
        _set_bool_if_exists(ray, ("UseRayAiming", "EnableRayAiming", "Enabled", "RayAiming"), True)
        method_changed, method_error = _set_method_if_exists(ray, case)
        if not method_changed:
            return False, method_error, before

    try:
        oss.update_status()
    except Exception as exc:
        return False, f"update_status failed after Ray Aiming={case}: {type(exc).__name__}: {exc!r}", before
    return True, None, _snapshot_ray_aiming(oss)


def _snapshot_text(snapshot: dict[str, Any]) -> str:
    values = snapshot.get("values", {})
    parts = []
    for key in sorted(values):
        value = values[key]
        try:
            parts.append(f"{key}={value}")
        except Exception:
            parts.append(f"{key}=<unprintable>")
    return "; ".join(parts) if parts else "unknown"


def _run_lowfreq_mtf(oss: Any) -> tuple[bool, str | None]:
    try:
        data, warnings = _run_fft_mtf_dataframe(oss, 30.0)
        close_all_analysis_windows(oss)
        if data is None or not isinstance(data, DataFrame) or data.empty:
            return False, "FFT MTF returned no usable DataFrame."
        if warnings:
            return True, " | ".join(warnings)
        return True, None
    except Exception as exc:
        close_all_analysis_windows(oss)
        return False, f"{type(exc).__name__}: {exc!r}"


def _count_surfaces(rows: list[dict[str, Any]]) -> Counter[int]:
    counter: Counter[int] = Counter()
    for row in rows:
        if str(row.get("status") or "").startswith("success"):
            continue
        surface = row.get("failed_surface")
        try:
            counter[int(surface)] += 1
        except (TypeError, ValueError):
            continue
    return counter


def _case_field_status(rows: list[dict[str, Any]]) -> str:
    failed = sum(1 for row in rows if row.get("status") == "failed")
    partial = sum(1 for row in rows if row.get("status") == "success_with_wrapper_warning")
    if failed == 0 and partial == 0:
        return "success"
    if failed < len(rows):
        return "partial"
    return "failed"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case",
        "requested_ray_aiming",
        "actual_ray_aiming_after_set",
        "setup_status",
        "setup_error",
        "ray_aiming_snapshot",
        "field_deg",
        "field_status",
        "ray_success_count",
        "ray_failure_count",
        "failed_surfaces",
        "failure_surface_counts",
        "s4_failures",
        "s6_failures",
        "s7_s8_failures",
        "stop_failures",
        "fft_mtf_usable_dataframe",
        "fft_mtf_note",
        "case_setup_status",
        "case_setup_error",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summarize_case(case: str, rows: list[dict[str, Any]], surfaces: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    by_field: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_field[float(row["field_deg"])].append(row)

    stop_surfaces = {surface for surface, info in surfaces.items() if info.get("is_stop")}
    for field in FIELDS_DEG:
        group = by_field.get(field, [])
        counter = _count_surfaces(group)
        failed_surfaces = "; ".join(f"S{surface}:{count}" for surface, count in sorted(counter.items()))
        summary_rows.append(
            {
                "case": case,
                "requested_ray_aiming": case,
                "field_deg": field,
                "field_status": _case_field_status(group) if group else "failed",
                "ray_success_count": sum(1 for row in group if row.get("status") != "failed"),
                "ray_failure_count": sum(1 for row in group if row.get("status") == "failed"),
                "failed_surfaces": failed_surfaces,
                "failure_surface_counts": failed_surfaces,
                "s4_failures": counter.get(4, 0),
                "s6_failures": counter.get(6, 0),
                "s7_s8_failures": counter.get(7, 0) + counter.get(8, 0),
                "stop_failures": sum(counter.get(surface, 0) for surface in stop_surfaces),
            }
        )
    return summary_rows


def _invalid_case_summary(
    case: str,
    *,
    actual_ray_aiming: str,
    setup_error: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in FIELDS_DEG:
        rows.append(
            {
                "case": case,
                "requested_ray_aiming": case,
                "actual_ray_aiming_after_set": actual_ray_aiming,
                "ray_aiming_snapshot": actual_ray_aiming,
                "field_deg": field,
                "field_status": "invalid",
                "ray_success_count": 0,
                "ray_failure_count": 0,
                "failed_surfaces": "",
                "failure_surface_counts": "",
                "s4_failures": 0,
                "s6_failures": 0,
                "s7_s8_failures": 0,
                "stop_failures": 0,
                "fft_mtf_usable_dataframe": False,
                "fft_mtf_note": "Ray Aiming case setup failed; trace/MTF not run.",
                "setup_status": "invalid",
                "setup_error": setup_error,
                "case_setup_status": "invalid",
                "case_setup_error": setup_error,
            }
        )
    return rows


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    summary_rows: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
    restore_warnings: list[str],
) -> None:
    lines = [
        "Ray Aiming Effect On High Fields Diagnostic",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        "allowed_temporary_change: Ray Aiming only",
        "",
        "[case_summary]",
    ]
    for case in RAY_AIMING_CASES:
        case_rows = [row for row in summary_rows if row.get("case") == case]
        if not case_rows:
            lines.append(f"  {case}: no rows")
            continue
        total_failures = sum(int(row.get("ray_failure_count") or 0) for row in case_rows)
        high_failures = sum(
            int(row.get("ray_failure_count") or 0)
            for row in case_rows
            if _to_float(row.get("field_deg")) in {49.0, 63.0, 70.0}
        )
        mtf = case_rows[0].get("fft_mtf_usable_dataframe")
        setup_status = case_rows[0].get("setup_status") or case_rows[0].get("case_setup_status")
        setup_error = case_rows[0].get("setup_error") or case_rows[0].get("case_setup_error")
        requested = case_rows[0].get("requested_ray_aiming")
        actual = case_rows[0].get("actual_ray_aiming_after_set") or case_rows[0].get("ray_aiming_snapshot")
        lines.append(
            f"  {case}: requested_ray_aiming={requested}, setup={setup_status}, "
            f"total_ray_failures={total_failures}, high_field_failures={high_failures}, "
            f"FFT_MTF_usable={mtf}"
            + (f", setup_error={setup_error}" if setup_error else "")
        )
        lines.append(f"    actual_ray_aiming_after_set: {actual}")
        for row in case_rows:
            lines.append(
                "    "
                f"field={_fmt(row.get('field_deg'))}: status={row.get('field_status')}, "
                f"success={row.get('ray_success_count')}, failed={row.get('ray_failure_count')}, "
                f"failure_surface_counts={row.get('failure_surface_counts') or row.get('failed_surfaces') or 'none'}"
            )

    lines.extend(["", "[high_field_improvement]"])
    current_high = sum(
        int(row.get("ray_failure_count") or 0)
        for row in summary_rows
        if row.get("case") == "current"
        and (row.get("setup_status") or row.get("case_setup_status")) == "success"
        and _to_float(row.get("field_deg")) in {63.0, 70.0}
    )
    for case in ("Off", "Paraxial", "Real"):
        case_rows = [row for row in summary_rows if row.get("case") == case]
        case_setup = case_rows[0].get("setup_status") if case_rows else "invalid"
        if case_setup != "success":
            lines.append(f"  {case}: skipped, setup_status={case_setup}; not included in comparison")
            continue
        high = sum(
            int(row.get("ray_failure_count") or 0)
            for row in summary_rows
            if row.get("case") == case
            and (row.get("setup_status") or row.get("case_setup_status")) == "success"
            and _to_float(row.get("field_deg")) in {63.0, 70.0}
        )
        if current_high == 0:
            verdict = "current already has no 63/70 sampled failures"
        elif high < current_high:
            verdict = "improved"
        elif high == current_high:
            verdict = "no clear change"
        else:
            verdict = "worse"
        lines.append(f"  {case}: 63/70 failures={high}, current={current_high}, verdict={verdict}")

    lines.extend(["", "[surface_focus]"])
    for surface, label in ((4, "S4"), (6, "S6"), (7, "S7"), (8, "S8")):
        hits = [
            row
            for row in detail_rows
            if row.get("status") == "failed" and str(row.get("failed_surface")) == str(surface)
        ]
        lines.append(f"  {label}: failures={len(hits)}")

    lines.extend(["", "[interpretation]"])
    lines.append("If Off/Paraxial/Real reduces 63/70 failures without increasing lower-field failures, Ray Aiming is part of the problem.")
    lines.append("If all modes fail on the same early surfaces, the issue is more likely clear aperture / geometry than ray aiming.")
    lines.append("If failures move between surfaces by mode, inspect entrance pupil and stop setup before modifying lens geometry.")
    if restore_warnings:
        lines.append("restore_warnings: " + " | ".join(restore_warnings))
    else:
        lines.append("restore_warnings: none")
    lines.extend(
        [
            "",
            "[files]",
            f"ray_aiming_effect_summary: {path.parent / 'ray_aiming_effect_summary.csv'}",
            f"ray_aiming_effect_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_ray_aiming_effect(lens_path: str) -> None:
    lens = Path(lens_path)
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "ray_aiming_effects" / run_id
    raw_dir = out_dir / "raw_single_ray_traces"
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

    print("Loading lens read-only...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    image_surface = int(lde.NumberOfSurfaces) - 1
    surfaces = _surface_table(oss)
    fields = _field_table(oss)
    field_numbers = {field: _field_number(fields, field) for field in FIELDS_DEG}
    original_ray_aiming = _snapshot_ray_aiming(oss)
    restore_warnings: list[str] = []
    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    try:
        for case in RAY_AIMING_CASES:
            print(f"Testing Ray Aiming case: {case}", flush=True)
            if case == "current":
                setup_ok = True
                setup_error = None
                snapshot = _snapshot_ray_aiming(oss)
            else:
                setup_ok, setup_error, snapshot = _apply_ray_aiming_case(oss, case)

            case_detail_rows: list[dict[str, Any]] = []
            actual_ray_aiming = _snapshot_text(snapshot)
            if not setup_ok:
                # Do not run ray trace or FFT MTF when the requested Ray Aiming
                # state could not be applied. Treat the case as invalid so it
                # cannot contaminate high-field improvement comparisons.
                case_summary = _invalid_case_summary(
                    case,
                    actual_ray_aiming=actual_ray_aiming,
                    setup_error=setup_error,
                )
                summary_rows.extend(case_summary)
                close_all_analysis_windows(oss)
                continue

            fft_ok, fft_note = _run_lowfreq_mtf(oss)

            for field in FIELDS_DEG:
                field_number = field_numbers[field]
                for px, py in PUPIL_SAMPLES:
                    if field_number is None:
                        row = {
                            "case": case,
                            "field_deg": field,
                            "field_number": None,
                            "px": px,
                            "py": py,
                            "status": "failed",
                            "failed_surface": None,
                            "failure_reason": "Requested field is not present in current lens field table.",
                        }
                        text = ""
                    else:
                        raw_path = raw_dir / f"{case}_field_{field:g}_px_{px:g}_py_{py:g}.txt".replace(".", "p")
                        row, text = _trace_one(
                            oss,
                            field_number=field_number,
                            field_deg=field,
                            px=px,
                            py=py,
                            image_surface=image_surface,
                            raw_path=raw_path,
                        )
                        row["case"] = case
                    failed_surface = row.get("failed_surface")
                    info = surfaces.get(int(failed_surface), {}) if failed_surface is not None else {}
                    row["failed_surface_comment"] = info.get("comment")
                    row["failed_surface_glass"] = info.get("glass")
                    row["likely_failure_type"] = _likely_failure_type(text or str(row.get("failure_reason")), failed_surface, info)
                    case_detail_rows.append(row)

            case_summary = _summarize_case(case, case_detail_rows, surfaces)
            for row in case_summary:
                row["requested_ray_aiming"] = case
                row["actual_ray_aiming_after_set"] = actual_ray_aiming
                row["ray_aiming_snapshot"] = actual_ray_aiming
                row["fft_mtf_usable_dataframe"] = fft_ok
                row["fft_mtf_note"] = fft_note
                row["setup_status"] = "success"
                row["setup_error"] = setup_error
                row["case_setup_status"] = "success"
                row["case_setup_error"] = setup_error
            detail_rows.extend(case_detail_rows)
            summary_rows.extend(case_summary)
            close_all_analysis_windows(oss)
    finally:
        restore_warnings.extend(_restore_ray_aiming(oss, original_ray_aiming))
        close_all_analysis_windows(oss)

    summary_path = out_dir / "ray_aiming_effect_summary.csv"
    report_path = out_dir / "ray_aiming_effect_report.txt"
    detail_path = out_dir / "ray_aiming_effect_detail.csv"
    _write_csv(summary_path, summary_rows)
    with detail_path.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "case",
            "field_deg",
            "field_number",
            "px",
            "py",
            "status",
            "failed_surface",
            "failed_surface_comment",
            "failed_surface_glass",
            "likely_failure_type",
            "failure_reason",
            "last_success_surface",
            "last_success_x",
            "last_success_y",
            "raw_trace_file",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(detail_rows)
    _write_report(
        report_path,
        lens=lens,
        run_id=run_id,
        summary_rows=summary_rows,
        detail_rows=detail_rows,
        restore_warnings=restore_warnings,
    )
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "lens": str(lens),
                "output_folder": str(out_dir),
                "read_only": True,
                "saved_lens": False,
                "optimized": False,
                "allowed_temporary_change": "Ray Aiming only",
                "original_ray_aiming": _snapshot_text(original_ray_aiming),
                "restore_warnings": restore_warnings,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"ray_aiming_effect_summary: {summary_path}", flush=True)
    print(f"ray_aiming_effect_report: {report_path}", flush=True)
    print(f"ray_aiming_effect_detail: {detail_path}", flush=True)
    for case in RAY_AIMING_CASES:
        high_failures = sum(
            int(row.get("ray_failure_count") or 0)
            for row in summary_rows
            if row.get("case") == case
            and (row.get("setup_status") or row.get("case_setup_status")) == "success"
            and _to_float(row.get("field_deg")) in {63.0, 70.0}
        )
        setup_rows = [row for row in summary_rows if row.get("case") == case]
        setup_status = setup_rows[0].get("setup_status") if setup_rows else "missing"
        print(f"{case}: setup_status={setup_status}, high_field_63_70_failures={high_failures}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Temporarily compare Ray Aiming settings on high-field ray failures.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script does not save or modify it.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_ray_aiming_effect(args.lens)
