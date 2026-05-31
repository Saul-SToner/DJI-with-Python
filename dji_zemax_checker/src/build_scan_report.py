from __future__ import annotations

import argparse
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


REPORT_COLUMNS = [
    "rank",
    "score",
    "status",
    "scanned_radius",
    "scanned_conic",
    "MTF40_min",
    "MTF40_mean",
    "MTF50_min",
    "MTF50_mean",
    "25T25",
    "25T30",
    "27p5T40",
    "28T40",
    "28T50",
    "L5_edge",
    "S15T",
    "run_id",
    "output_folder",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _read_key_values(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None or not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line or line.strip().startswith("["):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {"", "null", "none", "nan"}:
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _num(value: Any) -> float:
    return _to_float(value) or 0.0


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "null", "none", "nan"}:
        return ""
    return text


def _is_failed(row: dict[str, str]) -> bool:
    return _clean_text(row.get("status")).lower() == "failed"


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.6g}"
    if value is None:
        return "null"
    text = str(value)
    return text if text else "null"


def _safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_+-]+", "_", label.strip()).strip("_") or "scan"


def _label_from_csv(path: Path, txt_values: dict[str, str]) -> str:
    if txt_values.get("label"):
        return txt_values["label"]
    name = path.stem
    match = re.match(r"\d{8}_\d{6}_(.*)_grid_summary$", name)
    return match.group(1) if match else name.replace("_grid_summary", "")


def _unique_values(rows: list[dict[str, str]], key: str) -> list[str]:
    values: list[tuple[float | None, str]] = []
    seen: set[str] = set()
    for row in rows:
        raw = str(row.get(key, "")).strip()
        if not raw or raw.lower() in {"null", "none"} or raw in seen:
            continue
        seen.add(raw)
        values.append((_to_float(raw), raw))
    values.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else item[1]))
    return [raw for _, raw in values]


def _sort_rows(rows: list[dict[str, str]], sort_by: str) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: _num(row.get(sort_by)), reverse=True)


def _balanced_score(row: dict[str, str]) -> float:
    score = (
        3.0 * _num(row.get("MTF40_min"))
        + 2.0 * _num(row.get("MTF50_min"))
        + _num(row.get("MTF40_mean"))
        + _num(row.get("MTF50_mean"))
        + 0.8 * _num(row.get("27p5T40"))
        + 0.8 * _num(row.get("28T40"))
        + 0.5 * _num(row.get("28T50"))
    )
    l5_edge = _to_float(row.get("L5_edge"))
    if l5_edge is not None and l5_edge < 0.44:
        score -= 0.02
    return score


def _usable_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if not _is_failed(row)]


