from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from pandas import DataFrame

from diagnose_mtf_field import (
    _failed_summary_row,
    _field_result_rows,
    _restore_fields,
    _run_fft_mtf_dataframe,
    _set_requested_fields,
    _snapshot_fields,
)
from export_chatgpt_summary import _read_mtf
from export_surfaces import safe_get
from scan_radius import _safe_label


FIELDNAMES = [
    "field_deg",
    "status",
    "failure_reason",
    "T_min_20_50",
    "S_min_20_50",
    "T20",
    "T30",
    "T40",
    "T50",
    "S20",
    "S30",
    "S40",
    "S50",
    "T_zero_crossing_estimated",
    "S_zero_crossing_estimated",
]


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
    root = project_root / "results" / "field_expansion"
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _status_at(rows: list[dict[str, Any]], field: float) -> str:
    for row in rows:
        if abs(float(row["field_deg"]) - field) < 1e-9:
            if row.get("status") == "failed":
                return f"failed: {row.get('failure_reason') or 'unknown'}"
            return (
                "success: "
                f"T_min_20_50={_fmt(row.get('T_min_20_50'))}, "
                f"S_min_20_50={_fmt(row.get('S_min_20_50'))}"
            )
    return "not requested"


def _has_zero_crossing(row: dict[str, Any]) -> bool:
    for key in ("T_zero_crossing_estimated", "S_zero_crossing_estimated"):
        text = str(row.get(key) or "").strip().lower()
        if text not in {"", "unknown", "not observed"}:
            return True
    return False


def _recommendation(rows: list[dict[str, Any]], first_failed: float | None, last_success: float | None) -> str:
    low_field_zero = [
        row
        for row in rows
        if row.get("status") == "success"
        and float(row["field_deg"]) <= 50
        and (
            (_to_float(row.get("T_min_20_50")) is not None and _to_float(row.get("T_min_20_50")) < 0.005)
            or (_to_float(row.get("S_min_20_50")) is not None and _to_float(row.get("S_min_20_50")) < 0.005)
            or _has_zero_crossing(row)
        )
    ]
    if first_failed is not None and first_failed <= 50:
        return (
            "建议切换或重建超广角初始结构。当前结构在 50° 以内已经出现分析失败，"
            "这通常不是小范围微调能稳定解决的问题。"
        )
    if low_field_zero:
        return (
            "建议先不要继续扩大视场，优先处理 50° 以内的 MTF 近零/过零问题；"
            "当前结构可继续微调，但不宜直接推进到 70°。"
        )
    if first_failed is not None and first_failed >= 60 and (last_success or 0) >= 50:
        return (
            "0~50° 基本可诊断成功，但高视场开始失败。可以继续微调当前结构验证 55~60°，"
            "若目标确实接近 70°，后续可能需要切换更典型的超广角初始结构。"
        )
    if first_failed is None:
        return "所有请求视场均完成 MTF 诊断。可以继续在当前结构上做像质和制造约束细化。"
    return "当前结果处于过渡状态，建议围绕首次失败视场前后加密检查。"


