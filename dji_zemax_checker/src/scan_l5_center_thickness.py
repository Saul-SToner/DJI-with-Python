from __future__ import annotations

from pathlib import Path
from typing import Any

import zospy as zp

from export_mtf import export_mtf
from export_surfaces import export_surfaces, safe_get
from export_system_summary import export_system_summary
from manufacturing_check import export_manufacturing_check
from run_metadata import export_run_metadata
from run_files import run_file
from summarize_results import summarize_results


THICKNESS_VALUES = (0.90, 1.00, 1.10, 1.20, 1.30)


def _append_warning(output_dir: Path, message: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with run_file(output_dir, output_dir.name, "warnings").open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _run_exports(oss: Any, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    surfaces = []
    metadata = {}
    run_id = output_dir.name

    try:
        metadata = export_run_metadata(oss, run_file(output_dir, run_id, "run_metadata"), run_id, output_folder=output_dir)
    except Exception as exc:
        _append_warning(output_dir, f"Failed to export run_metadata.json: {repr(exc)}")

    try:
        surfaces = export_surfaces(oss, run_file(output_dir, run_id, "surfaces"), run_metadata=metadata)
    except Exception as exc:
        _append_warning(output_dir, f"Failed to export surfaces.csv: {repr(exc)}")

    try:
        export_system_summary(oss, run_file(output_dir, run_id, "system_summary"), run_metadata=metadata)
    except Exception as exc:
        _append_warning(output_dir, f"Failed to export system_summary.json: {repr(exc)}")

    try:
        if not export_mtf(oss, run_file(output_dir, run_id, "mtf_fft"), run_metadata=metadata):
            _append_warning(output_dir, "Failed to export mtf_fft.csv")
    except Exception as exc:
        _append_warning(output_dir, f"Failed to export mtf_fft.csv: {repr(exc)}")

    try:
        if not surfaces:
            surfaces = export_surfaces(oss, run_file(output_dir, run_id, "surfaces"), run_metadata=metadata)
        export_manufacturing_check(surfaces, run_file(output_dir, run_id, "manufacturing_check"), run_metadata=metadata)
    except Exception as exc:
        _append_warning(output_dir, f"Failed to export manufacturing_check.json: {repr(exc)}")


def _find_l5_front_surface(oss: Any) -> Any:
    lde = oss.LDE
    for index in range(lde.NumberOfSurfaces):
        surface = lde.GetSurfaceAt(index)
        if str(safe_get(surface, "Comment") or "").strip().upper() == "L5":
            return surface
    raise RuntimeError("Could not find L5 front surface by comment.")


def _safe_run_id(thickness: float) -> str:
    return f"l5_ct_{thickness:.2f}".replace(".", "p")


def scan_l5_center_thickness(project_root: Path) -> None:
    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    l5_front = _find_l5_front_surface(oss)
    original_thickness = float(l5_front.Thickness)

    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)

    try:
        for thickness in THICKNESS_VALUES:
            run_id = _safe_run_id(thickness)
            output_dir = project_root / "results" / run_id
            copy_path = scan_dir / f"{run_id}.zos"

            try:
                l5_front = _find_l5_front_surface(oss)
                l5_front.Thickness = thickness
                oss.update_status()
                oss.save_as(copy_path)
                _run_exports(oss, output_dir)
                print(f"Completed {run_id}: {copy_path}")
            except Exception as exc:
                _append_warning(output_dir, f"Scan point {run_id} failed: {repr(exc)}")
                print(f"[WARNING] Scan point {run_id} failed: {repr(exc)}")

        summarize_results(project_root)
    finally:
        try:
            if original_file:
                oss.load(original_file, saveifneeded=False)
            l5_front = _find_l5_front_surface(oss)
            l5_front.Thickness = original_thickness
            oss.update_status()
        except Exception as exc:
            print(f"[WARNING] Failed to restore original session state: {repr(exc)}")


if __name__ == "__main__":
    scan_l5_center_thickness(Path(__file__).resolve().parents[1])
