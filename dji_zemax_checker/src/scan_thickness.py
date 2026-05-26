from __future__ import annotations

import argparse
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
    _surface_at,
    resolve_surface_number,
)
from summarize_results import summarize_results


def thickness_token(value: float) -> str:
    prefix = "p" if value >= 0 else "m"
    return f"{prefix}{abs(value):g}".replace(".", "p")


def _unique_run_dir(project_root: Path, label: str, value: float) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{thickness_token(value)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _make_thickness_fixed(surface: Any) -> None:
    cell = safe_get(surface, "ThicknessCell")
    if cell is None:
        return

    for method_name in ("MakeSolveFixed", "MakeSolveNone"):
        try:
            method = getattr(cell, method_name)
        except Exception:
            method = None
        if callable(method):
            try:
                method()
                return
            except Exception:
                pass


def _set_thickness(surface: Any, value: float) -> None:
    surface.Thickness = value
    _make_thickness_fixed(surface)


def _surface_number_by_comment(oss: Any, comment: str) -> int:
    target = comment.strip().upper()
    matches: list[int] = []
    lde = oss.LDE
    for index in range(int(lde.NumberOfSurfaces)):
        surface = lde.GetSurfaceAt(index)
        if str(safe_get(surface, "Comment") or "").strip().upper() == target:
            matches.append(index)

    if not matches:
        raise ValueError(f"Could not find any surface with Comment={comment!r}.")
    if len(matches) > 1:
        raise ValueError(f"Found multiple surfaces with Comment={comment!r}: {matches}. Use --surface.")
    return matches[0]


def _resolve_thickness_surface(
    oss: Any,
    surface: int | None,
    surface_comment: str | None,
    surface_before_comment: str | None,
) -> tuple[int, str, str | None]:
    if surface_before_comment:
        comment_surface = _surface_number_by_comment(oss, surface_before_comment)
        if comment_surface <= 1:
            raise ValueError(
                f"Surface with Comment={surface_before_comment!r} is surface {comment_surface}; "
                "there is no valid previous thickness surface."
            )
        return comment_surface - 1, "surface_before_comment", surface_before_comment

    mode = "surface_comment" if surface_comment else "surface"
    return resolve_surface_number(oss, surface, surface_comment), mode, surface_comment


def scan_thickness(
    project_root: Path,
    values: tuple[float, ...],
    label: str,
    surface: int | None = None,
    surface_comment: str | None = None,
    surface_before_comment: str | None = None,
    quick_focus: bool = False,
    base_lens: Path | None = None,
) -> None:
    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)

    if base_lens is not None:
        if not base_lens.exists():
            raise FileNotFoundError(f"Base lens not found: {base_lens}")
        baseline_path = base_lens
    else:
        baseline_path = scan_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}_baseline.zos"
        oss.save_as(baseline_path)
        print(f"Saved baseline copy: {baseline_path}", flush=True)

    try:
        oss.load(baseline_path, saveifneeded=False)
        resolved_surface_number, scanned_mode, target_comment = _resolve_thickness_surface(
            oss,
            surface,
            surface_comment,
            surface_before_comment,
        )
        resolved_surface = _surface_at(oss, resolved_surface_number)
        resolved_surface_comment = str(safe_get(resolved_surface, "Comment") or "")
        print(
            "Scanning thickness surface:",
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
        for value in values:
            oss.load(baseline_path, saveifneeded=False)
            target_surface = _surface_at(oss, resolved_surface_number)
            target_comment = str(safe_get(target_surface, "Comment") or "")
            _set_thickness(target_surface, value)
            oss.update_status()

            run_id, run_dir = _unique_run_dir(project_root, label, value)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)

            quick_focus_warning = None
            if quick_focus:
                quick_focus_warning = _run_quick_focus(oss)
                target_surface = _surface_at(oss, resolved_surface_number)
                if abs(float(target_surface.Thickness) - value) > 1e-9:
                    _set_thickness(target_surface, value)
                    extra_warning = (
                        "Quick Focus changed the scanned thickness; "
                        f"restored surface {resolved_surface_number} Thickness to {value:g}."
                    )
                    quick_focus_warning = (
                        extra_warning if quick_focus_warning is None else f"{quick_focus_warning} {extra_warning}"
                    )
                oss.update_status()
                oss.save_as(copy_path)
                if quick_focus_warning:
                    _append_warning(run_dir, run_id, quick_focus_warning)

            extra_metadata = {
                "label": label,
                "scanned_parameter": "Thickness",
                "scanned_mode": scanned_mode,
                "target_comment": target_comment,
                "scanned_surface": resolved_surface_number,
                "scanned_surface_comment": target_comment or resolved_surface_comment,
                "scanned_thickness": value,
                "quick_focus": quick_focus,
                "quick_focus_warning": quick_focus_warning,
                "base_lens": str(baseline_path),
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
    parser = argparse.ArgumentParser(description="Generic conservative surface thickness scan without optimization.")
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--surface", type=int, help="Surface number to scan.")
    locator.add_argument("--surface-comment", help="Surface Comment text to locate.")
    locator.add_argument("--surface-before-comment", help="Find this Comment and scan the previous surface Thickness.")
    parser.add_argument("--values", nargs="+", required=True, type=float, help="Thickness values to scan.")
    parser.add_argument("--label", default="thickness_scan", help="Label used in run_id and scan copy names.")
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting thickness.")
    parser.add_argument("--base-lens", type=Path, help="Optional base lens path to reload before each scan point.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_thickness(
        Path(__file__).resolve().parents[1],
        tuple(args.values),
        label=args.label,
        surface=args.surface,
        surface_comment=args.surface_comment,
        surface_before_comment=args.surface_before_comment,
        quick_focus=args.quick_focus,
        base_lens=args.base_lens,
    )
