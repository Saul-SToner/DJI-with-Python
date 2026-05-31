from __future__ import annotations

from pathlib import Path

from run_files import run_file


PRINT_FIELDS = [
    ("run_id", "run_id"),
    ("label", "label"),
    ("scanned_mode", "scanned_mode"),
    ("target_comment", "target_comment"),
    ("scanned_surface", "scanned_surface"),
    ("scanned_surface_comment", "scanned_surface_comment"),
    ("scanned_radius", "scanned_radius"),
    ("scanned_thickness", "scanned_thickness"),
    ("scanned_conic", "scanned_conic"),
    ("image_shift", "image_shift"),
    ("original_image_thickness", "original_image_thickness"),
    ("new_image_thickness", "new_image_thickness"),
    ("scanned_coefficient", "scanned_coefficient"),
    ("scanned_value", "scanned_value"),
    ("scanned_surface_comment_a", "scanned_surface_comment_a"),
    ("scanned_radius_a", "scanned_radius_a"),
    ("scanned_surface_comment_b", "scanned_surface_comment_b"),
    ("scanned_radius_b", "scanned_radius_b"),
    ("scanned_material", "scanned_material"),
    ("material_catalog", "material_catalog"),
    ("requested_glass_catalog_name", "requested_glass_catalog_name"),
    ("nd", "material_nd"),
    ("vd", "material_vd"),
    ("requested_material", "requested_material"),
    ("actual_glass_name_after_set", "actual_glass_name_after_set"),
    ("actual_catalog_if_available", "actual_catalog_if_available"),
    ("actual_nd_if_available", "actual_nd_if_available"),
    ("actual_vd_if_available", "actual_vd_if_available"),
    ("is_material_resolved", "is_material_resolved"),
    ("material_set_success", "material_set_success"),
    ("material_validation_warning", "material_validation_warning"),
    ("material_validation_error", "material_validation_error"),
    ("failure_reason", "failure_reason"),
    ("output_folder", "output_folder"),
    ("base_lens", "base_lens"),
    ("scan_lens", "scan_lens"),
    ("lens_file", "lens_file"),
    ("F/#", "current_f_number"),
    ("EFL", "efl"),
    ("BFL", "bfl"),
    ("TTL", "ttl"),
    ("Working F/#", "working_f_number"),
    ("S6R", "S6R"),
    ("S7T", "S7T"),
    ("S8R", "S8R"),
    ("S11T", "S11T"),
    ("S12R", "S12R"),
    ("S13R", "S13R"),
    ("S13_conic", "S13_conic"),
    ("S15T", "S15T"),
    ("L5_edge", "L5_edge"),
    ("MTF40_min", "MTF40_min"),
    ("MTF40_mean", "MTF40_mean"),
    ("MTF50_min", "MTF50_min"),
    ("MTF50_mean", "MTF50_mean"),
    ("25T20", "25T20"),
    ("25T25", "25T25"),
    ("25T30", "25T30"),
    ("25T35", "25T35"),
    ("25T40", "25T40"),
    ("25T50", "25T50"),
    ("25S50", "25S50"),
    ("27p5T40", "27p5T40"),
    ("28T40", "28T40"),
    ("28T50", "28T50"),
    ("summary_extraction_warning", "summary_extraction_warning"),
    ("status", "status"),
]


def read_summary_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line or line.startswith("["):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()

    return values


def print_run_console_summary(run_dir: Path, run_id: str) -> None:
    summary_path = run_file(run_dir, run_id, "summary_for_chatgpt")
    values = read_summary_values(summary_path)
    values["output_folder"] = str(run_dir)

    print("Run export summary:", flush=True)
    for label, key in PRINT_FIELDS:
        print(f"{label}: {values.get(key, 'null')}", flush=True)
