from __future__ import annotations

import argparse
import csv
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from console_summary import read_summary_values
from export_surfaces import safe_get
from run_files import find_run_file
from scan_radius import _export_current_point, _safe_label


METRICS = [
    ("F/#", "current_f_number"),
    ("EFL", "efl"),
    ("BFL", "bfl"),
    ("TTL", "ttl"),
    ("Working F/#", "working_f_number"),
    ("S12R", "S12R"),
    ("S13R", "S13R"),
    ("S13_conic", "S13_conic"),
    ("S15T", "S15T"),
    ("L5_edge", "L5_edge"),
    ("MTF40_min", "MTF40_min"),
    ("MTF40_mean", "MTF40_mean"),
    ("MTF50_min", "MTF50_min"),
    ("MTF50_mean", "MTF50_mean"),
    ("25T25", "25T25"),
    ("25T30", "25T30"),
    ("27p5T40", "27p5T40"),
    ("28T40", "28T40"),
    ("28T50", "28T50"),
    ("manufacturing_check", "manufacturing_status"),
]

HIGHER_IS_BETTER = {
    "BFL",
    "L5_edge",
    "MTF40_min",
    "MTF40_mean",
    "MTF50_min",
    "MTF50_mean",
    "25T25",
    "25T30",
    "27p5T40",
    "28T40",
    "28T50",
}
LOWER_IS_BETTER = {"TTL", "F/#", "Working F/#"}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "nan"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.6g}"
    if value is None:
        return "null"
    text = str(value)
    return text if text else "null"


def _unique_run_dir(project_root: Path, label: str) -> tuple[str, Path]:
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    root = project_root / "results" / "compare"
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


def _export_one(oss: Any, lens_path: Path, side: str, compare_run_id: str, compare_dir: Path) -> dict[str, str]:
    export_run_id = f"{compare_run_id}_{side}"
    export_dir = compare_dir / f"{side}_export"
    oss.load(lens_path, saveifneeded=False)
    extra_metadata = {
        "label": compare_run_id,
        "comparison_side": side,
        "comparison_lens": str(lens_path),
    }
    _export_current_point(oss, export_run_id, export_dir, extra_metadata)

    summary_src = find_run_file(export_dir, "summary_for_chatgpt")
    summary_dst = compare_dir / f"{side}_summary_for_chatgpt.txt"
    shutil.copy2(summary_src, summary_dst)
    values = read_summary_values(summary_dst)
    values["summary_path"] = str(summary_dst)
    values["export_folder"] = str(export_dir)
    return values


def _assessment(metric: str, before: Any, after: Any) -> str:
    before_number = _to_float(before)
    after_number = _to_float(after)
    if before_number is None or after_number is None:
        if str(before) == str(after):
            return "unchanged"
        return "changed"
    delta = after_number - before_number
    if abs(delta) < 1e-12:
        return "unchanged"
    if metric in HIGHER_IS_BETTER:
        return "improved" if delta > 0 else "declined"
    if metric in LOWER_IS_BETTER:
        return "improved" if delta < 0 else "declined"
    return "increased" if delta > 0 else "decreased"


