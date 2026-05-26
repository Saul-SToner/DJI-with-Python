from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from zospy.analyses.reports.surface_data import ModelGlass, SurfaceData

from analysis_debug import update_analysis_debug
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


FF_BRANCH_TOLERANCE = 1e-4

FF_BRANCH_EXPECTED_SURFACES = {
    7: {"Thickness": 0.55},
    8: {"Radius": -42.0},
    9: {"Thickness": 0.70},
    11: {"Thickness": 0.771},
    12: {"Radius": -6.30},
    13: {"Radius": -12.0, "Conic": 12.75},
}


def _safe_material_token(value: str) -> str:
    return _safe_label(value.replace("-", "m"))


def _unique_run_dir(project_root: Path, label: str, material: str) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{_safe_material_token(material)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _load_allowed_materials(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Allowed materials CSV not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    allowed: dict[str, dict[str, str]] = {}
    for row in rows:
        name = (row.get("material_name") or "").strip()
        if name:
            allowed[name.upper()] = row
    return allowed


def _set_material(surface: Any, material: str) -> None:
    surface.Material = material


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close(actual: Any, expected: float, tolerance: float = FF_BRANCH_TOLERANCE) -> bool:
    actual_value = _to_float(actual)
    return actual_value is not None and abs(actual_value - expected) <= tolerance


def _set_value(surface: Any, attr: str, value: float) -> None:
    setattr(surface, attr, value)


def _find_comment_if_present(oss: Any, comment: str) -> int | None:
    try:
        return resolve_surface_number(oss, None, comment)
    except ValueError:
        return None


def _ff_branch_surfaces(oss: Any) -> tuple[int | None, int | None]:
    return _find_comment_if_present(oss, "FF_FRONT"), _find_comment_if_present(oss, "FF_BACK")


def _ff_branch_mismatches(oss: Any, expected_material: str | None = None) -> list[str]:
    front_index, back_index = _ff_branch_surfaces(oss)
    if front_index is None and back_index is None:
        return []

    mismatches: list[str] = []
    if front_index is None:
        mismatches.append("FF_FRONT comment not found")
        return mismatches
    if back_index is None:
        mismatches.append("FF_BACK comment not found")
        return mismatches
    if front_index <= 0:
        mismatches.append("FF_FRONT has no preceding L6-to-FF gap surface")
        return mismatches

    front = _surface_at(oss, front_index)
    back = _surface_at(oss, back_index)
    before_front = _surface_at(oss, front_index - 1)

    checks = [
        ("FF_FRONT Radius", safe_get(front, "Radius"), 75.0),
        ("FF_BACK Radius", safe_get(back, "Radius"), -40.0),
        ("L6_to_FF_FRONT Thickness", safe_get(before_front, "Thickness"), 0.25),
        ("FF thickness", safe_get(front, "Thickness"), 0.30),
        ("FF_BACK_to_filter Thickness", safe_get(back, "Thickness"), 0.20),
    ]
    for label, actual, expected in checks:
        if not _close(actual, expected):
            mismatches.append(f"{label}: expected {expected}, got {actual}")

    if expected_material is not None:
        current_material = str(safe_get(front, "Material") or "").strip()
        if current_material.upper() != expected_material.upper():
            mismatches.append(f"FF_FRONT Material: expected {expected_material}, got {current_material}")

    for surface_number, expected_values in FF_BRANCH_EXPECTED_SURFACES.items():
        try:
            surface = _surface_at(oss, surface_number)
        except Exception as exc:
            mismatches.append(f"S{surface_number}: missing ({repr(exc)})")
            continue
        for attr, expected in expected_values.items():
            actual = safe_get(surface, attr)
            if not _close(actual, expected):
                mismatches.append(f"S{surface_number}{attr}: expected {expected}, got {actual}")

    return mismatches


def _restore_ff_branch_invariants(oss: Any, material: str | None = None) -> list[str]:
    front_index, back_index = _ff_branch_surfaces(oss)
    if front_index is None or back_index is None or front_index <= 0:
        return _ff_branch_mismatches(oss, expected_material=material)

    front = _surface_at(oss, front_index)
    back = _surface_at(oss, back_index)
    before_front = _surface_at(oss, front_index - 1)

    _set_value(front, "Radius", 75.0)
    _set_value(back, "Radius", -40.0)
    _set_value(before_front, "Thickness", 0.25)
    _set_value(front, "Thickness", 0.30)
    _set_value(back, "Thickness", 0.20)
    if material is not None:
        _set_material(front, material)

    for surface_number, expected_values in FF_BRANCH_EXPECTED_SURFACES.items():
        surface = _surface_at(oss, surface_number)
        for attr, expected in expected_values.items():
            _set_value(surface, attr, expected)

    oss.update_status()
    return _ff_branch_mismatches(oss, expected_material=material)


def _validate_ff_branch_or_raise(oss: Any, context: str) -> None:
    mismatches = _ff_branch_mismatches(oss)
    if mismatches:
        details = "\n".join(f"- {message}" for message in mismatches)
        raise RuntimeError(f"{context} does not match the expected FF branch baseline:\n{details}")


def _resolve_values(values: list[str] | None, allowed: dict[str, dict[str, str]]) -> list[str]:
    if values:
        missing = [value for value in values if value.upper() not in allowed]
        if missing:
            raise ValueError(f"Materials not in allowed CSV: {', '.join(missing)}")
        return values
    return [row["material_name"] for row in allowed.values()]


def _material_glass_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def _surface_data_material_details(oss: Any, surface_number: int) -> dict[str, Any]:
    details: dict[str, Any] = {
        "actual_catalog_if_available": None,
        "actual_nd_if_available": None,
        "actual_vd_if_available": None,
        "surface_data_material_glass": None,
        "surface_data_best_fit_glass": None,
        "material_validation_error": None,
    }
    try:
        result = SurfaceData(surface=surface_number).run(oss)
        material = result.data.material
        glass = material.glass
        if isinstance(glass, ModelGlass):
            details["actual_nd_if_available"] = glass.nd
            details["actual_vd_if_available"] = glass.abbe
            details["surface_data_material_glass"] = "Model glass"
        else:
            details["surface_data_material_glass"] = _material_glass_name(glass)

        details["surface_data_best_fit_glass"] = _material_glass_name(material.best_fit_glass)
        if details["actual_nd_if_available"] is None and material.indices:
            details["actual_nd_if_available"] = material.indices[0].index
    except Exception as exc:
        details["material_validation_error"] = f"{type(exc).__name__}: {exc!r}"
    return details


def _material_validation(
    oss: Any,
    surface_number: int,
    requested_material: str,
    material_info: dict[str, str],
) -> dict[str, Any]:
    surface = _surface_at(oss, surface_number)
    actual_material = str(safe_get(surface, "Material") or "").strip()
    details = _surface_data_material_details(oss, surface_number)
    surface_data_ok = details.get("material_validation_error") is None

    actual_nd = details.get("actual_nd_if_available")
    actual_vd = details.get("actual_vd_if_available")
    allowed_nd = _to_float(material_info.get("nd"))
    allowed_vd = _to_float(material_info.get("vd"))
    if actual_nd is None:
        actual_nd = allowed_nd
    if actual_vd is None:
        actual_vd = allowed_vd

    requested_matches_actual = actual_material.upper() == requested_material.upper()
    has_index_data = actual_nd is not None and actual_vd is not None
    is_resolved = requested_matches_actual and has_index_data
    validation_error = None if is_resolved else details.get("material_validation_error")
    validation_warning = details.get("material_validation_error") if is_resolved and not surface_data_ok else None

    return {
        "requested_material": requested_material,
        "actual_glass_name_after_set": actual_material or None,
        "actual_catalog_if_available": details.get("actual_catalog_if_available"),
        "actual_nd_if_available": actual_nd,
        "actual_vd_if_available": actual_vd,
        "surface_data_material_glass": details.get("surface_data_material_glass"),
        "surface_data_best_fit_glass": details.get("surface_data_best_fit_glass"),
        "material_validation_error": validation_error,
        "material_validation_warning": validation_warning,
        "is_material_resolved": is_resolved,
        "material_set_success": requested_matches_actual,
    }


def scan_material(
    project_root: Path,
    base_lens: Path,
    allowed_materials_csv: Path,
    label: str,
    values: list[str] | None = None,
    surface: int | None = None,
    surface_comment: str | None = None,
    quick_focus: bool = False,
) -> None:
    if not base_lens.exists():
        raise FileNotFoundError(f"Base lens not found: {base_lens}")

    allowed = _load_allowed_materials(allowed_materials_csv)
    materials = _resolve_values(values, allowed)

    zos = zp.ZOS()
    oss = zos.connect("extension")
    original_file = safe_get(oss, "SystemFile")
    scan_dir = project_root / "scan_runs"
    scan_dir.mkdir(parents=True, exist_ok=True)

    try:
        oss.load(base_lens, saveifneeded=False)
        resolved_surface_number = resolve_surface_number(oss, surface, surface_comment)
        resolved_surface = _surface_at(oss, resolved_surface_number)
        resolved_surface_comment = str(safe_get(resolved_surface, "Comment") or "")
        if resolved_surface_comment.strip().upper() == "FF_FRONT":
            _validate_ff_branch_or_raise(oss, str(base_lens))
        print(
            "Scanning material surface:",
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
        for material in materials:
            material_info = allowed[material.upper()]
            oss.load(base_lens, saveifneeded=False)
            target_surface = _surface_at(oss, resolved_surface_number)
            target_comment = str(safe_get(target_surface, "Comment") or "")
            if target_comment.strip().upper() == "FF_FRONT":
                _validate_ff_branch_or_raise(oss, str(base_lens))
            _set_material(target_surface, material)
            oss.update_status()
            material_validation = _material_validation(oss, resolved_surface_number, material, material_info)

            run_id, run_dir = _unique_run_dir(project_root, label, material)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)
            update_analysis_debug(
                run_dir,
                run_id,
                {
                    "material_set_success": material_validation.get("material_set_success"),
                    "actual_glass_name_after_set": material_validation.get("actual_glass_name_after_set"),
                    "actual_nd": material_validation.get("actual_nd_if_available"),
                    "actual_vd": material_validation.get("actual_vd_if_available"),
                    "material_validation_warning": material_validation.get("material_validation_warning"),
                    "material_validation_error": material_validation.get("material_validation_error"),
                },
            )

            quick_focus_warning = None
            if quick_focus:
                quick_focus_warning = _run_quick_focus(oss)
                target_surface = _surface_at(oss, resolved_surface_number)
                current_material = str(safe_get(target_surface, "Material") or "")
                if current_material.strip().upper() != material.upper():
                    _set_material(target_surface, material)
                    extra_warning = (
                        "Quick Focus changed the scanned material; "
                        f"restored surface {resolved_surface_number} Material to {material}."
                    )
                    quick_focus_warning = (
                        extra_warning if quick_focus_warning is None else f"{quick_focus_warning} {extra_warning}"
                    )
                if target_comment.strip().upper() == "FF_FRONT":
                    mismatches = _ff_branch_mismatches(oss, expected_material=material)
                    if mismatches:
                        remaining = _restore_ff_branch_invariants(oss, material=material)
                        extra_warning = (
                            "Quick Focus changed fixed FF branch parameters; restored expected values. "
                            f"Original mismatches: {'; '.join(mismatches)}"
                        )
                        if remaining:
                            extra_warning += f" Remaining mismatches: {'; '.join(remaining)}"
                        quick_focus_warning = (
                            extra_warning if quick_focus_warning is None else f"{quick_focus_warning} {extra_warning}"
                        )
                oss.update_status()
                material_validation = _material_validation(oss, resolved_surface_number, material, material_info)
                oss.save_as(copy_path)
                if quick_focus_warning:
                    _append_warning(run_dir, run_id, quick_focus_warning)
                update_analysis_debug(
                    run_dir,
                    run_id,
                    {
                        "material_set_success": material_validation.get("material_set_success"),
                        "actual_glass_name_after_set": material_validation.get("actual_glass_name_after_set"),
                        "actual_nd": material_validation.get("actual_nd_if_available"),
                        "actual_vd": material_validation.get("actual_vd_if_available"),
                        "material_validation_warning": material_validation.get("material_validation_warning"),
                        "material_validation_error": material_validation.get("material_validation_error"),
                    },
                )

            extra_metadata = {
                "label": label,
                "scanned_parameter": "Material",
                "scanned_surface": resolved_surface_number,
                "scanned_surface_comment": target_comment or resolved_surface_comment,
                "scanned_material": material,
                "material_catalog": material_info.get("catalog_name"),
                "material_nd": material_info.get("nd"),
                "material_vd": material_info.get("vd"),
                **material_validation,
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
    parser = argparse.ArgumentParser(description="Material scan constrained by allowed materials CSV.")
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--surface", type=int, help="Surface number to scan.")
    locator.add_argument("--surface-comment", help="Surface Comment text to locate.")
    parser.add_argument("--base-lens", required=True, type=Path, help="Base lens loaded before each material point.")
    parser.add_argument("--allowed-materials-csv", required=True, type=Path, help="Allowed material whitelist CSV.")
    parser.add_argument("--values", nargs="+", help="Material names to scan. Defaults to all rows in CSV.")
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting material.")
    parser.add_argument("--label", default="material_scan", help="Label used in run_id and scan copy names.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_material(
        Path(__file__).resolve().parents[1],
        base_lens=args.base_lens,
        allowed_materials_csv=args.allowed_materials_csv,
        label=args.label,
        values=args.values,
        surface=args.surface,
        surface_comment=args.surface_comment,
        quick_focus=args.quick_focus,
    )
