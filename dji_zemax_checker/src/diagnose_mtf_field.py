from __future__ import annotations

import argparse
import csv
import json
import math
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from pandas import DataFrame
from zospy.analyses.base import OnComplete
from zospy.analyses.mtf import FFTMTF

from export_chatgpt_summary import _interpolate, _is_real_mtf_curve, _read_mtf
from export_surfaces import safe_get
from scan_radius import _safe_label
from zosapi_cleanup import close_all_analysis_windows


SUMMARY_FREQS = (20.0, 30.0, 40.0, 50.0)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.6g}"
    return "null" if value is None else str(value)


def _unique_run_dir(project_root: Path, label: str) -> tuple[str, Path]:
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    root = project_root / "results" / "diagnostics"
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


def _field_type_angle_constant() -> Any | None:
    for path in (
        ("SystemData", "FieldType", "Angle"),
        ("SystemData", "FieldType", "AngleDegrees"),
    ):
        try:
            obj: Any = zp.constants
            for attr in path:
                obj = getattr(obj, attr)
            return obj
        except Exception:
            continue
    return None


def _snapshot_fields(oss: Any) -> dict[str, Any]:
    fields = safe_get(oss.SystemData, "Fields")
    rows: list[dict[str, Any]] = []
    count = int(safe_get(fields, "NumberOfFields", 0) or 0)
    for index in range(1, count + 1):
        field = fields.GetField(index)
        rows.append(
            {
                "x": safe_get(field, "X"),
                "y": safe_get(field, "Y"),
                "weight": safe_get(field, "Weight", 1.0),
            }
        )
    try:
        field_type = fields.GetFieldType()
    except Exception:
        field_type = None
    return {"field_type": field_type, "fields": rows}


def _set_requested_fields(oss: Any, field_degrees: list[float]) -> list[str]:
    warnings: list[str] = []
    fields = safe_get(oss.SystemData, "Fields")
    if fields is None:
        return ["Could not access SystemData.Fields; using lens-defined fields."]

    try:
        angle_type = _field_type_angle_constant()
        if angle_type is not None:
            fields.SetFieldType(angle_type)
    except Exception as exc:
        warnings.append(f"Could not force field type to Angle: {type(exc).__name__}: {exc!r}")

    try:
        fields.DeleteAllFields()
        for value in field_degrees:
            fields.AddField(0.0, value, 1.0)
        oss.update_status()
    except Exception as exc:
        warnings.append(f"Could not replace fields with requested diagnostic fields: {type(exc).__name__}: {exc!r}")
    return warnings


def _restore_fields(oss: Any, snapshot: dict[str, Any]) -> None:
    fields = safe_get(oss.SystemData, "Fields")
    if fields is None:
        return
    try:
        field_type = snapshot.get("field_type")
        if field_type is not None:
            fields.SetFieldType(field_type)
        fields.DeleteAllFields()
        for row in snapshot.get("fields", []):
            fields.AddField(float(row.get("x") or 0.0), float(row.get("y") or 0.0), float(row.get("weight") or 1.0))
    except Exception:
        pass


def _run_fft_mtf_dataframe(oss: Any, maximum_frequency: float) -> tuple[DataFrame | None, list[str]]:
    warnings: list[str] = []
    try:
        result = FFTMTF(
            sampling="32x32",
            surface="Image",
            wavelength="All",
            field="All",
            maximum_frequency=maximum_frequency,
            use_polarization=False,
            use_dashes=False,
            show_diffraction_limit=False,
        ).run(oss)
        data = result.data
        close_all_analysis_windows(oss)
        return data, warnings
    except AttributeError as exc:
        close_all_analysis_windows(oss)
        if "metadata" not in str(exc):
            return None, [f"FFTMTF failed: {type(exc).__name__}: {exc!r}"]
        warnings.append(f"FFTMTF metadata access failed; using data-only fallback: {type(exc).__name__}: {exc!r}")
    except Exception as exc:
        close_all_analysis_windows(oss)
        return None, [f"FFTMTF failed: {type(exc).__name__}: {exc!r}"]

    analysis = FFTMTF(
        sampling="32x32",
        surface="Image",
        wavelength="All",
        field="All",
        maximum_frequency=maximum_frequency,
        use_polarization=False,
        use_dashes=False,
        show_diffraction_limit=False,
    )
    try:
        analysis._oss = weakref.proxy(oss)
        analysis._check_mode()
        analysis._create_analysis()
        return analysis.run_analysis(), warnings
    except Exception as exc:
        warnings.append(f"FFTMTF data-only fallback failed: {type(exc).__name__}: {exc!r}")
        return None, warnings
    finally:
        try:
            analysis._complete(OnComplete.Close)
        except Exception:
            pass
        close_all_analysis_windows(oss)


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
    return min(candidates, key=lambda item: abs(float(item["field"]) - field))


