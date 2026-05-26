from __future__ import annotations

from pathlib import Path

from scan_l5_back_radius import (
    _append_warning,
    _l5_surfaces,
    _run_exports,
    FIXED_L5_CENTER_THICKNESS,
)
from summarize_results import summarize_results

import zospy as zp


BASELINE_NAME = "l5_ct_1p10.zos"
ABS_RADIUS_VALUES = (4.5, 4.6, 4.7, 4.8, 4.9, 5.0)


def _safe_run_id(abs_radius: float) -> str:
    return f"l5_ct_1p10_rback_fine_{abs_radius:.1f}".replace(".", "p")


def scan_l5_back_radius_fine(project_root: Path) -> None:
    baseline_path = project_root / "scan_runs" / BASELINE_NAME
    if not baseline_path.exists():
        raise FileNotFoundError(f"Baseline file not found: {baseline_path}")

    zos = zp.ZOS()
    oss = zos.connect("extension")

    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)

    oss.load(baseline_path, saveifneeded=False)
    _, l5_back = _l5_surfaces(oss)
    sign = -1.0 if float(l5_back.Radius) < 0 else 1.0

    for abs_radius in ABS_RADIUS_VALUES:
        radius = sign * abs_radius
        run_id = _safe_run_id(abs_radius)
        output_dir = project_root / "results" / run_id
        copy_path = scan_dir / f"{run_id}.zos"

        try:
            l5_front, l5_back = _l5_surfaces(oss)
            l5_front.Thickness = FIXED_L5_CENTER_THICKNESS
            l5_back.Radius = radius
            oss.update_status()
            oss.save_as(copy_path)
            _run_exports(oss, output_dir)
            print(f"Completed {run_id}: R={radius:g}, {copy_path}")
        except Exception as exc:
            _append_warning(output_dir, f"Scan point {run_id} failed: {repr(exc)}")
            print(f"[WARNING] Scan point {run_id} failed: {repr(exc)}")

    summarize_results(project_root)


if __name__ == "__main__":
    scan_l5_back_radius_fine(Path(__file__).resolve().parents[1])
