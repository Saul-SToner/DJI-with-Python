from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from export_surfaces import safe_get
from scan_radius import _export_current_point, _safe_label, _surface_at, resolve_surface_number
from summarize_results import summarize_results


COEFFICIENT_TERMS = {
    # Even Asphere terms are addressed by order: A2 -> n=1, A4 -> n=2, ...
    "A2": 1,
    "A4": 2,
    "A6": 3,
    "A8": 4,
    "A10": 5,
}


def value_token(value: float) -> str:
    prefix = "p" if value >= 0 else "m"
    return f"{prefix}{abs(value):.3e}".replace("+", "").replace("-", "").replace(".", "p")


def _unique_run_dir(project_root: Path, label: str, coefficient: str, value: float) -> tuple[str, Path]:
    safe_label = _safe_label(label)
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_label}_{coefficient}_{value_token(value)}"
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


def _surface_data(surface: Any) -> Any:
    return safe_get(surface, "SurfaceData") or surface


def _surface_type_name(surface: Any) -> str:
    return str(safe_get(surface, "TypeName") or safe_get(surface, "Type") or "")


def _callable_attr(obj: Any, name: str) -> Any | None:
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    return value if callable(value) else None


def _cell_value(cell: Any) -> float | None:
    if cell is None:
        return None
    for attr in ("DoubleValue", "Value"):
        value = _to_float(safe_get(cell, attr))
        if value is not None:
            return value
    return None


def _set_cell_fixed(cell: Any) -> None:
    if cell is None:
        return
    for method_name in ("MakeSolveFixed", "MakeSolveNone"):
        method = _callable_attr(cell, method_name)
        if callable(method):
            try:
                method()
                return
            except Exception:
                pass


def _set_cell_value(cell: Any, value: float) -> bool:
    if cell is None:
        return False
    for attr in ("DoubleValue", "Value"):
        try:
            setattr(cell, attr, value)
            return True
        except Exception:
            pass
    return False


def _term_cell(surface: Any, term_number: int) -> Any | None:
    data = _surface_data(surface)
    method = _callable_attr(data, "NthEvenOrderTermCell")
    if callable(method):
        try:
            return method(term_number)
        except Exception:
            pass
    return _surface_column_cell(surface, term_number)


def _surface_column_cell(surface: Any, term_number: int) -> Any | None:
    column = _surface_column_constant(f"Par{term_number}")
    if column is None:
        return None
    getter = _callable_attr(surface, "GetSurfaceCell")
    if not callable(getter):
        return None
    try:
        return getter(column)
    except Exception:
        return None


def _surface_column_constant(name: str) -> Any | None:
    candidates = [
        (zp.constants, "Editors", "LDE", "SurfaceColumn"),
        (zp.constants, "Editors", "LDE"),
        ("zospy.api.constants", "Editors", "LDE", "SurfaceColumn"),
        ("zospy.api.constants", "Editors", "LDE"),
        ("zospy.api.stubs._ZOSAPI_constants", "Editors", "LDE", "SurfaceColumn"),
        ("zospy.api.stubs._ZOSAPI_constants", "Editors", "LDE"),
    ]
    for source, *attrs in candidates:
        try:
            if isinstance(source, str):
                obj: Any = __import__(source, fromlist=["_"])
            else:
                obj = source
            for attr in attrs:
                obj = getattr(obj, attr)
            return getattr(obj, name)
        except Exception:
            continue
    return None


def _get_even_term(surface: Any, term_number: int) -> float | None:
    data = _surface_data(surface)
    method = _callable_attr(data, "GetNthEvenOrderTerm")
    if callable(method):
        try:
            return _to_float(method(term_number))
        except Exception:
            pass

    cell = _term_cell(surface, term_number)
    return _cell_value(cell)


def _set_even_term(surface: Any, term_number: int, value: float) -> tuple[bool, str]:
    data = _surface_data(surface)
    errors: list[str] = []

    method = _callable_attr(data, "SetNthEvenOrderTerm")
    if callable(method):
        try:
            method(term_number, value)
            cell = _term_cell(surface, term_number)
            _set_cell_fixed(cell)
            actual = _get_even_term(surface, term_number)
            if actual is not None and abs(actual - value) <= 1e-12:
                return True, f"NthEvenOrderTerm({term_number})={actual}"
            errors.append(f"SetNthEvenOrderTerm readback={actual}")
        except Exception as exc:
            errors.append(f"SetNthEvenOrderTerm failed: {repr(exc)}")

    cell = _term_cell(surface, term_number)
    if cell is not None:
        if _set_cell_value(cell, value):
            _set_cell_fixed(cell)
            actual = _cell_value(cell)
            if actual is not None and abs(actual - value) <= 1e-12:
                return True, f"cell Par{term_number}={actual}"
            errors.append(f"cell Par{term_number} readback={actual}")
        else:
            errors.append(f"cell Par{term_number} not writable")
    else:
        errors.append(f"cell Par{term_number} not found")

    return False, "; ".join(errors)


