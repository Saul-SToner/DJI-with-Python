from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from console_summary import read_summary_values
from export_surfaces import safe_get
from run_files import find_run_file
from scan_conic import _set_conic
from scan_radius import (
    _append_warning,
    _export_current_point,
    _run_quick_focus,
    _safe_label,
    _set_radius,
    _surface_at,
    resolve_surface_number,
)
from summarize_results import summarize_results


SORT_FIELDS = {"MTF40_min", "MTF40_mean", "MTF50_min", "MTF50_mean", "28T40", "28T50", "score"}

GRID_COLUMNS = [
    "run_id",
    "status",
    "scanned_surface",
    "scanned_surface_comment",
    "scanned_radius",
    "scanned_conic",
    "output_folder",
    "scan_lens",
    "F/#",
    "EFL",
    "BFL",
    "TTL",
    "Working F/#",
    "S13R",
    "S13_conic",
    "S15T",
    "L5_edge",
    "MTF40_min",
    "MTF40_mean",
    "MTF50_min",
    "MTF50_mean",
    "25T20",
    "25T25",
    "25T30",
    "25T35",
    "25T40",
    "25T50",
    "25S50",
    "27p5T40",
    "28T40",
    "28T50",
    "score",
    "summary_extraction_warning",
    "failure_reason",
]


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


def _score(row: dict[str, Any]) -> float:
    def value(key: str) -> float:
        return _to_float(row.get(key)) or 0.0

    return (
        4.0 * value("MTF40_min")
        + 2.0 * value("MTF50_min")
        + value("MTF40_mean")
        + value("MTF50_mean")
        + 0.5 * value("28T40")
        + 0.5 * value("28T50")
    )


def _value_token(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "minf"
    text = f"{abs(value):g}".replace(".", "p")
    if value < 0:
        return f"m{text}"
    return text


def _combo_suffix(label: str, radius: float, conic: float) -> str:
    return f"{_safe_label(label)}_R_{_value_token(radius)}_K_{_value_token(conic)}"


def _unique_run_dir(project_root: Path, label: str, radius: float, conic: float) -> tuple[str, Path]:
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_combo_suffix(label, radius, conic)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _existing_completed_run(project_root: Path, label: str, radius: float, conic: float) -> tuple[str, Path] | None:
    suffix = _combo_suffix(label, radius, conic)
    results_dir = project_root / "results"
    if not results_dir.exists():
        return None
    for run_dir in sorted(results_dir.glob(f"*_{suffix}"), reverse=True):
        if find_run_file(run_dir, "summary_for_chatgpt").exists():
            return run_dir.name, run_dir
    return None


def _read_run_row(
    run_id: str,
    run_dir: Path,
    scanned_surface: int,
    scanned_surface_comment: str,
    radius: float,
    conic: float,
    failure_reason: str = "",
) -> dict[str, Any]:
    values = read_summary_values(find_run_file(run_dir, "summary_for_chatgpt"))
    row: dict[str, Any] = {
        "run_id": values.get("run_id") or run_id,
        "status": "failed" if failure_reason else values.get("status", "null"),
        "scanned_surface": values.get("scanned_surface", scanned_surface),
        "scanned_surface_comment": values.get("scanned_surface_comment", scanned_surface_comment),
        "scanned_radius": values.get("scanned_radius", radius),
        "scanned_conic": values.get("scanned_conic", conic),
        "output_folder": str(run_dir),
        "scan_lens": values.get("scan_lens", "null"),
        "F/#": values.get("current_f_number", "null"),
        "EFL": values.get("efl", "null"),
        "BFL": values.get("bfl", "null"),
        "TTL": values.get("ttl", "null"),
        "Working F/#": values.get("working_f_number", "null"),
        "S13R": values.get("S13R", "null"),
        "S13_conic": values.get("S13_conic", "null"),
        "S15T": values.get("S15T", "null"),
        "L5_edge": values.get("L5_edge", "null"),
        "MTF40_min": values.get("MTF40_min", "null"),
        "MTF40_mean": values.get("MTF40_mean", "null"),
        "MTF50_min": values.get("MTF50_min", "null"),
        "MTF50_mean": values.get("MTF50_mean", "null"),
        "25T20": values.get("25T20", "null"),
        "25T25": values.get("25T25", "null"),
        "25T30": values.get("25T30", "null"),
        "25T35": values.get("25T35", "null"),
        "25T40": values.get("25T40", "null"),
        "25T50": values.get("25T50", "null"),
        "25S50": values.get("25S50", "null"),
        "27p5T40": values.get("27p5T40", "null"),
        "28T40": values.get("28T40", "null"),
        "28T50": values.get("28T50", "null"),
        "summary_extraction_warning": values.get("summary_extraction_warning", "null"),
        "failure_reason": failure_reason,
    }
    row["score"] = _score(row)
    return row


def _failure_row(
    run_id: str,
    run_dir: Path,
    scanned_surface: int,
    scanned_surface_comment: str,
    radius: float,
    conic: float,
    scan_lens: Path | None,
    failure_reason: str,
) -> dict[str, Any]:
    row = {key: "null" for key in GRID_COLUMNS}
    row.update(
        {
            "run_id": run_id,
            "status": "failed",
            "scanned_surface": scanned_surface,
            "scanned_surface_comment": scanned_surface_comment,
            "scanned_radius": radius,
            "scanned_conic": conic,
            "output_folder": str(run_dir),
            "scan_lens": str(scan_lens) if scan_lens else "null",
            "score": 0.0,
            "failure_reason": failure_reason,
        }
    )
    return row


def _write_grid_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=GRID_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sort_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _to_float(row.get(sort_by)) or -math.inf, reverse=True)


