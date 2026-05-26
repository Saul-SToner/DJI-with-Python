from __future__ import annotations

import argparse
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from console_summary import print_run_console_summary
from export_chatgpt_summary import export_chatgpt_summary
from export_mtf import export_mtf
from export_surfaces import export_surfaces, safe_get
from export_system_summary import export_system_summary
from manufacturing_check import export_manufacturing_check
from run_files import run_file
from run_metadata import export_run_metadata, load_run_metadata
from summarize_results import summarize_results


def parse_radius_value(text: str) -> float:
    normalized = text.strip().lower()
    if normalized in {"inf", "+inf", "infinity", "+infinity"}:
        return math.inf
    if normalized in {"-inf", "-infinity"}:
        return -math.inf
    return float(text)


def radius_token(value: float) -> str:
    if math.isinf(value):
        return "inf"
    prefix = "p" if value >= 0 else "m"
    return f"{prefix}{abs(value):g}".replace(".", "p")


def _safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_+-]+", "_", label.strip()).strip("_") or "radius_scan"


def _unique_run_dir(project_root: Path, label: str, value: float) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{radius_token(value)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _append_warning(output_dir: Path, run_id: str, message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with run_file(output_dir, run_id, "warnings").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _surface_at(oss: Any, surface_number: int) -> Any:
    lde = oss.LDE
    count = int(lde.NumberOfSurfaces)
    if surface_number < 0 or surface_number >= count:
        raise ValueError(f"Surface {surface_number} is out of range. NumberOfSurfaces={count}.")
    return lde.GetSurfaceAt(surface_number)


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


def resolve_surface_number(oss: Any, surface: int | None, surface_comment: str | None) -> int:
    if surface is None and not surface_comment:
        raise ValueError("Specify either --surface or --surface-comment.")
    if surface_comment:
        return _surface_number_by_comment(oss, surface_comment)
    assert surface is not None
    _surface_at(oss, surface)
    return surface


def _make_radius_fixed(surface: Any) -> None:
    cell = safe_get(surface, "RadiusCell")
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


def _set_radius(surface: Any, value: float) -> None:
    surface.Radius = value
    _make_radius_fixed(surface)


def _run_quick_focus(oss: Any) -> str | None:
    tool = None
    try:
        tool = oss.Tools.OpenQuickFocus()
        tool.RunAndWaitForCompletion()
        if not bool(safe_get(tool, "Succeeded", True)):
            return f"Quick Focus did not succeed: {safe_get(tool, 'ErrorMessage')}"
        return None
    except Exception as exc:
        return f"Quick Focus failed: {repr(exc)}"
    finally:
        if tool is not None:
            try:
                tool.Close()
            except Exception:
                pass


def _export_current_point(
    oss: Any,
    run_id: str,
    run_dir: Path,
    extra_metadata: dict[str, Any],
) -> tuple[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    export_time = datetime.now().isoformat(timespec="seconds")
    metadata: dict[str, Any] = {}
    surfaces: list[dict[str, Any]] = []

    try:
        metadata_path = run_file(run_dir, run_id, "run_metadata")
        metadata = export_run_metadata(
            oss,
            metadata_path,
            run_id,
            export_time,
            output_folder=run_dir,
            extra=extra_metadata,
        )
        metadata = load_run_metadata(metadata_path)
        print("Exported:", metadata_path, flush=True)
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export run_metadata.json: {repr(exc)}")

    try:
        surfaces_path = run_file(run_dir, run_id, "surfaces")
        surfaces = export_surfaces(oss, surfaces_path, run_metadata=metadata)
        print("Exported:", surfaces_path, flush=True)
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export surfaces.csv: {repr(exc)}")

    try:
        system_summary_path = run_file(run_dir, run_id, "system_summary")
        export_system_summary(oss, system_summary_path, run_metadata=metadata)
        print("Exported:", system_summary_path, flush=True)
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export system_summary.json: {repr(exc)}")

    try:
        mtf_path = run_file(run_dir, run_id, "mtf_fft")
        if export_mtf(oss, mtf_path, run_metadata=metadata):
            print("Exported:", mtf_path, flush=True)
        else:
            _append_warning(run_dir, run_id, "Failed to export mtf_fft.csv")
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export mtf_fft.csv: {repr(exc)}")

    try:
        if not surfaces:
            surfaces = export_surfaces(oss, run_file(run_dir, run_id, "surfaces"), run_metadata=metadata)
        manufacturing_path = run_file(run_dir, run_id, "manufacturing_check")
        export_manufacturing_check(surfaces, manufacturing_path, run_metadata=metadata)
        print("Exported:", manufacturing_path, flush=True)
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export manufacturing_check.json: {repr(exc)}")

    try:
        summary_path = run_file(run_dir, run_id, "summary_for_chatgpt")
        export_chatgpt_summary(run_dir, run_id, summary_path)
        print("Exported:", summary_path, flush=True)
    except Exception as exc:
        _append_warning(run_dir, run_id, f"Failed to export summary_for_chatgpt.txt: {repr(exc)}")

    print_run_console_summary(run_dir, run_id)
    return run_id, run_dir


def scan_radius(
    project_root: Path,
    values: tuple[float, ...],
    label: str,
    surface: int | None = None,
    surface_comment: str | None = None,
    quick_focus: bool = False,
    base_lens: Path | None = None,
) -> None:
    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    baseline_path: Path | None = None
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
        if baseline_path is not None:
            oss.load(baseline_path, saveifneeded=False)
        resolved_surface_number = resolve_surface_number(oss, surface, surface_comment)
        resolved_surface = _surface_at(oss, resolved_surface_number)
        resolved_surface_comment = str(safe_get(resolved_surface, "Comment") or "")
        print(
            "Scanning surface:",
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
            if baseline_path is not None:
                oss.load(baseline_path, saveifneeded=False)

            target_surface = _surface_at(oss, resolved_surface_number)
            target_comment = str(safe_get(target_surface, "Comment") or "")
            _set_radius(target_surface, value)
            oss.update_status()

            run_id, run_dir = _unique_run_dir(project_root, label, value)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)

            quick_focus_warning = None
            if quick_focus:
                quick_focus_warning = _run_quick_focus(oss)
                oss.update_status()
                oss.save_as(copy_path)
                if quick_focus_warning:
                    _append_warning(run_dir, run_id, quick_focus_warning)

            extra_metadata = {
                "label": label,
                "scanned_parameter": "Radius",
                "scanned_surface": resolved_surface_number,
                "scanned_surface_comment": target_comment or resolved_surface_comment,
                "scanned_radius": "inf" if math.isinf(value) else value,
                "quick_focus": quick_focus,
                "quick_focus_warning": quick_focus_warning,
                "base_lens": str(baseline_path) if baseline_path is not None else None,
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
    parser = argparse.ArgumentParser(description="Generic conservative surface radius scan without optimization.")
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--surface", type=int, help="Surface number to scan.")
    locator.add_argument("--surface-comment", help="Surface Comment text to locate.")
    parser.add_argument("--values", nargs="+", required=True, type=parse_radius_value, help="Radius values, including inf/infinity.")
    parser.add_argument("--label", default="radius_scan", help="Label used in run_id and scan copy names.")
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting radius.")
    parser.add_argument("--base-lens", type=Path, help="Optional base lens path to reload before each scan point.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_radius(
        Path(__file__).resolve().parents[1],
        tuple(args.values),
        label=args.label,
        surface=args.surface,
        surface_comment=args.surface_comment,
        quick_focus=args.quick_focus,
        base_lens=args.base_lens,
    )
