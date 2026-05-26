from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from export_system_summary import _raw_optical_summary, _read_raw_text
from run_files import find_run_file


TARGET_MTF_FREQUENCIES = (50.0, 100.0)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _system_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = find_run_file(run_dir, "system_summary")
    raw_path = find_run_file(run_dir, "system_data_raw")
    data = _load_json(summary_path)
    optical = data.get("optical_summary") or {}

    if raw_path.exists() and data.get("system_data_raw_valid") is not False:
        raw_optical = _raw_optical_summary(_read_raw_text(raw_path))
        for key, value in raw_optical.items():
            if optical.get(key) is None and value is not None:
                optical[key] = value

    return {
        "system_file": data.get("system_file"),
        "mode": data.get("mode"),
        "number_of_surfaces": data.get("number_of_surfaces"),
        "efl": optical.get("efl") or optical.get("effective_focal_length_air"),
        "bfl": optical.get("bfl") or optical.get("back_focal_length"),
        "ttl": optical.get("ttl") or optical.get("total_track"),
        "f_number": optical.get("f_number") or optical.get("image_space_f_number"),
        "entrance_pupil_diameter": optical.get("entrance_pupil_diameter"),
    }


def _manufacturing_summary(run_dir: Path) -> dict[str, Any]:
    data = _load_json(find_run_file(run_dir, "manufacturing_check"))
    l5 = ((data.get("checks") or {}).get("l5") or {})

    return {
        "manufacturing_status": data.get("status"),
        "l5_status": l5.get("status"),
        "l5_surfaces": ";".join(str(item) for item in (l5.get("surfaces") or [])),
        "l5_center_thickness": l5.get("center_thickness"),
        "l5_edge_thickness": l5.get("edge_thickness_at_common_semi_diameter"),
        "l5_minimum_abs_radius": l5.get("minimum_abs_radius"),
    }


def _parse_field(description: str) -> float | None:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", description)
    return _to_float(match.group(0)) if match else None


def _parse_orientation(label: str) -> str:
    normalized = label.strip().lower()
    if normalized in {"子午", "t", "tan", "tangential", "tangential mtf"}:
        return "T"
    if normalized in {"弧矢", "s", "sag", "sagittal", "sagittal mtf"}:
        return "S"
    return label.strip() or "unknown"


def _is_real_mtf_curve(item: dict[str, Any]) -> bool:
    text = f"{item.get('description', '')} {item.get('label', '')} {item.get('source_curve', '')}".lower()
    return not any(token in text for token in ("diffraction", "limit", "衍射", "极限"))


def _read_mtf_rows(path: Path) -> tuple[list[float], list[dict[str, Any]]]:
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
    series_values: list[list[float | None]] = [[] for _ in descriptions]

    for row in rows[3:]:
        frequency = _to_float(row[0] if row else None)
        if frequency is None:
            continue
        frequencies.append(frequency)

        for output_index, source_index in enumerate(source_columns):
            value = row[source_index] if source_index < len(row) else None
            series_values[output_index].append(_to_float(value))

    series = [
        {
            "series_index": index + 1,
            "description": descriptions[index] if index < len(descriptions) else "",
            "label": labels[index] if index < len(labels) else "",
            "field": _parse_field(descriptions[index] if index < len(descriptions) else ""),
            "wavelength": "All",
            "orientation": _parse_orientation(labels[index] if index < len(labels) else ""),
            "source_curve": (
                f"{index + 1}: {descriptions[index] if index < len(descriptions) else ''} "
                f"{labels[index] if index < len(labels) else ''}"
            ).strip(),
            "values": values,
        }
        for index, values in enumerate(series_values)
    ]

    return frequencies, series


def _interpolate(x_values: list[float], y_values: list[float | None], target: float) -> float | None:
    points = [(x, y) for x, y in zip(x_values, y_values, strict=False) if y is not None]
    if not points:
        return None

    if target < points[0][0] or target > points[-1][0]:
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