def _comparison_rows(before: dict[str, str], after: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric, key in METRICS:
        before_value = before.get(key, "null")
        after_value = after.get(key, "null")
        before_number = _to_float(before_value)
        after_number = _to_float(after_value)
        delta = after_number - before_number if before_number is not None and after_number is not None else None
        percent_change = (
            delta / abs(before_number) * 100.0
            if delta is not None and before_number is not None and abs(before_number) > 1e-12
            else None
        )
        rows.append(
            {
                "metric": metric,
                "before": before_value,
                "after": after_value,
                "delta": delta,
                "percent_change": percent_change,
                "assessment": _assessment(metric, before_value, after_value),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["metric", "before", "after", "delta", "percent_change", "assessment"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    columns = ["metric", "before", "after", "delta", "percent_change", "assessment"]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(row.get(column)).replace("|", "\\|") for column in columns) + " |")
    return lines


def _metric_names(rows: list[dict[str, Any]], assessment: str, metrics: set[str] | None = None) -> list[str]:
    selected = []
    for row in rows:
        if row.get("assessment") != assessment:
            continue
        if metrics is not None and row.get("metric") not in metrics:
            continue
        selected.append(str(row.get("metric")))
    return selected


def _manufacturing_risk(values: dict[str, str]) -> list[str]:
    risks: list[str] = []
    manufacturing_status = str(values.get("manufacturing_status", "")).lower()
    structure_status = str(values.get("structure_status", "")).lower()
    l5_edge = _to_float(values.get("L5_edge"))
    if manufacturing_status in {"fail", "warning"}:
        risks.append(f"manufacturing_status={manufacturing_status}")
    if structure_status == "fail":
        risks.append("structure_status=fail")
    if l5_edge is not None and l5_edge < 0.40:
        risks.append(f"L5_edge={l5_edge:.6g} < 0.40")
    return risks


def _stage_best_judgement(before: dict[str, str], after: dict[str, str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    after_risks = _manufacturing_risk(after)
    if after_risks:
        reasons.append("制造/结构风险未完全消除: " + "; ".join(after_risks))
        return False, reasons

    checks = ["MTF40_min", "MTF40_mean", "MTF50_min", "MTF50_mean", "27p5T40", "28T40", "28T50"]
    improved_or_equal = 0
    declined = []
    for key in checks:
        before_value = _to_float(before.get(key))
        after_value = _to_float(after.get(key))
        if before_value is None or after_value is None:
            continue
        if after_value >= before_value:
            improved_or_equal += 1
        else:
            declined.append(key)

    if improved_or_equal >= 4:
        reasons.append(f"核心 MTF 指标中 {improved_or_equal} 项不低于 before。")
        if declined:
            reasons.append("仍需关注下降项: " + ", ".join(declined))
        return True, reasons

    reasons.append("核心 MTF 指标提升项不足，暂不建议作为阶段性最佳。")
    if declined:
        reasons.append("下降项: " + ", ".join(declined))
    return False, reasons


def _write_report(
    md_path: Path,
    txt_path: Path,
    compare_run_id: str,
    before_lens: Path,
    after_lens: Path,
    before: dict[str, str],
    after: dict[str, str],
    rows: list[dict[str, Any]],
    compare_dir: Path,
) -> None:
    performance_metrics = HIGHER_IS_BETTER | LOWER_IS_BETTER
    improved = _metric_names(rows, "improved", performance_metrics)
    declined = _metric_names(rows, "declined", performance_metrics)
    increased = _metric_names(rows, "increased")
    decreased = _metric_names(rows, "decreased")
    after_risks = _manufacturing_risk(after)
    before_risks = _manufacturing_risk(before)
    stage_best, stage_reasons = _stage_best_judgement(before, after)

    lines = [
        "# Zemax Lens Comparison Report",
        "",
        "## 1. Metadata",
        f"- run_id: {compare_run_id}",
        f"- before: {before_lens}",
        f"- after: {after_lens}",
        f"- output_folder: {compare_dir}",
        f"- before_summary: {compare_dir / 'before_summary_for_chatgpt.txt'}",
        f"- after_summary: {compare_dir / 'after_summary_for_chatgpt.txt'}",
        "",
        "## 2. Comparison Table",
    ]
    lines.extend(_markdown_table(rows))
    lines.extend(
        [
            "",
            "## 3. Changes",
            "- improved metrics: " + (", ".join(improved) if improved else "none"),
            "- declined metrics: " + (", ".join(declined) if declined else "none"),
            "- increased non-directional metrics: " + (", ".join(increased) if increased else "none"),
            "- decreased non-directional metrics: " + (", ".join(decreased) if decreased else "none"),
            "",
            "## 4. Manufacturing Risk",
            "- before risk: " + ("; ".join(before_risks) if before_risks else "none"),
            "- after risk: " + ("; ".join(after_risks) if after_risks else "none"),
            "",
            "## 5. Stage Best Judgement",
            f"- after_is_stage_best_candidate: {'yes' if stage_best else 'no'}",
        ]
    )
    lines.extend(f"- {reason}" for reason in stage_reasons)
    lines.extend(
        [
            "",
            "## 6. Engineering Interpretation",
            "这份比较只判断当前 before/after 两个 Zemax 文件的导出指标差异，不替代完整设计验收。",
            "如果 after 在制造风险可控的前提下提升了 MTF40/50 的均值或最小值，并且边缘视场没有明显退化，则可以作为阶段性最佳版本继续保留。",
            "如果 after 只提升单一指标但牺牲 L5_edge、BFL 或边缘视场 MTF，则应作为局部实验结果，而不是最终主线。",
            "",
            "## 7. Files",
            f"- comparison_table: {compare_dir / 'comparison_table.csv'}",
            f"- markdown_report: {md_path}",
            f"- txt_report: {txt_path}",
        ]
    )

    content = "\n".join(lines) + "\n"
    md_path.write_text(content, encoding="utf-8")
    txt_path.write_text(content, encoding="utf-8")


def compare_lens_reports(project_root: Path, before: Path, after: Path, label: str) -> Path:
    if not before.exists():
        raise FileNotFoundError(f"Before lens not found: {before}")
    if not after.exists():
        raise FileNotFoundError(f"After lens not found: {after}")

    compare_run_id, compare_dir = _unique_run_dir(project_root, label)
    compare_dir.mkdir(parents=True, exist_ok=True)

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    try:
        before_values = _export_one(oss, before, "before", compare_run_id, compare_dir)
        after_values = _export_one(oss, after, "after", compare_run_id, compare_dir)
    finally:
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
        except Exception as exc:
            print(f"[WARNING] Failed to restore original file: {repr(exc)}", flush=True)

    rows = _comparison_rows(before_values, after_values)
    table_path = compare_dir / "comparison_table.csv"
    _write_csv(table_path, rows)
    md_path = compare_dir / "comparison_report.md"
    txt_path = compare_dir / "comparison_report.txt"
    _write_report(md_path, txt_path, compare_run_id, before, after, before_values, after_values, rows, compare_dir)

    print(f"compare_run_id: {compare_run_id}", flush=True)
    print(f"compare_output_folder: {compare_dir}", flush=True)
    print(f"before_summary: {compare_dir / 'before_summary_for_chatgpt.txt'}", flush=True)
    print(f"after_summary: {compare_dir / 'after_summary_for_chatgpt.txt'}", flush=True)
    print(f"comparison_table: {table_path}", flush=True)
    print(f"comparison_report_md: {md_path}", flush=True)
    print(f"comparison_report_txt: {txt_path}", flush=True)
    return compare_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two Zemax lens files using the existing export pipeline.")
    parser.add_argument("--before", required=True, type=Path, help="Before/original .ZOS file.")
    parser.add_argument("--after", required=True, type=Path, help="After/candidate .ZOS file.")
    parser.add_argument("--label", default="lens_compare", help="Label used in comparison run_id.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    compare_lens_reports(
        Path(__file__).resolve().parents[1],
        before=args.before,
        after=args.after,
        label=args.label,
    )
