from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from run_files import find_run_file
from scan_material import scan_material
from scan_thickness import scan_thickness
from scan_two_radii import scan_two_radii


DEFAULT_MATERIALS = [
    "H-FK61",
    "H-QK3L",
    "H-K9L",
    "H-BAK4",
    "H-ZK4",
    "H-LAK4L",
    "H-LAK10",
    "H-LAF51",
    "H-ZF3",
    "APL5014GH",
]

SUMMARY_FIELDS = [
    "stage",
    "run_id",
    "run_dir",
    "scanned_parameter",
    "scanned_material",
    "scanned_radius",
    "scanned_thickness",
    "scanned_radius_a",
    "scanned_radius_b",
    "MTF40_mean",
    "MTF50_mean",
    "MTF40_min",
    "MTF50_min",
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
    "L5_edge",
    "structure_status",
    "mtf_status",
    "status",
    "mtf_exported",
    "failure_reason",
]


def _read_summary(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line or line.startswith("["):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _warning_text(run_dir: Path) -> str:
    warnings_path = find_run_file(run_dir, "warnings")
    if not warnings_path.exists():
        return ""
    return " | ".join(line.strip() for line in warnings_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def _failure_reason(run_dir: Path, summary: dict[str, str], debug: dict[str, Any]) -> str:
    reasons: list[str] = []
    mtf_path = find_run_file(run_dir, "mtf_fft")
    if not mtf_path.exists() or mtf_path.stat().st_size == 0:
        reasons.append("MTF export failed")
    if summary.get("MTF40_mean", "null").lower() == "null" or summary.get("MTF50_mean", "null").lower() == "null":
        reasons.append("MTF summary fields are null")

    for key in ("system_error_message", "fftmtf_error_message"):
        value = debug.get(key)
        if value:
            reasons.append(str(value))

    warnings = _warning_text(run_dir)
    if warnings:
        reasons.append(warnings)

    return " | ".join(dict.fromkeys(reasons))


def _collect_run_row(stage: str, run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    summary_path = find_run_file(run_dir, "summary_for_chatgpt")
    debug_path = find_run_file(run_dir, "analysis_debug")
    summary = _read_summary(summary_path)
    debug = _read_json(debug_path)
    mtf_path = find_run_file(run_dir, "mtf_fft")
    failure = _failure_reason(run_dir, summary, debug)

    return {
        "stage": stage,
        "run_id": summary.get("run_id") or run_id,
        "run_dir": str(run_dir),
        "scanned_parameter": summary.get("scanned_parameter", "null"),
        "scanned_material": summary.get("scanned_material", "null"),
        "scanned_radius": summary.get("scanned_radius", "null"),
        "scanned_thickness": summary.get("scanned_thickness", "null"),
        "scanned_radius_a": summary.get("scanned_radius_a", "null"),
        "scanned_radius_b": summary.get("scanned_radius_b", "null"),
        "MTF40_mean": summary.get("MTF40_mean", "null"),
        "MTF50_mean": summary.get("MTF50_mean", "null"),
        "MTF40_min": summary.get("MTF40_min", "null"),
        "MTF50_min": summary.get("MTF50_min", "null"),
        "25T20": summary.get("25T20", "null"),
        "25T25": summary.get("25T25", "null"),
        "25T30": summary.get("25T30", "null"),
        "25T35": summary.get("25T35", "null"),
        "25T40": summary.get("25T40", "null"),
        "25T50": summary.get("25T50", "null"),
        "25S50": summary.get("25S50", "null"),
        "27p5T40": summary.get("27p5T40", "null"),
        "28T40": summary.get("28T40", "null"),
        "28T50": summary.get("28T50", "null"),
        "L5_edge": summary.get("L5_edge", "null"),
        "structure_status": summary.get("structure_status", "null"),
        "mtf_status": summary.get("mtf_status", "null"),
        "status": summary.get("status", "null"),
        "mtf_exported": mtf_path.exists() and mtf_path.stat().st_size > 0,
        "failure_reason": failure,
    }


def _near_zero_penalty(row: dict[str, Any]) -> float:
    values = [_to_float(row.get(key)) for key in ("25T25", "25T30", "25T35")]
    near_zero_count = sum(1 for value in values if value is not None and value < 0.01)
    if near_zero_count >= 2:
        return 1.0
    if near_zero_count == 1:
        return 0.5
    return 0.0


def _candidate_score(row: dict[str, Any]) -> float | None:
    required = ["MTF40_mean", "MTF50_mean", "25T40", "25T50", "25S50", "27p5T40", "28T40"]
    values = {key: _to_float(row.get(key)) for key in required}
    if any(value is None for value in values.values()):
        return None
    return (
        2.0 * values["MTF40_mean"]
        + 2.0 * values["MTF50_mean"]
        + 1.5 * values["25T40"]
        + 1.0 * values["25T50"]
        + 1.0 * values["25S50"]
        + 1.0 * values["27p5T40"]
        + 1.0 * values["28T40"]
        - 2.0 * _near_zero_penalty(row)
    )


def _candidate_exclusion(row: dict[str, Any]) -> str:
    checks = [
        (not bool(row.get("mtf_exported")), "MTF export failed"),
        ((_to_float(row.get("L5_edge")) or -math.inf) < 0.40, "L5_edge < 0.40"),
        ((_to_float(row.get("25S50")) or -math.inf) < 0.03, "25S50 < 0.03"),
        ((_to_float(row.get("MTF40_mean")) or -math.inf) < 0.095, "MTF40_mean < 0.095"),
        ((_to_float(row.get("MTF50_mean")) or -math.inf) < 0.09, "MTF50_mean < 0.09"),
    ]
    return "; ".join(reason for failed, reason in checks if failed)


def _best_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        exclusion = _candidate_exclusion(row)
        score = _candidate_score(row)
        item = {**row, "candidate_exclusion": exclusion, "score": score}
        if not exclusion and score is not None:
            candidates.append(item)
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _write_stage_text(path: Path, stage: str, base_lens: Path, rows: list[dict[str, Any]]) -> None:
    failed = [row for row in rows if row.get("failure_reason")]
    lines = [
        f"stage name: {stage}",
        f"base_lens: {base_lens}",
        f"run count: {len(rows)}",
        f"success count: {len(rows) - len(failed)}",
        f"failed count: {len(failed)}",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"run_id: {row.get('run_id')}",
                f"scanned_parameter: {row.get('scanned_parameter')}",
                f"scanned_material: {row.get('scanned_material')}",
                f"scanned_radius: {row.get('scanned_radius')}",
                f"scanned_thickness: {row.get('scanned_thickness')}",
                f"scanned_radius_a: {row.get('scanned_radius_a')}",
                f"scanned_radius_b: {row.get('scanned_radius_b')}",
                f"MTF40_mean: {row.get('MTF40_mean')}",
                f"MTF50_mean: {row.get('MTF50_mean')}",
                f"MTF40_min: {row.get('MTF40_min')}",
                f"MTF50_min: {row.get('MTF50_min')}",
                f"25T20: {row.get('25T20')}",
                f"25T25: {row.get('25T25')}",
                f"25T30: {row.get('25T30')}",
                f"25T35: {row.get('25T35')}",
                f"25T40: {row.get('25T40')}",
                f"25T50: {row.get('25T50')}",
                f"25S50: {row.get('25S50')}",
                f"27p5T40: {row.get('27p5T40')}",
                f"28T40: {row.get('28T40')}",
                f"28T50: {row.get('28T50')}",
                f"L5_edge: {row.get('L5_edge')}",
                f"structure_status: {row.get('structure_status')}",
                f"mtf_status: {row.get('mtf_status')}",
                f"status: {row.get('status')}",
                f"failure_reason: {row.get('failure_reason') or 'none'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_stage_action(project_root: Path, args: argparse.Namespace, label: str) -> None:
    quick_focus = not args.no_quick_focus
    if args.stage == "material_scan_debug":
        scan_material(
            project_root,
            base_lens=args.base_lens,
            allowed_materials_csv=args.allowed_materials_csv,
            label=label,
            values=[args.material],
            surface_comment="FF_FRONT",
            quick_focus=quick_focus,
        )
    elif args.stage == "material_scan_selected":
        scan_material(
            project_root,
            base_lens=args.base_lens,
            allowed_materials_csv=args.allowed_materials_csv,
            label=label,
            values=args.values or DEFAULT_MATERIALS,
            surface_comment="FF_FRONT",
            quick_focus=quick_focus,
        )
    elif args.stage == "ff_2d_radius_scan":
        scan_two_radii(
            project_root,
            base_lens=args.base_lens,
            values_a=(75.0, 100.0, 125.0),
            values_b=(-40.0, -42.0, -45.0),
            label=label,
            surface_comment_a="FF_FRONT",
            surface_comment_b="FF_BACK",
            quick_focus=quick_focus,
        )
    elif args.stage == "ff_gap_scan":
        scan_thickness(
            project_root,
            values=(0.15, 0.25, 0.35),
            label=label,
            surface_before_comment="FF_FRONT",
            quick_focus=quick_focus,
            base_lens=args.base_lens,
        )
    elif args.stage == "ff_to_filter_gap_scan":
        scan_thickness(
            project_root,
            values=(0.10, 0.20, 0.30),
            label=label,
            surface_comment="FF_BACK",
            quick_focus=quick_focus,
            base_lens=args.base_lens,
        )
    else:
        raise ValueError(f"Unsupported stage: {args.stage}")


def run_stage(project_root: Path, args: argparse.Namespace) -> Path:
    if not args.base_lens.exists():
        raise FileNotFoundError(f"Base lens not found: {args.base_lens}")
    if args.stage.startswith("material") and not args.allowed_materials_csv.exists():
        raise FileNotFoundError(f"Allowed materials CSV not found: {args.allowed_materials_csv}")

    stage_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.stage}"
    stage_dir = project_root / "stage_runs" / stage_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or args.stage

    results_dir = project_root / "results"
    before = {path.name for path in results_dir.iterdir() if path.is_dir()} if results_dir.exists() else set()
    stage_failure: str | None = None
    try:
        _run_stage_action(project_root, args, label)
    except Exception as exc:
        stage_failure = f"Stage execution failed: {type(exc).__name__}: {exc!r}"
        print(f"[ERROR] {stage_failure}", flush=True)

    after_dirs = sorted(path for path in results_dir.iterdir() if path.is_dir() and path.name not in before)
    rows = [_collect_run_row(args.stage, run_dir) for run_dir in after_dirs]
    if stage_failure and not rows:
        rows.append(
            {
                "stage": args.stage,
                "run_id": "",
                "run_dir": "",
                "failure_reason": stage_failure,
                "mtf_exported": False,
            }
        )

    failed_rows = [row for row in rows if row.get("failure_reason")]
    candidates = _best_candidates(rows)

    _write_csv(stage_dir / "stage_summary.csv", rows, SUMMARY_FIELDS)
    _write_csv(stage_dir / "failed_runs.csv", failed_rows, SUMMARY_FIELDS)
    _write_csv(stage_dir / "best_candidates.csv", candidates, [*SUMMARY_FIELDS, "candidate_exclusion", "score"])
    _write_stage_text(stage_dir / "stage_summary_for_chatgpt.txt", args.stage, args.base_lens, rows)

    print(f"stage_dir: {stage_dir}", flush=True)
    print(f"stage_summary: {stage_dir / 'stage_summary.csv'}", flush=True)
    print(f"stage_summary_for_chatgpt: {stage_dir / 'stage_summary_for_chatgpt.txt'}", flush=True)
    print(f"failed_runs: {stage_dir / 'failed_runs.csv'}", flush=True)
    print(f"best_candidates: {stage_dir / 'best_candidates.csv'}", flush=True)
    print(f"run_count: {len(rows)}", flush=True)
    print(f"failed_count: {len(failed_rows)}", flush=True)
    print(f"candidate_count: {len(candidates)}", flush=True)
    return stage_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a predefined scan stage and archive stage-level summaries.")
    parser.add_argument(
        "stage",
        choices=[
            "material_scan_debug",
            "material_scan_selected",
            "ff_2d_radius_scan",
            "ff_gap_scan",
            "ff_to_filter_gap_scan",
        ],
    )
    parser.add_argument("--base-lens", required=True, type=Path, help="Base lens copied/reloaded for every run.")
    parser.add_argument(
        "--allowed-materials-csv",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "allowed_materials_from_DJI_library.csv",
    )
    parser.add_argument("--material", default="H-FK61", help="Single material for material_scan_debug.")
    parser.add_argument("--values", nargs="+", help="Material list for material_scan_selected.")
    parser.add_argument("--label", help="Override run label. Defaults to stage name.")
    parser.add_argument("--no-quick-focus", action="store_true", help="Disable Quick Focus for this stage.")
    return parser.parse_args()


if __name__ == "__main__":
    run_stage(Path(__file__).resolve().parents[1], _parse_args())