def _mtf_fixed_summary(run_id: str, run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frequencies, series = _read_mtf_rows(find_run_file(run_dir, "mtf_fft"))
    fixed_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    real_series = [item for item in series if _is_real_mtf_curve(item)]
    fields = [item["field"] for item in real_series if item.get("field") is not None]
    center_field = min(fields, key=lambda value: abs(value)) if fields else None
    edge_field = max(fields, key=lambda value: abs(value)) if fields else None

    for target in TARGET_MTF_FREQUENCIES:
        values: list[float] = []
        keyed_values: dict[str, float] = {}
        for item in real_series:
            value = _interpolate(frequencies, item["values"], target)
            fixed_rows.append(
                {
                    "run_id": run_id,
                    "field": item["field"],
                    "wavelength": item["wavelength"],
                    "series_name": item["description"],
                    "orientation": item["orientation"],
                    "frequency_lp_per_mm": target,
                    "mtf_value": value,
                    "source_curve": item["source_curve"],
                    "series_index": item["series_index"],
                    "description": item["description"],
                    "label": item["label"],
                    "mtf": value,
                }
            )
            if value is not None:
                values.append(value)
                if item["field"] == center_field and item["orientation"] in {"T", "S"}:
                    keyed_values[f"center_{item['orientation'].lower()}"] = value
                if item["field"] == edge_field and item["orientation"] in {"T", "S"}:
                    keyed_values[f"edge_{item['orientation'].lower()}"] = value

        key = str(int(target)) if target.is_integer() else str(target).replace(".", "_")
        summary[f"mtf{key}_min_all_real_fields"] = min(values) if values else None
        summary[f"mtf{key}_mean_all_real_fields"] = sum(values) / len(values) if values else None
        summary[f"mtf{key}_center_t"] = keyed_values.get("center_t")
        summary[f"mtf{key}_center_s"] = keyed_values.get("center_s")
        summary[f"mtf{key}_edge_t"] = keyed_values.get("edge_t")
        summary[f"mtf{key}_edge_s"] = keyed_values.get("edge_s")

    return summary, fixed_rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_l5_trend_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    points = [
        (row["run_id"], _to_float(row.get("l5_edge_thickness")))
        for row in rows
        if _to_float(row.get("l5_edge_thickness")) is not None
    ]

    width, height = 900, 360
    margin_left, margin_right, margin_top, margin_bottom = 70, 30, 30, 95
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    if not points:
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            '<text x="30" y="50">No L5 edge thickness data.</text></svg>',
            encoding="utf-8",
        )
        return

    y_values = [value for _, value in points if value is not None]
    y_min = min(0.0, min(y_values))
    y_max = max(y_values)
    if y_max == y_min:
        y_max = y_min + 1.0

    def x_pos(index: int) -> float:
        if len(points) == 1:
            return margin_left + plot_width / 2
        return margin_left + plot_width * index / (len(points) - 1)

    def y_pos(value: float) -> float:
        return margin_top + plot_height * (1.0 - (value - y_min) / (y_max - y_min))

    polyline = " ".join(f"{x_pos(i):.2f},{y_pos(value):.2f}" for i, (_, value) in enumerate(points))
    circles = "\n".join(
        f'<circle cx="{x_pos(i):.2f}" cy="{y_pos(value):.2f}" r="4" fill="#1f6feb" />'
        for i, (_, value) in enumerate(points)
    )
    labels = "\n".join(
        (
            f'<text x="{x_pos(i):.2f}" y="{height - 52}" font-size="10" '
            f'text-anchor="end" transform="rotate(-45 {x_pos(i):.2f},{height - 52})">{run_id}</text>'
        )
        for i, (run_id, _) in enumerate(points)
    )
    threshold = 0.2
    threshold_y = y_pos(threshold) if y_min <= threshold <= y_max else None
    threshold_line = (
        ""
        if threshold_y is None
        else (
            f'<line x1="{margin_left}" y1="{threshold_y:.2f}" x2="{width - margin_right}" '
            f'y2="{threshold_y:.2f}" stroke="#d1242f" stroke-dasharray="5 4" />'
            f'<text x="{width - margin_right - 6}" y="{threshold_y - 6:.2f}" '
            f'font-size="12" text-anchor="end" fill="#d1242f">0.2 threshold</text>'
        )
    )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white" />