def _write_report(path: Path, lens: Path, rows: list[dict[str, Any]], warnings: list[str]) -> None:
    successful = [float(row["field_deg"]) for row in rows if row.get("status") == "success"]
    failed = [float(row["field_deg"]) for row in rows if row.get("status") == "failed"]
    last_success = max(successful) if successful else None
    first_failed = min(failed) if failed else None
    failed_40_50 = any(40.0 <= field <= 50.0 for field in failed)
    recommendation = _recommendation(rows, first_failed, last_success)

    lines = [
        "field_expansion_report",
        f"lens: {lens}",
        f"last_successful_field: {_fmt(last_success)}",
        f"first_failed_field: {_fmt(first_failed)}",
        f"failure_started_between_40_50: {str(failed_40_50).lower()}",
        f"field_50_status: {_status_at(rows, 50.0)}",
        f"field_60_status: {_status_at(rows, 60.0)}",
        f"field_70_status: {_status_at(rows, 70.0)}",
        "",
        "[field_rows]",
    ]
    for row in rows:
        lines.append(
            f"field={_fmt(row.get('field_deg'))}: "
            f"status={row.get('status')}, "
            f"T_min_20_50={_fmt(row.get('T_min_20_50'))}, "
            f"S_min_20_50={_fmt(row.get('S_min_20_50'))}, "
            f"T20={_fmt(row.get('T20'))}, T30={_fmt(row.get('T30'))}, "
            f"T40={_fmt(row.get('T40'))}, T50={_fmt(row.get('T50'))}, "
            f"S20={_fmt(row.get('S20'))}, S30={_fmt(row.get('S30'))}, "
            f"S40={_fmt(row.get('S40'))}, S50={_fmt(row.get('S50'))}, "
            f"T_zero={row.get('T_zero_crossing_estimated')}, "
            f"S_zero={row.get('S_zero_crossing_estimated')}, "
            f"failure_reason={row.get('failure_reason') or 'none'}"
        )

    lines.extend(
        [
            "",
            "[decision]",
            recommendation,
            "",
            "[warnings]",
            " | ".join(warnings) if warnings else "none",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def field_expansion_check(
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
    summary_rows: list[dict[str, Any]] = []

    output_frequencies: list[float] = []
    current = freq_start
    while current <= freq_end + 1e-9:
        output_frequencies.append(round(current, 10))
        current += freq_step

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    snapshot: dict[str, Any] | None = None
    try:
        oss.load(lens, saveifneeded=False)
        snapshot = _snapshot_fields(oss)
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

                _, summary = _field_result_rows(field, output_frequencies, frequencies, series)
                summary_rows.append(summary)
                print(f"field {field:g}: success", flush=True)
            except Exception as exc:
                failure_reason = f"{type(exc).__name__}: {exc!r}"
                warnings.append(f"Field {field:g} failed: {failure_reason}")
                summary_rows.append(_failed_summary_row(field, failure_reason))
                print(f"field {field:g}: failed: {failure_reason}", flush=True)
    finally:
        if snapshot is not None:
            _restore_fields(oss, snapshot)
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
        except Exception as exc:
            print(f"[WARNING] Failed to restore original file: {repr(exc)}", flush=True)

    summary_rows = sorted(summary_rows, key=lambda row: float(row["field_deg"]))
    summary_path = run_dir / "field_expansion_summary.csv"
    report_path = run_dir / "field_expansion_report.txt"
    _write_csv(summary_path, summary_rows)
    _write_report(report_path, lens, summary_rows, warnings)

    print(f"field_expansion_run_id: {run_id}", flush=True)
    print(f"field_expansion_output_folder: {run_dir}", flush=True)
    print(f"field_expansion_summary: {summary_path}", flush=True)
    print(f"field_expansion_report: {report_path}", flush=True)
    return run_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find the half-field angle where FFT MTF diagnosis starts failing.")
    parser.add_argument("--lens", required=True, type=Path, help="Lens file to load for field expansion diagnosis.")
    parser.add_argument("--fields", nargs="+", required=True, type=float, help="Half-field angles in degrees.")
    parser.add_argument("--freq-start", type=float, default=0.0, help="Start frequency in lp/mm.")
    parser.add_argument("--freq-end", type=float, default=80.0, help="End frequency in lp/mm.")
    parser.add_argument("--freq-step", type=float, default=1.0, help="Frequency step in lp/mm.")
    parser.add_argument("--label", default="field_expansion_check", help="Label used in run_id.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    field_expansion_check(
        Path(__file__).resolve().parents[1],
        lens=args.lens,
        fields=list(args.fields),
        freq_start=args.freq_start,
        freq_end=args.freq_end,
        freq_step=args.freq_step,
        label=args.label,
    )
