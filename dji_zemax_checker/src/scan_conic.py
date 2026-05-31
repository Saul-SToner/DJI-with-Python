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


def conic_token(value: float) -> str:
    prefix = "p" if value >= 0 else "m"
    return f"{prefix}{abs(value):g}".replace(".", "p")


def _unique_run_dir(project_root: Path, label: str, value: float) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{conic_token(value)}"
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _make_conic_fixed(surface: Any) -> None:
    cell = safe_get(surface, "ConicCell")
    if cell is None:
        return

    for method_name in ("MakeSolveFixed", "MakeSolveNone"):
        method = safe_get(cell, method_name)
        if callable(method):
            try:
                method()
                return
            except Exception:
                pass


def _set_parameter_cell(surface: Any, index: int, value: float) -> bool:
    for getter_name in ("GetCellAt", "GetSurfaceCell"):
        getter = safe_get(surface, getter_name)
        if not callable(getter):
            continue
        try:
            cell = getter(index)
        except Exception:
            continue
        for attr in ("DoubleValue", "Value"):
            try:
                setattr(cell, attr, value)
                return True
            except Exception:
                pass
    return False


def _try_convert_to_even_asphere(surface: Any) -> None:
    radius = safe_get(surface, "Radius")
    thickness = safe_get(surface, "Thickness")
    material = safe_get(surface, "Material")

    converted = False
    for method_name in ("GetSurfaceTypeSettings", "CreateSurfaceTypeSettings"):
        method = safe_get(surface, method_name)
        if not callable(method):
            continue
        for type_name in ("EvenAsphere", "Even Asphere"):
            try:
                settings = method(type_name)
                change_type = safe_get(surface, "ChangeType")
                if callable(change_type):
                    change_type(settings)
                    converted = True
                    break
            except Exception:
                continue
        if converted:
            break

    for attr, value in (("Radius", radius), ("Thickness", thickness), ("Material", material)):
        if value is not None:
            try:
                setattr(surface, attr, value)
            except Exception:
                pass

    # Even Asphere coefficient cells are commonly parameter cells; these best-effort writes keep A2/A4/A6/A8 closed.
    for index in (12, 13, 14, 15):
        _set_parameter_cell(surface, index, 0.0)


def _set_conic(surface: Any, value: float) -> None:
    original_radius = safe_get(surface, "Radius")
    try:
        surface.Conic = value
    except Exception:
        _try_convert_to_even_asphere(surface)
        try:
            surface.Conic = value
        except Exception as exc:
            raise RuntimeError("Target surface does not support writable Conic.") from exc

    _make_conic_fixed(surface)
    if original_radius is not None:
        try:
            surface.Radius = original_radius
        except Exception:
            pass

    actual = _to_float(safe_get(surface, "Conic"))
    if actual is None or abs(actual - value) > 1e-9:
        raise RuntimeError(f"Failed to set Conic to {value:g}; actual={actual}.")


def scan_conic(
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
        resolved_surface_number = resolve_surface_number(oss, surface, surface_comment)
        resolved_surface = _surface_at(oss, resolved_surface_number)
        resolved_surface_comment = str(safe_get(resolved_surface, "Comment") or "")
        if safe_get(resolved_surface, "Conic") is None:
            _try_convert_to_even_asphere(resolved_surface)
            if safe_get(resolved_surface, "Conic") is None:
                raise RuntimeError(f"Surface {resolved_surface_number} does not expose a Conic field.")
        print(
            "Scanning conic surface:",
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
            _set_conic(target_surface, value)
            oss.update_status()

            run_id, run_dir = _unique_run_dir(project_root, label, value)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)

            quick_focus_warning = None
            if quick_focus:
                quick_focus_warning = _run_quick_focus(oss)
                target_surface = _surface_at(oss, resolved_surface_number)
                actual = _to_float(safe_get(target_surface, "Conic"))
                if actual is None or abs(actual - value) > 1e-9:
                    _set_conic(target_surface, value)
                    extra_warning = (
                        "Quick Focus changed the scanned conic; "
                        f"restored surface {resolved_surface_number} Conic to {value:g}."
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
                "scanned_parameter": "Conic",
                "scanned_surface": resolved_surface_number,
                "scanned_surface_comment": target_comment or resolved_surface_comment,
                "scanned_conic": value,
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
    parser = argparse.ArgumentParser(description="Conservative surface conic scan without optimization.")
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--surface", type=int, help="Surface number to scan.")
    locator.add_argument("--surface-comment", help="Surface Comment text to locate.")
    parser.add_argument("--values", nargs="+", required=True, type=float, help="Conic values to scan.")
    parser.add_argument("--label", default="conic_scan", help="Label used in run_id and scan copy names.")
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting conic.")
    parser.add_argument("--base-lens", type=Path, help="Optional base lens path to reload before each scan point.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_conic(
        Path(__file__).resolve().parents[1],
        tuple(args.values),
        label=args.label,
        surface=args.surface,
        surface_comment=args.surface_comment,
        quick_focus=args.quick_focus,
        base_lens=args.base_lens,
    )
