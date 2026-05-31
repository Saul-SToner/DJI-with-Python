from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from export_surfaces import safe_get
from scan_radius import _export_current_point, _safe_label, _surface_at
from scan_thickness import _set_thickness, thickness_token
from summarize_results import summarize_results


DEFAULT_SHIFTS = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)


def _unique_run_dir(project_root: Path, label: str, shift: float) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{thickness_token(shift)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _image_before_surface_number(oss: Any) -> int:
    lde = oss.LDE
    image_surface = int(lde.NumberOfSurfaces) - 1
    if image_surface <= 0:
        raise RuntimeError("Could not locate the surface before image.")
    return image_surface - 1


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Image-before surface thickness is not numeric: {value!r}") from exc


def scan_image_plane(
    project_root: Path,
    base_lens: Path,
    shifts: tuple[float, ...] = DEFAULT_SHIFTS,
    label: str = "image_plane_scan",
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
        image_before_surface = _image_before_surface_number(oss)
        image_before = _surface_at(oss, image_before_surface)
        original_thickness = _to_float(safe_get(image_before, "Thickness"))
        image_before_comment = str(safe_get(image_before, "Comment") or "")
        print(
            "Scanning image plane via surface:",
            image_before_surface,
            f"comment={image_before_comment!r}",
            f"original_thickness={original_thickness:g}",
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
        for shift in shifts:
            oss.load(base_lens, saveifneeded=False)
            image_before = _surface_at(oss, image_before_surface)
            new_thickness = original_thickness + shift
            _set_thickness(image_before, new_thickness)
            oss.update_status()

            run_id, run_dir = _unique_run_dir(project_root, label, shift)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)

            extra_metadata = {
                "label": label,
                "scanned_parameter": "ImagePlaneShift",
                "scanned_surface": image_before_surface,
                "scanned_surface_comment": image_before_comment,
                "image_shift": shift,
                "original_image_thickness": original_thickness,
                "new_image_thickness": new_thickness,
                "quick_focus": False,
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
    parser = argparse.ArgumentParser(description="Scan image plane by changing the thickness before image.")
    parser.add_argument("--base-lens", required=True, type=Path, help="Base lens loaded before each scan point.")
    parser.add_argument("--values", nargs="+", type=float, default=DEFAULT_SHIFTS, help="Relative image shifts in mm.")
    parser.add_argument("--label", default="image_plane_scan", help="Label used in run_id and scan copy names.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_image_plane(
        Path(__file__).resolve().parents[1],
        base_lens=args.base_lens,
        shifts=tuple(args.values),
        label=args.label,
    )
