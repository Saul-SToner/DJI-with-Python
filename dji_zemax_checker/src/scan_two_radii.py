from __future__ import annotations

import argparse
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from export_surfaces import safe_get
from scan_radius import (
    _append_warning,
    _export_current_point,
    _run_quick_focus,
    _safe_label,
    _set_radius,
    _surface_at,
    parse_radius_value,
    radius_token,
    resolve_surface_number,
)
from summarize_results import summarize_results


def _surface_label(surface_number: int, comment: str) -> str:
    return _safe_label(comment) if comment.strip() else f"S{surface_number}"


def _unique_run_dir(
    project_root: Path,
    label: str,
    surface_a: int,
    comment_a: str,
    value_a: float,
    surface_b: int,
    comment_b: str,
    value_b: float,
) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    a_label = _surface_label(surface_a, comment_a)
    b_label = _surface_label(surface_b, comment_b)
    base = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_"
        f"{a_label}_{radius_token(value_a)}_{b_label}_{radius_token(value_b)}"
    )
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _radius_equal(left: Any, right: float) -> bool:
    try:
        left_float = float(left)
    except (TypeError, ValueError):
        return False

    if math.isinf(right):
        return math.isinf(left_float)
    return abs(left_float - right) <= 1e-9


def _scan_value(value: float) -> str | float:
    return "inf" if math.isinf(value) else value


def scan_two_radii(
    project_root: Path,
    base_lens: Path,
    values_a: tuple[float, ...],
    values_b: tuple[float, ...],
    label: str,
    surface_a: int | None = None,
    surface_comment_a: str | None = None,
    surface_b: int | None = None,
    surface_comment_b: str | None = None,
    quick_focus: bool = False,
) -> None:
    if not base_lens.exists():
        raise FileNotFoundError(f"Base lens not found: {base_lens}")

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)

    try:
        oss.load(base_lens, saveifneeded=False)
        surface_number_a = resolve_surface_number(oss, surface_a, surface_comment_a)
        surface_number_b = resolve_surface_number(oss, surface_b, surface_comment_b)
        if surface_number_a == surface_number_b:
            raise ValueError(f"A and B resolve to the same surface: {surface_number_a}.")

        comment_a = str(safe_get(_surface_at(oss, surface_number_a), "Comment") or "")
        comment_b = str(safe_get(_surface_at(oss, surface_number_b), "Comment") or "")
        print(
            "Scanning radii:",
            f"A=S{surface_number_a} comment={comment_a!r}",
            f"B=S{surface_number_b} comment={comment_b!r}",
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
                oss.load(base_lens, saveifneeded=False)
                target_a = _surface_at(oss, surface_number_a)
                target_b = _surface_at(oss, surface_number_b)
                _set_radius(target_a, value_a)
                _set_radius(target_b, value_b)
                oss.update_status()

                run_id, run_dir = _unique_run_dir(
                    project_root,
                    label,
                    surface_number_a,
                    comment_a,
                    value_a,
                    surface_number_b,
                    comment_b,
                    value_b,
                )
                copy_path = scan_dir / f"{run_id}.zos"
                oss.save_as(copy_path)
                print(f"Saved scan copy: {copy_path}", flush=True)

                quick_focus_warning = None
                if quick_focus:
                    quick_focus_warning = _run_quick_focus(oss)
                    target_a = _surface_at(oss, surface_number_a)
                    target_b = _surface_at(oss, surface_number_b)
                    restore_messages: list[str] = []
                    if not _radius_equal(safe_get(target_a, "Radius"), value_a):
                        _set_radius(target_a, value_a)
                        restore_messages.append(
                            f"Quick Focus changed A radius; restored S{surface_number_a} Radius to {_scan_value(value_a)}."
                        )
                    if not _radius_equal(safe_get(target_b, "Radius"), value_b):
                        _set_radius(target_b, value_b)
                        restore_messages.append(
                            f"Quick Focus changed B radius; restored S{surface_number_b} Radius to {_scan_value(value_b)}."
                        )
                    if restore_messages:
                        restore_warning = " ".join(restore_messages)
                        quick_focus_warning = (
                            restore_warning
                            if quick_focus_warning is None
                            else f"{quick_focus_warning} {restore_warning}"
                        )
                    oss.update_status()
                    oss.save_as(copy_path)
                    if quick_focus_warning:
                        _append_warning(run_dir, run_id, quick_focus_warning)

                extra_metadata = {
                    "label": label,
                    "scanned_parameter": "TwoRadii",
                    "scanned_surface_a": surface_number_a,
                    "scanned_surface_comment_a": comment_a,
                    "scanned_radius_a": _scan_value(value_a),
                    "scanned_surface_b": surface_number_b,
                    "scanned_surface_comment_b": comment_b,
                    "scanned_radius_b": _scan_value(value_b),
                    "quick_focus": quick_focus,
                    "quick_focus_warning": quick_focus_warning,
                    "base_lens": str(base_lens),
                    "scan_lens": str(copy_path),
                    "scan_copy_file": str(copy_path),
                }
                _export_current_point(oss, run_id, run_dir, extra_metadata)

        summarize_results(project_root)
    finally:
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
        except Exception as exc:
            print(f"[WARNING] Failed to restore original file: {repr(exc)}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-surface fixed radius grid scan without optimization.")
    group_a = parser.add_mutually_exclusive_group(required=True)
    group_a.add_argument("--surface-a", type=int, help="Surface number for radius A.")
    group_a.add_argument("--surface-comment-a", help="Surface Comment text for radius A.")
    group_b = parser.add_mutually_exclusive_group(required=True)
    group_b.add_argument("--surface-b", type=int, help="Surface number for radius B.")
    group_b.add_argument("--surface-comment-b", help="Surface Comment text for radius B.")
    parser.add_argument("--values-a", nargs="+", required=True, type=parse_radius_value, help="Radius values for A.")
    parser.add_argument("--values-b", nargs="+", required=True, type=parse_radius_value, help="Radius values for B.")
    parser.add_argument("--base-lens", required=True, type=Path, help="Base lens loaded before each grid point.")
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting both radii.")
    parser.add_argument("--label", default="two_radius_scan", help="Label used in run_id and scan copy names.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_two_radii(
        Path(__file__).resolve().parents[1],
        base_lens=args.base_lens,
        values_a=tuple(args.values_a),
        values_b=tuple(args.values_b),
        label=args.label,
        surface_a=args.surface_a,
        surface_comment_a=args.surface_comment_a,
        surface_b=args.surface_b,
        surface_comment_b=args.surface_comment_b,
        quick_focus=args.quick_focus,
    )