def _surface_type_constant(name: str) -> Any | None:
    candidates = [
        (zp.constants, "Editors", "LDE", "SurfaceType"),
        (zp.constants, "Editors", "LDE"),
        ("zospy.api.constants", "Editors", "LDE", "SurfaceType"),
        ("zospy.api.constants", "Editors", "LDE"),
    ]
    for source, *attrs in candidates:
        try:
            if isinstance(source, str):
                obj: Any = __import__(source, fromlist=["_"])
            else:
                obj = source
            for attr in attrs:
                obj = getattr(obj, attr)
            return getattr(obj, name)
        except Exception:
            continue
    return None


def _ensure_even_asphere(surface: Any) -> None:
    type_name = _surface_type_name(surface).replace(" ", "").lower()
    if "evenaspher" in type_name:
        return

    settings_method = _callable_attr(surface, "GetSurfaceTypeSettings")
    change_type = _callable_attr(surface, "ChangeType")
    if settings_method is None or change_type is None:
        raise RuntimeError("Target surface cannot be converted to Even Asphere.")

    attempts = [
        _surface_type_constant("EvenAspheric"),
        "EvenAspheric",
        "EvenAsphere",
        "Even Asphere",
    ]
    errors: list[str] = []
    for surface_type in attempts:
        if surface_type is None:
            continue
        try:
            settings = settings_method(surface_type)
            change_type(settings)
            return
        except Exception as exc:
            errors.append(f"{surface_type!r}: {repr(exc)}")

    raise RuntimeError("Failed to convert target surface to Even Asphere: " + " | ".join(errors))


def _set_coefficient(surface: Any, coefficient: str, value: float) -> None:
    coefficient = coefficient.upper()
    if coefficient not in COEFFICIENT_TERMS:
        raise ValueError(f"Unsupported coefficient {coefficient!r}. Supported: {', '.join(COEFFICIENT_TERMS)}")

    radius = safe_get(surface, "Radius")
    thickness = safe_get(surface, "Thickness")
    material = safe_get(surface, "Material")
    conic = safe_get(surface, "Conic")
    before_type = _surface_type_name(surface)

    _ensure_even_asphere(surface)

    if radius is not None:
        surface.Radius = radius
    if thickness is not None:
        surface.Thickness = thickness
    if material is not None:
        surface.Material = material
    try:
        surface.Conic = 0.0 if conic is None or "even" not in before_type.lower() else conic
    except Exception:
        pass

    term_values = {"A2": 0.0, "A4": 0.0, "A6": 0.0, "A8": 0.0, "A10": 0.0}
    term_values[coefficient] = value

    failures: list[str] = []
    for name, coeff_value in term_values.items():
        wrote, detail = _set_even_term(surface, COEFFICIENT_TERMS[name], coeff_value)
        if not wrote:
            failures.append(f"{name} could not be set to {coeff_value:g} ({detail})")

    if failures:
        raise RuntimeError("Failed to set Even Asphere coefficients: " + " | ".join(failures))


def scan_asphere_coeff(
    project_root: Path,
    values: tuple[float, ...],
    coefficient: str,
    label: str,
    surface: int | None = None,
    surface_comment: str | None = None,
    base_lens: Path | None = None,
) -> None:
    coefficient = coefficient.upper()
    if coefficient not in COEFFICIENT_TERMS:
        raise ValueError(f"Unsupported coefficient {coefficient!r}. Supported: {', '.join(COEFFICIENT_TERMS)}")

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
        print(
            "Scanning asphere coefficient surface:",
            resolved_surface_number,
            f"comment={resolved_surface_comment!r}",
            f"coefficient={coefficient}",
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
            _set_coefficient(target_surface, coefficient, value)
            oss.update_status()

            run_id, run_dir = _unique_run_dir(project_root, label, coefficient, value)
            copy_path = scan_dir / f"{run_id}.zos"
            oss.save_as(copy_path)
            print(f"Saved scan copy: {copy_path}", flush=True)

            extra_metadata = {
                "label": label,
                "scanned_parameter": "AsphereCoefficient",
                "scanned_surface": resolved_surface_number,
                "scanned_surface_comment": target_comment or resolved_surface_comment,
                "scanned_coefficient": coefficient,
                "scanned_value": value,
                "quick_focus": False,
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
    parser = argparse.ArgumentParser(description="Scan one Even Asphere coefficient without optimization.")
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--surface", type=int, help="Surface number to scan.")
    locator.add_argument("--surface-comment", help="Surface Comment text to locate.")
    parser.add_argument("--coefficient", required=True, choices=sorted(COEFFICIENT_TERMS), help="Coefficient to scan.")
    parser.add_argument("--values", nargs="+", required=True, type=float, help="Coefficient values.")
    parser.add_argument("--label", default="asphere_coeff_scan", help="Label used in run_id and scan copy names.")
    parser.add_argument("--base-lens", type=Path, help="Optional base lens path to reload before each scan point.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_asphere_coeff(
        Path(__file__).resolve().parents[1],
        tuple(args.values),
        coefficient=args.coefficient,
        label=args.label,
        surface=args.surface,
        surface_comment=args.surface_comment,
        base_lens=args.base_lens,
    )
