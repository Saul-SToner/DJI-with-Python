from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from build_scan_report import build_report
from export_surfaces import safe_get
from scan_radius import (
    _append_warning,
    _export_current_point,
    _run_quick_focus,
    _safe_label,
    _set_radius,
    _surface_at,
    resolve_surface_number,
)
from scan_radius_conic_grid import (
    SORT_FIELDS,
    _failure_row,
    _read_run_row,
    _sort_rows,
    _to_float,
    _value_token,
    _write_grid_csv,
)
from summarize_results import summarize_results


def _combo_suffix(label: str, surface_a: int, value_a: float, surface_b: int, value_b: float) -> str:
    return (
        f"{_safe_label(label)}_S{surface_a}R_{_value_token(value_a)}"
        f"_S{surface_b}R_{_value_token(value_b)}"
    )


def _unique_run_dir(
    project_root: Path,
    label: str,
    surface_a: int,
    value_a: float,
    surface_b: int,
    value_b: float,
) -> tuple[str, Path]:
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_combo_suffix(label, surface_a, value_a, surface_b, value_b)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _write_grid_text(
    path: Path,
    label: str,
    base_lens: Path,
    surface_a: int,
    comment_a: str,
    values_a: tuple[float, ...],
    surface_b: int,
    comment_b: str,
    values_b: tuple[float, ...],
    sort_by: str,
    rows: list[dict[str, Any]],
) -> None:
    failed = [row for row in rows if row.get("status") == "failed" or row.get("failure_reason")]
    sorted_rows = _sort_rows(rows, sort_by)
    lines = [
        f"label: {label}",
        f"base_lens: {base_lens}",
        "scanned_mode: radius_pair_grid",
        f"surface_a: {surface_a}",
        f"surface_comment_a: {comment_a}",
        "values_a: " + ", ".join(f"{value:g}" for value in values_a),
        f"surface_b: {surface_b}",
        f"surface_comment_b: {comment_b}",
        "values_b: " + ", ".join(f"{value:g}" for value in values_b),
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
                f"radius_a: {row.get('scanned_radius_a')}",
                f"radius_b: {row.get('scanned_radius_b')}",
                f"score: {row.get('score')}",
                f"MTF40_min: {row.get('MTF40_min')}",
                f"MTF40_mean: {row.get('MTF40_mean')}",
                f"MTF50_min: {row.get('MTF50_min')}",
                f"MTF50_mean: {row.get('MTF50_mean')}",
                f"25T25: {row.get('25T25')}",
                f"25T30: {row.get('25T30')}",
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


def _pair_row(
    run_id: str,
    run_dir: Path,
    surface_a: int,
    comment_a: str,
    value_a: float,
    surface_b: int,
    comment_b: str,
    value_b: float,
    failure_reason: str = "",
) -> dict[str, Any]:
    row = _read_run_row(run_id, run_dir, surface_a, comment_a, value_a, value_b, failure_reason=failure_reason)
    row["scanned_parameter"] = "RadiusPairGrid"
    row["scanned_mode"] = "radius_pair_grid"
    row["scanned_surface_a"] = surface_a
    row["scanned_surface_comment_a"] = comment_a
    row["scanned_radius_a"] = value_a
    row["scanned_surface_b"] = surface_b
    row["scanned_surface_comment_b"] = comment_b
    row["scanned_radius_b"] = value_b
    return row


def _pair_failure_row(
    run_id: str,
    run_dir: Path,
    surface_a: int,
    comment_a: str,
    value_a: float,
    surface_b: int,
    comment_b: str,
    value_b: float,
    scan_lens: Path | None,
    failure_reason: str,
) -> dict[str, Any]:
    row = _failure_row(run_id, run_dir, surface_a, comment_a, value_a, value_b, scan_lens, failure_reason)
    row["scanned_parameter"] = "RadiusPairGrid"
    row["scanned_mode"] = "radius_pair_grid"
    row["scanned_surface_a"] = surface_a
    row["scanned_surface_comment_a"] = comment_a
    row["scanned_radius_a"] = value_a
    row["scanned_surface_b"] = surface_b
    row["scanned_surface_comment_b"] = comment_b
    row["scanned_radius_b"] = value_b
    return row


def scan_radius_pair_grid(
    project_root: Path,
    base_lens: Path,
    surface_a: int,
    values_a: tuple[float, ...],
    surface_b: int,
    values_b: tuple[float, ...],
    label: str,
    quick_focus: bool,
    sort_by: str,
) -> tuple[Path, Path, Path]:
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
        resolved_a = resolve_surface_number(oss, surface_a, None)
        resolved_b = resolve_surface_number(oss, surface_b, None)
        comment_a = str(safe_get(_surface_at(oss, resolved_a), "Comment") or "")
        comment_b = str(safe_get(_surface_at(oss, resolved_b), "Comment") or "")
        print(
            "Scanning radius pair grid:",
            f"surface_a={resolved_a} comment={comment_a!r}",
            f"surface_b={resolved_b} comment={comment_b!r}",
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
        for value_a in values_a:
            for value_b in values_b:
                run_id, run_dir = _unique_run_dir(project_root, label, resolved_a, value_a, resolved_b, value_b)
                copy_path: Path | None = None
                try:
                    oss.load(base_lens, saveifneeded=False)
                    target_a = _surface_at(oss, resolved_a)
                    target_b = _surface_at(oss, resolved_b)
                    _set_radius(target_a, value_a)
                    _set_radius(target_b, value_b)
                    oss.update_status()

                    copy_path = scan_dir / f"{run_id}.zos"
                    oss.save_as(copy_path)
                    print(f"Saved scan copy: {copy_path}", flush=True)

                    quick_focus_warning = None
                    if quick_focus:
                        quick_focus_warning = _run_quick_focus(oss)
                        target_a = _surface_at(oss, resolved_a)
                        target_b = _surface_at(oss, resolved_b)
                        actual_a = _to_float(safe_get(target_a, "Radius"))
                        actual_b = _to_float(safe_get(target_b, "Radius"))
                        restored: list[str] = []
                        if actual_a is None or abs(actual_a - value_a) > 1e-9:
                            _set_radius(target_a, value_a)
                            restored.append(f"S{resolved_a} Radius restored to {value_a:g}")
                        if actual_b is None or abs(actual_b - value_b) > 1e-9:
                            _set_radius(target_b, value_b)
                            restored.append(f"S{resolved_b} Radius restored to {value_b:g}")
                        if restored:
                            message = "Quick Focus changed scanned radii; " + "; ".join(restored) + "."
                            quick_focus_warning = (
                                message if quick_focus_warning is None else f"{quick_focus_warning} {message}"
                            )
                        oss.update_status()
                        oss.save_as(copy_path)
                        if quick_focus_warning:
                            _append_warning(run_dir, run_id, quick_focus_warning)

                    extra_metadata = {
                        "label": label,
                        "scanned_parameter": "RadiusPairGrid",
                        "scanned_mode": "radius_pair_grid",
                        "scanned_surface": resolved_a,
                        "scanned_surface_comment": comment_a,
                        "scanned_surface_a": resolved_a,
                        "scanned_surface_comment_a": comment_a,
                        "scanned_radius_a": value_a,
                        "scanned_surface_b": resolved_b,
                        "scanned_surface_comment_b": comment_b,
                        "scanned_radius_b": value_b,
                        "quick_focus": quick_focus,
                        "quick_focus_warning": quick_focus_warning,
                        "base_lens": str(base_lens),
                        "scan_lens": str(copy_path),
                        "scan_copy_file": str(copy_path),
                    }
                    _export_current_point(oss, run_id, run_dir, extra_metadata)
                    rows.append(
                        _pair_row(run_id, run_dir, resolved_a, comment_a, value_a, resolved_b, comment_b, value_b)
                    )
                except Exception as exc:
                    failure_reason = f"{type(exc).__name__}: {exc!r}"
                    print(f"[ERROR] {run_id} failed: {failure_reason}", flush=True)
                    try:
                        _append_warning(run_dir, run_id, f"radius pair grid point failed: {failure_reason}")
                    except Exception:
                        pass
                    rows.append(
                        _pair_failure_row(
                            run_id,
                            run_dir,
                            resolved_a,
                            comment_a,
                            value_a,
                            resolved_b,
                            comment_b,
                            value_b,
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
    _write_grid_text(
        txt_path,
        label,
        base_lens,
        resolved_a,
        comment_a,
        values_a,
        resolved_b,
        comment_b,
        values_b,
        sort_by,
        rows,
    )

    report_md, _ = build_report(
        grid_summary_csv=csv_path,
        grid_summary_txt=txt_path,
        source_log=None,
        top_n=10,
        sort_by=sort_by,
        decision_note=f"Radius pair grid: S{resolved_a}R x S{resolved_b}R",
        out_dir=project_root / "reports",
    )

    print(f"grid_summary_csv: {csv_path}", flush=True)
    print(f"grid_summary_for_chatgpt: {txt_path}", flush=True)
    print(f"analysis_report: {report_md}", flush=True)
    print(f"grid_total_points: {len(rows)}", flush=True)
    print(f"grid_failed_points: {sum(1 for row in rows if row.get('status') == 'failed' or row.get('failure_reason'))}", flush=True)
    return csv_path, txt_path, report_md


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Radius x Radius for two LDE surfaces.")
    parser.add_argument("--base-lens", required=True, type=Path, help="Base .ZOS file reloaded for every grid point.")
    parser.add_argument("--surface-a", required=True, type=int, help="First surface number.")
    parser.add_argument("--values-a", nargs="+", required=True, type=float, help="Radius values for surface A.")
    parser.add_argument("--surface-b", required=True, type=int, help="Second surface number.")
    parser.add_argument("--values-b", nargs="+", required=True, type=float, help="Radius values for surface B.")
    parser.add_argument("--quick-focus", action="store_true", help="Run Quick Focus after setting both radii.")
    parser.add_argument("--label", default="radius_pair_grid", help="Label used in run_id and summary filenames.")
    parser.add_argument("--sort-by", default="score", choices=sorted(SORT_FIELDS), help="Grid summary/report sort key.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_radius_pair_grid(
        Path(__file__).resolve().parents[1],
        base_lens=args.base_lens,
        surface_a=args.surface_a,
        values_a=tuple(args.values_a),
        surface_b=args.surface_b,
        values_b=tuple(args.values_b),
        label=args.label,
        quick_focus=args.quick_focus,
        sort_by=args.sort_by,
    )