def _write_grid_text(
    path: Path,
    label: str,
    base_lens: Path,
    surface: int,
    radii: tuple[float, ...],
    conics: tuple[float, ...],
    sort_by: str,
    rows: list[dict[str, Any]],
) -> None:
    failed = [row for row in rows if row.get("status") == "failed" or row.get("failure_reason")]
    sorted_rows = _sort_rows(rows, sort_by)
    lines = [
        f"label: {label}",
        f"base_lens: {base_lens}",
        f"surface: {surface}",
        "radii: " + ", ".join(f"{value:g}" for value in radii),
        "conics: " + ", ".join(f"{value:g}" for value in conics),
        f"sort_by: {sort_by}",
        f"total points: {len(rows)}",
        f"success points: {len(rows) - len(failed)}",
        f"failed points: {len(failed)}",
        "",
        "[top_10]",
    ]
    for index, row in enumerate(sorted_rows[:10], start=1):
        lines.extend(
            [
                f"rank: {index}",
                f"radius: {row.get('scanned_radius')}",
                f"conic: {row.get('scanned_conic')}",
                f"score: {row.get('score')}",
                f"MTF40_min: {row.get('MTF40_min')}",
                f"MTF40_mean: {row.get('MTF40_mean')}",
                f"MTF50_min: {row.get('MTF50_min')}",
                f"MTF50_mean: {row.get('MTF50_mean')}",
                f"27p5T40: {row.get('27p5T40')}",
                f"28T40: {row.get('28T40')}",
                f"28T50: {row.get('28T50')}",
                f"L5_edge: {row.get('L5_edge')}",
                f"run_id: {row.get('run_id')}",
                f"output_folder: {row.get('output_folder')}",
                f"failure_reason: {row.get('failure_reason') or 'none'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def scan_radius_conic_grid(
    project_root: Path,
    base_lens: Path,
    surface: int,
    radii: tuple[float, ...],
    conics: tuple[float, ...],
    label: str = "radius_conic_grid_scan",
    quick_focus: bool = False,
    resume: bool = False,
    sort_by: str = "MTF40_min",
) -> tuple[Path, Path]:
    if not base_lens.exists():
        raise FileNotFoundError(f"Base lens not found: {base_lens}")
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"Unsupported --sort-by {sort_by!r}. Allowed: {', '.join(sorted(SORT_FIELDS))}")

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    try:
        oss.load(base_lens, saveifneeded=False)
        resolved_surface_number = resolve_surface_number(oss, surface, None)
        resolved_surface = _surface_at(oss, resolved_surface_number)
        resolved_surface_comment = str(safe_get(resolved_surface, "Comment") or "")
        print(
            "Scanning radius/conic grid surface:",
            resolved_surface_number,
            f"comment={resolved_surface_comment!r}",
            flush=True,
        )
    except Exception:
        if original_file:
            try:
                oss.load(original_file, saveifneeded=False)
            except Exception:
                pass
        raise

    try:
        for radius in radii:
            for conic in conics:
                existing = _existing_completed_run(project_root, label, radius, conic) if resume else None
                if existing:
                    existing_run_id, existing_run_dir = existing
                    print(f"Skipping existing run: {existing_run_id}", flush=True)
                    rows.append(
                        _read_run_row(
                            existing_run_id,
                            existing_run_dir,
                            resolved_surface_number,
                            resolved_surface_comment,
                            radius,
                            conic,
                        )
                    )
                    continue

                run_id, run_dir = _unique_run_dir(project_root, label, radius, conic)
                copy_path: Path | None = None
                try:
                    oss.load(base_lens, saveifneeded=False)
                    target_surface = _surface_at(oss, resolved_surface_number)
                    target_comment = str(safe_get(target_surface, "Comment") or "") or resolved_surface_comment
                    _set_radius(target_surface, radius)
                    _set_conic(target_surface, conic)
                    oss.update_status()

                    copy_path = scan_dir / f"{run_id}.zos"
                    oss.save_as(copy_path)
                    print(f"Saved scan copy: {copy_path}", flush=True)

                    quick_focus_warning = None
                    if quick_focus:
                        quick_focus_warning = _run_quick_focus(oss)
                        target_surface = _surface_at(oss, resolved_surface_number)
                        actual_radius = _to_float(safe_get(target_surface, "Radius"))
                        actual_conic = _to_float(safe_get(target_surface, "Conic"))
                        restored: list[str] = []
                        if actual_radius is None or abs(actual_radius - radius) > 1e-9:
                            _set_radius(target_surface, radius)
                            restored.append(f"Radius restored to {radius:g}")
                        if actual_conic is None or abs(actual_conic - conic) > 1e-9:
                            _set_conic(target_surface, conic)
                            restored.append(f"Conic restored to {conic:g}")
                        if restored:
                            message = "Quick Focus changed scanned parameters; " + "; ".join(restored) + "."
                            quick_focus_warning = (
                                message if quick_focus_warning is None else f"{quick_focus_warning} {message}"
                            )
                        oss.update_status()
                        oss.save_as(copy_path)
                        if quick_focus_warning:
                            _append_warning(run_dir, run_id, quick_focus_warning)

                    extra_metadata = {
                        "label": label,
                        "scanned_parameter": "RadiusConicGrid",
                        "scanned_mode": "radius_conic_grid",
                        "scanned_surface": resolved_surface_number,
                        "scanned_surface_comment": target_comment,
                        "scanned_radius": radius,
                        "scanned_conic": conic,
                        "quick_focus": quick_focus,
                        "quick_focus_warning": quick_focus_warning,
                        "base_lens": str(base_lens),
                        "scan_lens": str(copy_path),
                        "scan_copy_file": str(copy_path),
                    }
                    _export_current_point(oss, run_id, run_dir, extra_metadata)
                    rows.append(
                        _read_run_row(
                            run_id,
                            run_dir,
                            resolved_surface_number,
                            target_comment,
                            radius,
                            conic,
                        )
                    )
                except Exception as exc:
                    failure_reason = f"{type(exc).__name__}: {exc!r}"
                    print(f"[ERROR] {run_id} failed: {failure_reason}", flush=True)
                    try:
                        _append_warning(run_dir, run_id, f"radius/conic grid point failed: {failure_reason}")
                    except Exception:
                        pass
                    rows.append(
                        _failure_row(
                            run_id,
                            run_dir,
                            resolved_surface_number,
                            resolved_surface_comment,
                            radius,
                            conic,
                            copy_path,
                            failure_reason,
                        )
                    )

        summarize_results(project_root)
    finally:
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
        except Exception as exc:
            print(f"[WARNING] Failed to restore original file: {repr(exc)}", flush=True)

    summary_dir = project_root / "results" / "grid_summaries"
    summary_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    csv_path = summary_dir / f"{summary_id}_grid_summary.csv"
    txt_path = summary_dir / f"{summary_id}_grid_summary_for_chatgpt.txt"
    sorted_rows = _sort_rows(rows, sort_by)
    _write_grid_csv(csv_path, sorted_rows)
    _write_grid_text(txt_path, label, base_lens, surface, radii, conics, sort_by, rows)

    print(f"grid_summary_csv: {csv_path}", flush=True)
    print(f"grid_summary_for_chatgpt: {txt_path}", flush=True)
    print(f"grid_total_points: {len(rows)}", flush=True)
    print(f"grid_failed_points: {sum(1 for row in rows if row.get('status') == 'failed' or row.get('failure_reason'))}", flush=True)
    return csv_path, txt_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan Radius x Conic for one LDE surface without Local Optimization or Hammer."
    )
    parser.add_argument("--base-lens", required=True, type=Path, help="Base .ZOS file reloaded for every grid point.")
    parser.add_argument("--surface", required=True, type=int, help="Surface number whose Radius and Conic are scanned.")
    parser.add_argument("--radii", nargs="+", required=True, type=float, help="Radius values to scan.")
    parser.add_argument("--conics", nargs="+", required=True, type=float, help="Conic values to scan.")
    parser.add_argument("--quick-focus", action="store_true", help="Run Quick Focus after setting Radius and Conic.")
    parser.add_argument("--label", default="radius_conic_grid_scan", help="Label used in run_id and summary filenames.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip a grid point when an existing matching result folder already has summary_for_chatgpt.txt.",
    )
    parser.add_argument("--sort-by", default="MTF40_min", choices=sorted(SORT_FIELDS), help="Grid summary sort key.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_radius_conic_grid(
        Path(__file__).resolve().parents[1],
        base_lens=args.base_lens,
        surface=args.surface,
        radii=tuple(args.radii),
        conics=tuple(args.conics),
        label=args.label,
        quick_focus=args.quick_focus,
        resume=args.resume,
        sort_by=args.sort_by,
    )