<text x="{margin_left}" y="22" font-size="16" font-family="Arial">L5 edge thickness vs run_id</text>
<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#333" />
<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#333" />
{threshold_line}
<polyline points="{polyline}" fill="none" stroke="#1f6feb" stroke-width="2" />
{circles}
{labels}
<text x="18" y="{margin_top + 12}" font-size="12" font-family="Arial">{y_max:.4g}</text>
<text x="18" y="{height - margin_bottom}" font-size="12" font-family="Arial">{y_min:.4g}</text>
<text x="18" y="{margin_top + plot_height / 2:.2f}" font-size="12" font-family="Arial" transform="rotate(-90 18,{margin_top + plot_height / 2:.2f})">edge thickness</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def summarize_results(project_root: Path) -> dict[str, Path]:
    results_dir = project_root / "results"
    summary_rows: list[dict[str, Any]] = []
    mtf_fixed_rows: list[dict[str, Any]] = []

    for run_dir in sorted(path for path in results_dir.iterdir() if path.is_dir()):
        run_id = run_dir.name
        system = _system_summary(run_dir)
        manufacturing = _manufacturing_summary(run_dir)
        mtf_summary, mtf_rows = _mtf_fixed_summary(run_id, run_dir)
        mtf_fixed_rows.extend(mtf_rows)

        summary_rows.append(
            {
                "run_id": run_id,
                **system,
                **manufacturing,
                **mtf_summary,
                "run_dir": str(run_dir),
            }
        )

    summary_fields = [
        "run_id",
        "system_file",
        "mode",
        "number_of_surfaces",
        "efl",
        "bfl",
        "ttl",
        "f_number",
        "entrance_pupil_diameter",
        "manufacturing_status",
        "l5_status",
        "l5_surfaces",
        "l5_center_thickness",
        "l5_edge_thickness",
        "l5_minimum_abs_radius",
        "mtf50_center_t",
        "mtf50_center_s",
        "mtf50_edge_t",
        "mtf50_edge_s",
        "mtf100_center_t",
        "mtf100_center_s",
        "mtf100_edge_t",
        "mtf100_edge_s",
        "mtf50_min_all_real_fields",
        "mtf50_mean_all_real_fields",
        "mtf100_min_all_real_fields",
        "mtf100_mean_all_real_fields",
        "run_dir",
    ]
    mtf_fields = ["run_id", "frequency_lp_per_mm", "series_index", "description", "label", "mtf"]
    mtf_detail_fields = [
        "run_id",
        "field",
        "wavelength",
        "series_name",
        "orientation",
        "frequency_lp_per_mm",
        "mtf_value",
        "source_curve",
    ]

    summary_path = results_dir / "summary.csv"
    mtf_path = results_dir / "mtf_fixed.csv"
    mtf_detail_path = results_dir / "mtf_fixed_detail.csv"
    trend_path = results_dir / "l5_edge_thickness_trend.svg"

    _write_csv(summary_path, summary_rows, summary_fields)
    _write_csv(mtf_path, mtf_fixed_rows, mtf_fields)
    _write_csv(mtf_detail_path, mtf_fixed_rows, mtf_detail_fields)
    _write_l5_trend_svg(trend_path, summary_rows)

    return {
        "summary": summary_path,
        "mtf_fixed": mtf_path,
        "mtf_fixed_detail": mtf_detail_path,
        "l5_trend": trend_path,
    }


if __name__ == "__main__":
    paths = summarize_results(Path(__file__).resolve().parents[1])
    for name, path in paths.items():
        print(f"{name}: {path}")