def _best_by(rows: list[dict[str, str]], key: str) -> dict[str, str] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: _num(row.get(key)))


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "null")
            cells.append(_fmt(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _top_table_rows(rows: list[dict[str, str]], top_n: int, sort_by: str) -> list[dict[str, Any]]:
    table_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(_sort_rows(rows, sort_by)[:top_n], start=1):
        table_rows.append({"rank": rank, **row})
    return table_rows


def _all_numeric_zero(rows: list[dict[str, str]], key: str) -> bool:
    values = [_to_float(row.get(key)) for row in rows if not _is_failed(row)]
    values = [value for value in values if value is not None]
    return bool(values) and all(abs(value) <= 1e-12 for value in values)


def _risk_flags(rows: list[dict[str, str]], failed_points: int) -> list[str]:
    flags: list[str] = []
    if _all_numeric_zero(rows, "25T25"):
        flags.append(
            "25T25 remains zero across all scanned candidates; this may indicate a persistent field/frequency collapse or export/sampling issue."
        )
    if _all_numeric_zero(rows, "25T30"):
        flags.append(
            "25T30 remains zero across all scanned candidates; this may indicate a persistent field/frequency collapse or export/sampling issue."
        )

    unstable = [row for row in rows if (_to_float(row.get("MTF40_min")) or math.inf) < 0.005]
    for row in unstable[:12]:
        flags.append(f"unstable: run_id={row.get('run_id')} MTF40_min={_fmt(row.get('MTF40_min'))}")

    if failed_points > 0:
        for row in rows:
            if _is_failed(row):
                reason = _clean_text(row.get("failure_reason")) or "no failure_reason provided"
                flags.append(f"failed: run_id={row.get('run_id')} reason={reason}")

    for row in rows:
        warning = _clean_text(row.get("summary_extraction_warning"))
        if warning:
            flags.append(f"summary_extraction_warning: run_id={row.get('run_id')} {warning}")

    for row in rows:
        l5_edge = _to_float(row.get("L5_edge"))
        if l5_edge is not None and l5_edge < 0.44:
            flags.append(f"manufacturing risk: run_id={row.get('run_id')} L5_edge={_fmt(l5_edge)}")

    usable = _usable_rows(rows)
    for key in ("27p5T40", "28T40"):
        values = [_to_float(row.get(key)) for row in usable]
        values = [value for value in values if value is not None]
        if not values:
            continue
        average = sum(values) / len(values)
        if average <= 0:
            continue
        for row in usable:
            value = _to_float(row.get(key))
            if value is not None and value < 0.6 * average:
                flags.append(
                    f"edge-field imbalance: run_id={row.get('run_id')} {key}={_fmt(value)} average={_fmt(average)}"
                )
    return flags or ["No automatic risk flags beyond normal manual review."]


def _row_line(title: str, row: dict[str, str] | None, extra_score: float | None = None) -> str:
    if row is None:
        return f"- {title}: null"
    pieces = [
        f"run_id={row.get('run_id')}",
        f"R={_fmt(row.get('scanned_radius'))}",
        f"K={_fmt(row.get('scanned_conic'))}",
        f"score={_fmt(row.get('score'))}",
        f"MTF40_min={_fmt(row.get('MTF40_min'))}",
        f"MTF40_mean={_fmt(row.get('MTF40_mean'))}",
        f"MTF50_min={_fmt(row.get('MTF50_min'))}",
        f"28T40={_fmt(row.get('28T40'))}",
        f"L5_edge={_fmt(row.get('L5_edge'))}",
    ]
    if extra_score is not None:
        pieces.insert(3, f"balanced_score={_fmt(extra_score)}")
    return f"- {title}: " + ", ".join(pieces)


def _recommended(rows: list[dict[str, str]]) -> tuple[dict[str, str] | None, list[str]]:
    usable = _usable_rows(rows)
    if not usable:
        return None, ["No non-failed candidate is available."]

    balanced = [(row, _balanced_score(row)) for row in usable]
    balanced_best, balanced_value = max(balanced, key=lambda item: item[1])
    lines = [
        _row_line("balanced_score 第一名", balanced_best, balanced_value),
        _row_line("score 第一名", _best_by(usable, "score")),
        _row_line("MTF40_min 第一名", _best_by(usable, "MTF40_min")),
        _row_line("MTF40_mean 第一名", _best_by(usable, "MTF40_mean")),
        _row_line("28T40 第一名", _best_by(usable, "28T40")),
    ]
    return balanced_best, lines


def _engineering_interpretation(rows: list[dict[str, str]], label: str) -> list[str]:
    usable = _usable_rows(rows)
    top = _sort_rows(usable, "score")[: max(1, min(10, len(usable)))]
    top_conics = [_to_float(row.get("scanned_conic")) for row in top]
    top_conics = [value for value in top_conics if value is not None]
    lines = [
        "本轮扫描的作用是把同一面的 Radius 和 Conic 解耦成固定网格，而不是交给优化器自由漂移。",
        "因此结果更适合判断局部趋势和稳定区域，不能只看单个 score 最高点，还需要同时看低频最小值、边缘视场、L5 边缘厚度和失败/异常标记。",
    ]
    if "conic" in label.lower() or any(row.get("scanned_conic") for row in rows):
        near_10 = sum(1 for value in top_conics if abs(value - 10.0) <= 0.26)
        if top_conics and near_10 >= max(1, len(top_conics) // 2):
            lines.append("本轮结果显示 K≈10 构成主要优区，说明当前 S13 非球面量级不宜大幅偏离原先收敛点。")

        for target in (9.5, 10.5):
            subset = [row for row in usable if abs((_to_float(row.get("scanned_conic")) or math.inf) - target) < 1e-9]
            if subset and any((_to_float(row.get("MTF40_min")) or 0.0) < 0.005 for row in subset):
                lines.append(f"K={target:g} 附近存在 MTF40_min 明显塌陷的点，说明 K 偏离 10 后部分视场可能出现低频/中频 MTF 塌陷。")

    if _all_numeric_zero(rows, "25T25") and _all_numeric_zero(rows, "25T30"):
        lines.append(
            "25T25 和 25T30 在所有候选中仍为 0，说明单独扫描 S13R/S13 conic 不能解决这个问题；下一步应检查 MTF 采样/导出点，或扫描 S15T、后焦、相邻面曲率。"
        )
    else:
        lines.append("如果 25T25/25T30 只在部分组合中塌陷，后续应围绕未塌陷且 MTF40_min 较高的局部区域继续细扫。")

    return lines


def _next_scan(best: dict[str, str] | None, base_lens: str, surface: str) -> list[str]:
    scan_lens = best.get("scan_lens") if best else None
    source_lens = scan_lens if scan_lens and scan_lens.lower() != "null" else base_lens
    radius = _to_float(best.get("scanned_radius")) if best else None
    if radius is None:
        radius_values = "-11.92 -11.94 -11.96 -11.98 -12.00 -12.02 -12.04 -12.06"
    else:
        radius_values = " ".join(f"{radius + delta:.2f}" for delta in (-0.06, -0.04, -0.02, 0.0, 0.02, 0.04, 0.06))

    lines = [
        "建议下一步先围绕综合候选做 S13R 超细扫，保持 K 不再大范围漂移：",
        "```powershell",
        "python -u .\\src\\scan_radius.py `",
        f'  --base-lens "{source_lens}" `',
        f"  --surface {surface or 13} `",
        f"  --values {radius_values} `",
        "  --quick-focus `",
        "  --label S13R_ultrafine_K10",
        "```",
    ]

    scan_thickness = Path(__file__).resolve().parent / "scan_thickness.py"
    if scan_thickness.exists():
        lines.extend(
            [
                "同时建议做一轮 S15T / 像面前空气厚度小范围验证，用于判断 25T25、25T30 零点是否与焦面位置有关：",
                "```powershell",
                "python -u .\\src\\scan_thickness.py `",
                f'  --base-lens "{source_lens}" `',
                "  --surface 15 `",
                "  --values 2.68 2.71 2.74 2.77 2.80 `",
                "  --label S15T_focus_sensitivity",
                "```",
            ]
        )
    else:
        lines.append("建议后续新增 scan_thickness.py 或 scan_image_focus.py，用于验证像面/后焦调整是否能消除 25T25、25T30 为 0 的问题。")
    return lines


def build_report(
    grid_summary_csv: Path,
    grid_summary_txt: Path | None,
    source_log: Path | None,
    top_n: int,
    sort_by: str,
    decision_note: str | None,
    out_dir: Path,
) -> tuple[Path, Path]:
    rows = _read_csv(grid_summary_csv)
    txt_values = _read_key_values(grid_summary_txt)
    label = _label_from_csv(grid_summary_csv, txt_values)
    report_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{report_time}_{_safe_label(label)}_analysis_report.md"
    txt_path = out_dir / f"{report_time}_{_safe_label(label)}_analysis_report.txt"

    if sort_by not in set(rows[0].keys() if rows else []) | {"score"}:
        sort_by = "score"

    failed_rows = [row for row in rows if _is_failed(row)]
    best, recommendation_lines = _recommended(rows)
    top_rows = _top_table_rows(rows, top_n, sort_by)
    base_lens = txt_values.get("base_lens", "null")
    surface = txt_values.get("surface") or (rows[0].get("scanned_surface") if rows else "null")
    surface_comment = rows[0].get("scanned_surface_comment") if rows else "null"
    scanned_mode = (
        _clean_text(rows[0].get("scanned_mode")) if rows else ""
    ) or _clean_text(txt_values.get("scanned_mode"))
    if not scanned_mode:
        scanned_mode = "radius_conic_grid" if rows and _clean_text(rows[0].get("scanned_conic")) else "scan"
    fixed_s13_conic = ""
    if rows and not any(_clean_text(row.get("scanned_conic")) for row in rows):
        s13_conics = _unique_values(rows, "S13_conic")
        if len(s13_conics) == 1:
            fixed_s13_conic = s13_conics[0]

    lines = [
        "# Zemax Scan Analysis Report",
        "",
        "## 1. Run Metadata",
        f"- report_time: {datetime.now().isoformat(timespec='seconds')}",
        f"- grid_summary_csv: {grid_summary_csv}",
        f"- grid_summary_txt: {grid_summary_txt or 'null'}",
        f"- source_log: {source_log or 'null'}",
        f"- total_points: {len(rows)}",
        f"- failed_points: {len(failed_rows)}",
        f"- label: {label}",
        f"- scanned_surface: {surface}",
        f"- scanned_surface_comment: {surface_comment}",
        f"- scanned_mode: {scanned_mode}",
        f"- base_lens: {base_lens}",
        f"- sort_by: {sort_by}",
        f"- top_n: {top_n}",
    ]
    if fixed_s13_conic:
        lines.append(f"- fixed_S13_conic: {fixed_s13_conic}")
    if decision_note:
        lines.append(f"- decision_note: {decision_note}")

    lines.extend(
        [
            "",
            "## 2. Scan Range",
            "- scanned_radius unique values: " + ", ".join(_unique_values(rows, "scanned_radius") or ["null"]),
            "- scanned_conic unique values: " + ", ".join(_unique_values(rows, "scanned_conic") or ["null"]),
            "- scanned_thickness unique values: " + ", ".join(_unique_values(rows, "scanned_thickness") or ["null"]),
            "- scanned_value unique values: " + ", ".join(_unique_values(rows, "scanned_value") or ["null"]),
            "",
            "## 3. Top Candidates",
        ]
    )
    lines.extend(_markdown_table(top_rows, REPORT_COLUMNS))
    lines.extend(["", "## 4. Recommended Candidate"])
    lines.append("自动推荐采用 balanced_score，不直接等同于原始 score 第一名。")
    lines.extend(recommendation_lines)
    if best:
        lines.append(f"推荐综合候选: run_id={best.get('run_id')} output_folder={best.get('output_folder')}")

    lines.extend(["", "## 5. Risk Flags"])
    lines.extend(f"- {flag}" for flag in _risk_flags(rows, len(failed_rows)))

    lines.extend(["", "## 6. Engineering Interpretation"])
    lines.extend(_engineering_interpretation(rows, label))

    lines.extend(["", "## 7. Next Recommended Scan"])
    lines.extend(_next_scan(best, base_lens, str(surface or 13)))

    lines.extend(
        [
            "",
            "## 8. Files",
            f"- markdown report: {md_path}",
            f"- txt report: {txt_path}",
            f"- grid_summary_csv: {grid_summary_csv}",
            f"- grid_summary_txt: {grid_summary_txt or 'null'}",
            f"- source log: {source_log or 'null'}",
            f"- best candidate output_folder: {best.get('output_folder') if best else 'null'}",
            f"- best candidate scan_lens: {best.get('scan_lens') if best else 'null'}",
        ]
    )

    content = "\n".join(lines) + "\n"
    md_path.write_text(content, encoding="utf-8")
    txt_path.write_text(content, encoding="utf-8")
    return md_path, txt_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Markdown/TXT analysis report from a Zemax grid summary CSV.")
    parser.add_argument("--grid-summary-csv", required=True, type=Path, help="Path to *_grid_summary.csv.")
    parser.add_argument("--grid-summary-txt", type=Path, help="Optional path to *_grid_summary_for_chatgpt.txt.")
    parser.add_argument("--log", type=Path, help="Optional PowerShell scan log path.")
    parser.add_argument("--top-n", type=int, default=10, help="Number of candidates to show in the top table.")
    parser.add_argument("--sort-by", default="score", help="Sort key for the top-candidate table.")
    parser.add_argument("--decision-note", help="Optional note copied into the report metadata.")
    parser.add_argument("--out-dir", type=Path, default=Path("reports"), help="Output directory for reports.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    md, txt = build_report(
        grid_summary_csv=args.grid_summary_csv,
        grid_summary_txt=args.grid_summary_txt,
        source_log=args.log,
        top_n=args.top_n,
        sort_by=args.sort_by,
        decision_note=args.decision_note,
        out_dir=args.out_dir,
    )
    print(f"markdown_report: {md}", flush=True)
    print(f"txt_report: {txt}", flush=True)