def _curve_value(frequencies: list[float], item: dict[str, Any] | None, target: float) -> float | None:
    if item is None:
        return None
    return _interpolate(frequencies, item["values"], target)


def _zero_crossing_estimate(points: list[tuple[float, float | None]]) -> str:
    valid = [(freq, value) for freq, value in points if value is not None]
    if not valid:
        return "unknown"
    if any(value <= 1e-6 for freq, value in valid if 20.0 <= freq <= 50.0):
        near = [freq for freq, value in valid if value <= 1e-6 and 20.0 <= freq <= 50.0]
        return f"near {near[0]:g} lp/mm"
    minimum = min((value, freq) for freq, value in valid if 20.0 <= freq <= 50.0)
    if minimum[0] < 0.005:
        return f"near-zero minimum at {minimum[1]:g} lp/mm"
    return "not observed"


def _write_curves(
    path: Path,
    curve_rows: list[dict[str, Any]],
) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["field_deg", "frequency_lpmm", "tangential_mtf", "sagittal_mtf"],
        )
        writer.writeheader()
        writer.writerows(curve_rows)


def _summary_rows(
    requested_fields: list[float],
    frequencies: list[float],
    series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in requested_fields:
        t_series = _nearest_series(series, field, "T")
        s_series = _nearest_series(series, field, "S")
        row: dict[str, Any] = {"field_deg": field}
        t_points = []
        s_points = []
        for freq in SUMMARY_FREQS:
            t_value = _curve_value(frequencies, t_series, freq)
            s_value = _curve_value(frequencies, s_series, freq)
            row[f"T{int(freq)}"] = t_value
            row[f"S{int(freq)}"] = s_value
            if 20.0 <= freq <= 50.0:
                t_points.append((freq, t_value))
                s_points.append((freq, s_value))
        row["T_min_20_50"] = min((value for _, value in t_points if value is not None), default=None)
        row["S_min_20_50"] = min((value for _, value in s_points if value is not None), default=None)
        row["T_zero_crossing_estimated"] = _zero_crossing_estimate(t_points)
        row["S_zero_crossing_estimated"] = _zero_crossing_estimate(s_points)
        rows.append(row)
    return rows


def _field_result_rows(
    field: float,
    output_frequencies: list[float],
    frequencies: list[float],
    series: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    t_series = _nearest_series(series, field, "T")
    s_series = _nearest_series(series, field, "S")
    curve_rows: list[dict[str, Any]] = []
    for freq in output_frequencies:
        curve_rows.append(
            {
                "field_deg": field,
                "frequency_lpmm": freq,
                "tangential_mtf": _curve_value(frequencies, t_series, freq),
                "sagittal_mtf": _curve_value(frequencies, s_series, freq),
            }
        )

    summary = _summary_rows([field], frequencies, series)[0]
    summary["status"] = "success"
    summary["failure_reason"] = None
    return curve_rows, summary


def _failed_summary_row(field: float, failure_reason: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "field_deg": field,
        "status": "failed",
        "failure_reason": failure_reason,
        "T_min_20_50": None,
        "S_min_20_50": None,
        "T_zero_crossing_estimated": "unknown",
        "S_zero_crossing_estimated": "unknown",
    }
    for freq in SUMMARY_FREQS:
        row[f"T{int(freq)}"] = None
        row[f"S{int(freq)}"] = None
    return row


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "field_deg",
        "status",
        "failure_reason",
        "T20",
        "T30",
        "T40",
        "T50",
        "S20",
        "S30",
        "S40",
        "S50",
        "T_min_20_50",
        "S_min_20_50",
        "T_zero_crossing_estimated",
        "S_zero_crossing_estimated",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _has_zero_crossing(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text not in {"", "unknown", "not observed"}


def _field_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: float(row["field_deg"]))


def _collapse_flags(rows: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for row in _field_rows(rows):
        field = float(row["field_deg"])
        t_min = _to_float(row.get("T_min_20_50"))
        s_min = _to_float(row.get("S_min_20_50"))
        if field >= 60.0 and t_min is not None and t_min < 0.01:
            flags.append(f"high_field_tangential_low: field={field:g} T_min_20_50={t_min:.6g}")
        if field >= 60.0 and s_min is not None and s_min < 0.01:
            flags.append(f"high_field_sagittal_low: field={field:g} S_min_20_50={s_min:.6g}")
        if _has_zero_crossing(row.get("T_zero_crossing_estimated")):
            flags.append(f"zero_crossing: field={field:g} orientation=T {row.get('T_zero_crossing_estimated')}")
        if _has_zero_crossing(row.get("S_zero_crossing_estimated")):
            flags.append(f"zero_crossing: field={field:g} orientation=S {row.get('S_zero_crossing_estimated')}")

    by_field = {float(row["field_deg"]): row for row in rows}
    if 60.0 in by_field and 70.0 in by_field:
        for orientation in ("T", "S"):
            key = f"{orientation}_min_20_50"
            v60 = _to_float(by_field[60.0].get(key))
            v70 = _to_float(by_field[70.0].get(key))
            if v60 is not None and v70 is not None and v60 > 0.02 and v70 < max(0.01, 0.35 * v60):
                flags.append(
                    f"60_to_70_collapse: orientation={orientation} field60={v60:.6g} field70={v70:.6g}"
                )
    return flags


def _summary_text(rows: list[dict[str, Any]], warnings: list[str]) -> list[str]:
    successful_fields = [float(row["field_deg"]) for row in rows if row.get("status") == "success"]
    failed_rows = [row for row in rows if row.get("status") == "failed"]
    failed_fields = [float(row["field_deg"]) for row in failed_rows]
    first_failed_field = failed_fields[0] if failed_fields else None
    failure_reason_by_field = {
        f"{float(row['field_deg']):g}": str(row.get("failure_reason") or "unknown") for row in failed_rows
    }
    lines = [
        "diagnosis_target: all requested half-fields",
        "successful_fields: " + (", ".join(f"{field:g}" for field in successful_fields) if successful_fields else "none"),
        "failed_fields: " + (", ".join(f"{field:g}" for field in failed_fields) if failed_fields else "none"),
        f"first_failed_field: {_fmt(first_failed_field)}",
        "failure_reason_by_field: " + (json.dumps(failure_reason_by_field, ensure_ascii=False) if failure_reason_by_field else "none"),
        "all_fields_summary:",
    ]
    for row in _field_rows(rows):
        field = float(row["field_deg"])
        if row.get("status") == "failed":
            lines.append(
                "  "
                f"field={field:g}: status=failed, failure_reason={row.get('failure_reason')}, "
                "T_min_20_50=null, S_min_20_50=null, T_zero=unknown, S_zero=unknown"
            )
            continue
        lines.append(
            "  "
            f"field={field:g}: "
            f"T_min_20_50={_fmt(row.get('T_min_20_50'))}, "
            f"S_min_20_50={_fmt(row.get('S_min_20_50'))}, "
            f"T20={_fmt(row.get('T20'))}, T30={_fmt(row.get('T30'))}, "
            f"T40={_fmt(row.get('T40'))}, T50={_fmt(row.get('T50'))}, "
            f"S20={_fmt(row.get('S20'))}, S30={_fmt(row.get('S30'))}, "
            f"S40={_fmt(row.get('S40'))}, S50={_fmt(row.get('S50'))}, "
            f"T_zero={row.get('T_zero_crossing_estimated', 'unknown')}, "
            f"S_zero={row.get('S_zero_crossing_estimated', 'unknown')}"
        )

    flags = _collapse_flags(rows)
    lines.append("automatic_flags:")
    if flags:
        lines.extend(f"  {flag}" for flag in flags)
    else:
        lines.append("  none")

    if any(field >= 60.0 for field in failed_fields) and any(field <= 50.0 for field in successful_fields):
        lines.append(
            "high_field_failure_note: The lens or MTF analysis failed at high field angles; this may indicate "
            "ray tracing/vignetting/field setup failure rather than a valid low MTF value."
        )

    t_values = [(float(row["field_deg"]), _to_float(row.get("T_min_20_50"))) for row in rows]
    t_valid = [(field, value) for field, value in t_values if value is not None]
    if t_valid:
        values = [value for _, value in t_valid]
        spread = max(values) - min(values)
        if spread > 0.05:
            lines.append(f"field_transition: Tangential MTF changes abruptly across requested fields; min spread={_fmt(spread)}.")
        else:
            lines.append(f"field_transition: Tangential MTF changes smoothly across requested fields; min spread={_fmt(spread)}.")

    if warnings:
        lines.append("warnings: " + " | ".join(warnings))
    else:
        lines.append("warnings: none")
    return lines


def diagnose_mtf_field(
    project_root: Path,
    lens: Path,
    fields: list[float],
    freq_start: float,
    freq_end: float,
    freq_step: float,
    label: str,
) -> Path:
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")
    if freq_step <= 0:
        raise ValueError("--freq-step must be positive.")

    run_id, run_dir = _unique_run_dir(project_root, label)
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    curve_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    snapshot: dict[str, Any] | None = None
    try:
        oss.load(lens, saveifneeded=False)
        snapshot = _snapshot_fields(oss)
        output_frequencies: list[float] = []
        current = freq_start
        while current <= freq_end + 1e-9:
            output_frequencies.append(round(current, 10))
            current += freq_step

        for field in fields:
            try:
                warnings.extend(_set_requested_fields(oss, [field]))
                data, mtf_warnings = _run_fft_mtf_dataframe(oss, freq_end)
                warnings.extend(mtf_warnings)
                if data is None or not isinstance(data, DataFrame) or data.empty:
                    raise RuntimeError("FFT MTF returned no usable DataFrame.")

                raw_csv = run_dir / f"mtf_raw_fft_field_{field:g}.csv".replace(".", "p")
                data.to_csv(raw_csv, index=True, encoding="utf-8-sig")
                frequencies, series = _read_mtf(raw_csv)
                if not frequencies or not series:
                    raise RuntimeError("Could not parse FFT MTF curves from raw CSV.")

                field_curve_rows, field_summary = _field_result_rows(field, output_frequencies, frequencies, series)
                curve_rows.extend(field_curve_rows)
                summary_rows.append(field_summary)
            except Exception as exc:
                failure_reason = f"{type(exc).__name__}: {exc!r}"
                warnings.append(f"Field {field:g} failed: {failure_reason}")
                summary_rows.append(_failed_summary_row(field, failure_reason))

        _write_curves(run_dir / "mtf_field_curves.csv", curve_rows)
        _write_summary_csv(run_dir / "mtf_field_summary.csv", summary_rows)

        metadata = {
            "run_id": run_id,
            "label": label,
            "lens": str(lens),
            "fields": fields,
            "freq_start": freq_start,
            "freq_end": freq_end,
            "freq_step": freq_step,
            "output_folder": str(run_dir),
            "successful_fields": [row["field_deg"] for row in summary_rows if row.get("status") == "success"],
            "failed_fields": [row["field_deg"] for row in summary_rows if row.get("status") == "failed"],
            "warnings": warnings,
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

        lines = [
            f"run_id: {run_id}",
            f"lens: {lens}",
            f"output_folder: {run_dir}",
            "",
            "[summary]",
            *_summary_text(summary_rows, warnings),
            "",
            "[files]",
            f"metadata: {run_dir / 'metadata.json'}",
            f"mtf_field_curves: {run_dir / 'mtf_field_curves.csv'}",
            f"mtf_field_summary: {run_dir / 'mtf_field_summary.csv'}",
        ]
        (run_dir / "diagnose_summary_for_chatgpt.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"diagnostic_run_id: {run_id}", flush=True)
        print(f"diagnostic_output_folder: {run_dir}", flush=True)
        print(f"diagnostic_summary: {run_dir / 'diagnose_summary_for_chatgpt.txt'}", flush=True)
        return run_dir
    finally:
        if snapshot is not None:
            _restore_fields(oss, snapshot)
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
        except Exception as exc:
            print(f"[WARNING] Failed to restore original file: {repr(exc)}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose full FFT MTF curves for selected field angles.")
    parser.add_argument("--lens", required=True, type=Path, help="Lens file to load for diagnosis.")
    parser.add_argument("--fields", nargs="+", required=True, type=float, help="Field angles in degrees to diagnose.")
    parser.add_argument("--freq-start", type=float, default=0.0, help="Start frequency in lp/mm for output curve.")
    parser.add_argument("--freq-end", type=float, default=80.0, help="End frequency in lp/mm for FFT MTF and output curve.")
    parser.add_argument("--freq-step", type=float, default=1.0, help="Output frequency step in lp/mm.")
    parser.add_argument("--label", default="diagnose_mtf_field", help="Label used in diagnostic run_id.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_mtf_field(
        Path(__file__).resolve().parents[1],
        lens=args.lens,
        fields=list(args.fields),
        freq_start=args.freq_start,
        freq_end=args.freq_end,
        freq_step=args.freq_step,
        label=args.label,
    )
