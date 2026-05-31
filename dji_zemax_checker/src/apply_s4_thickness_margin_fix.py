from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import zospy as zp


TARGET_SURFACE = 4
EXPECTED_RADIUS = 3.306
EXPECTED_GLASS = ""
EXPECTED_SEMI_DIAMETER = 3.89554
EXPECTED_PREVIOUS_THICKNESS = 3.757663
PRE_APERTURE_THICKNESS = 3.64409
PRE_APERTURE_SEMI_DIAMETER = 2.900269955
TARGET_THICKNESS = 3.879031
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
TOLERANCE = 1e-8
PRECHECK_TOLERANCE = 5e-4
_LIVE_ZOS_CONNECTIONS: list[Any] = []


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None


def _same_value(left: Any, right: Any, tolerance: float = TOLERANCE) -> bool:
    a = _to_float(left)
    b = _to_float(right)
    if a is None or b is None:
        return str(left) == str(right)
    if math.isinf(a) or math.isinf(b):
        return math.isinf(a) and math.isinf(b) and (a > 0) == (b > 0)
    return abs(a - b) <= tolerance


def _close_enough(left: Any, right: Any, tolerance: float = PRECHECK_TOLERANCE) -> bool:
    return _same_value(left, right, tolerance)


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _get_even_term(surface: Any, term: int) -> Any:
    data = _safe_get(surface, "SurfaceData")
    if data is None:
        return None
    method = _safe_get(data, "GetNthEvenOrderTerm")
    if callable(method):
        try:
            return method(term)
        except Exception:
            pass
    cell_method = _safe_get(data, "NthEvenOrderTermCell")
    if callable(cell_method):
        try:
            cell = cell_method(term)
            for attr in ("DoubleValue", "Value"):
                value = _safe_get(cell, attr)
                if value is not None:
                    return value
        except Exception:
            pass
    return None


def _snapshot(oss: Any) -> dict[int, dict[str, Any]]:
    lde = oss.LDE
    rows: dict[int, dict[str, Any]] = {}
    for surface_number in range(int(lde.NumberOfSurfaces)):
        surface = lde.GetSurfaceAt(surface_number)
        rows[surface_number] = {
            "radius": surface.Radius,
            "thickness": surface.Thickness,
            "glass": str(surface.Material or ""),
            "semi_diameter": surface.SemiDiameter,
            "comment": str(surface.Comment or ""),
            "conic": _safe_get(surface, "Conic"),
            "even_terms": {term: _get_even_term(surface, term) for term in EVEN_TERMS},
        }
    return rows


def _validate_only_allowed_changes(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
    *,
    allow_s4_semi_diameter_change: bool,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if set(before) != set(after):
        return [f"surface set changed: before={sorted(before)}, after={sorted(after)}"], warnings

    for surface_number, before_row in before.items():
        after_row = after[surface_number]

        if not _same_value(before_row["radius"], after_row["radius"]):
            failures.append(f"S{surface_number} Radius changed: {before_row['radius']} -> {after_row['radius']}")
        if before_row["glass"] != after_row["glass"]:
            failures.append(f"S{surface_number} Glass changed: {before_row['glass']} -> {after_row['glass']}")
        if not _same_value(before_row["conic"], after_row["conic"]):
            failures.append(f"S{surface_number} Conic changed: {before_row['conic']} -> {after_row['conic']}")
        for term in EVEN_TERMS:
            if not _same_value(before_row["even_terms"].get(term), after_row["even_terms"].get(term)):
                failures.append(
                    f"S{surface_number} A{term} changed: "
                    f"{before_row['even_terms'].get(term)} -> {after_row['even_terms'].get(term)}"
                )

        if surface_number == TARGET_SURFACE:
            if not _same_value(after_row["thickness"], TARGET_THICKNESS):
                failures.append(f"S4 Thickness expected {TARGET_THICKNESS}, got {after_row['thickness']}")
            if allow_s4_semi_diameter_change:
                if not _same_value(after_row["semi_diameter"], EXPECTED_SEMI_DIAMETER):
                    failures.append(f"S4 SemiDiameter expected {EXPECTED_SEMI_DIAMETER}, got {after_row['semi_diameter']}")
            elif not _same_value(before_row["semi_diameter"], after_row["semi_diameter"]):
                failures.append(
                    f"S4 SemiDiameter changed: {before_row['semi_diameter']} -> {after_row['semi_diameter']}"
                )
        else:
            if not _same_value(before_row["thickness"], after_row["thickness"]):
                failures.append(
                    f"S{surface_number} Thickness changed unexpectedly: "
                    f"{before_row['thickness']} -> {after_row['thickness']}"
                )
            if not _same_value(before_row["semi_diameter"], after_row["semi_diameter"]):
                warnings.append(
                    f"S{surface_number} SemiDiameter changed automatically: "
                    f"{before_row['semi_diameter']} -> {after_row['semi_diameter']}"
                )

    return failures, warnings


def _make_semidiameter_manual(surface: Any) -> None:
    cell = _safe_get(surface, "SemiDiameterCell")
    if cell is None:
        return
    for method_name in ("MakeSolveFixed", "MakeSolveNone"):
        method = _safe_get(cell, method_name)
        if callable(method):
            try:
                method()
                return
            except Exception:
                pass


def _set_semidiameter(surface: Any, value: float) -> None:
    _make_semidiameter_manual(surface)
    try:
        surface.SemiDiameter = value
    except Exception as exc:
        raise RuntimeError(
            f"Failed to set S{surface.SurfaceNumber} SemiDiameter. "
            "It may still be controlled by an automatic/solve setting."
        ) from exc
    actual = surface.SemiDiameter
    if not _same_value(actual, value):
        raise RuntimeError(f"S{surface.SurfaceNumber} SemiDiameter readback mismatch: expected {value}, got {actual}.")


def _connect_extension() -> Any:
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
        _LIVE_ZOS_CONNECTIONS.append(zos)
        return oss
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc


def _print_s4(prefix: str, snapshot: dict[int, dict[str, Any]]) -> None:
    row = snapshot[TARGET_SURFACE]
    print(
        f"{prefix} S4: Radius={row['radius']}, Thickness={row['thickness']}, "
        f"Glass={row['glass']!r}, SemiDiameter={row['semi_diameter']}",
        flush=True,
    )


def _precheck(before: dict[int, dict[str, Any]], from_pre_aperture_state: bool) -> str:
    s4 = before[TARGET_SURFACE]
    failures: list[str] = []
    if not _close_enough(s4["radius"], EXPECTED_RADIUS):
        failures.append(f"S4 Radius expected near {EXPECTED_RADIUS}, got {s4['radius']}")
    if str(s4["glass"]) != EXPECTED_GLASS:
        failures.append(f"S4 Glass expected empty, got {s4['glass']!r}")

    if _close_enough(s4["thickness"], TARGET_THICKNESS) and _close_enough(s4["semi_diameter"], EXPECTED_SEMI_DIAMETER):
        status = "already_applied"
    elif from_pre_aperture_state:
        if not _close_enough(s4["thickness"], PRE_APERTURE_THICKNESS):
            failures.append(f"S4 Thickness expected near pre-aperture {PRE_APERTURE_THICKNESS}, got {s4['thickness']}")
        if not _close_enough(s4["semi_diameter"], PRE_APERTURE_SEMI_DIAMETER):
            failures.append(
                f"S4 SemiDiameter expected near pre-aperture {PRE_APERTURE_SEMI_DIAMETER}, got {s4['semi_diameter']}"
            )
        status = "ready_from_pre_aperture_state"
    else:
        if not _close_enough(s4["semi_diameter"], EXPECTED_SEMI_DIAMETER):
            failures.append(f"S4 SemiDiameter expected near {EXPECTED_SEMI_DIAMETER}, got {s4['semi_diameter']}")
        if _close_enough(s4["thickness"], EXPECTED_PREVIOUS_THICKNESS):
            status = "ready_thickness_only"
        else:
            failures.append(
                f"S4 Thickness expected near {EXPECTED_PREVIOUS_THICKNESS} or already {TARGET_THICKNESS}, "
                f"got {s4['thickness']}"
            )
            status = "invalid"

    if failures:
        raise RuntimeError("; ".join(failures))
    return status


def apply_s4_thickness_margin_fix(lens_path: str, apply: bool, from_pre_aperture_state: bool) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    print(f"lens path: {lens_path}", flush=True)
    print(f"mode: {'apply' if apply else 'dry-run'}", flush=True)
    oss = _connect_extension()
    try:
        oss.load(lens_path, saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    if int(oss.LDE.NumberOfSurfaces) <= TARGET_SURFACE:
        print(f"[ERROR] Lens has too few surfaces: {oss.LDE.NumberOfSurfaces}", flush=True)
        raise SystemExit(1)

    before = _snapshot(oss)
    _print_s4("before", before)
    if from_pre_aperture_state:
        print("from_pre_aperture_state: true", flush=True)
        print(f"S4 target Semi-Diameter: {EXPECTED_SEMI_DIAMETER}", flush=True)
    else:
        print("from_pre_aperture_state: false", flush=True)
    print(f"S4 target Thickness: {TARGET_THICKNESS}", flush=True)

    try:
        precheck_status = _precheck(before, from_pre_aperture_state)
        print(f"precheck status: {precheck_status}", flush=True)
    except Exception as exc:
        print("[ERROR] Precheck failed. Lens was not modified or saved by this script.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    if not apply:
        print("save status: dry-run only; lens not modified and not saved.", flush=True)
        print("dry-run completed successfully.", flush=True)
        return

    if precheck_status == "already_applied":
        print("S4 target values are already applied. No save was performed.", flush=True)
        print("save status: already applied; unchanged", flush=True)
        return

    try:
        s4 = oss.LDE.GetSurfaceAt(TARGET_SURFACE)
        if precheck_status == "ready_from_pre_aperture_state":
            _set_semidiameter(s4, EXPECTED_SEMI_DIAMETER)
        s4.Thickness = TARGET_THICKNESS
    except Exception as exc:
        print("[ERROR] Failed while setting S4 Thickness. Lens was not saved.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    after = _snapshot(oss)
    _print_s4("after ", after)

    allow_semi_change = precheck_status == "ready_from_pre_aperture_state"
    failures, warnings = _validate_only_allowed_changes(before, after, allow_s4_semi_diameter_change=allow_semi_change)
    if failures:
        print("[ERROR] Safety check failed. Lens was not saved.", flush=True)
        for failure in failures:
            print(f"[ERROR] {failure}", flush=True)
        raise SystemExit(1)
    for warning in warnings:
        print(f"[WARNING] {warning}", flush=True)

    try:
        oss.save()
    except Exception as exc:
        print(f"[ERROR] Failed to save lens to original path: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    try:
        oss.load(lens_path, saveifneeded=False)
        verify = _snapshot(oss)
    except Exception as exc:
        print("[ERROR] Saved, but failed to reload/re-read lens for verification.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    verify_failures, verify_warnings = _validate_only_allowed_changes(
        before,
        verify,
        allow_s4_semi_diameter_change=allow_semi_change,
    )
    if verify_failures:
        print("[ERROR] Post-save verification failed.", flush=True)
        for failure in verify_failures:
            print(f"[ERROR] {failure}", flush=True)
        raise SystemExit(1)
    for warning in verify_warnings:
        print(f"[WARNING] post-save: {warning}", flush=True)

    print(f"S4 old Radius: {before[4]['radius']}", flush=True)
    print(f"S4 new Radius: {verify[4]['radius']}", flush=True)
    print(f"S4 old Thickness: {before[4]['thickness']}", flush=True)
    print(f"S4 new Thickness: {verify[4]['thickness']}", flush=True)
    print(f"S4 old Glass: {before[4]['glass']!r}", flush=True)
    print(f"S4 new Glass: {verify[4]['glass']!r}", flush=True)
    print(f"S4 old Semi-Diameter: {before[4]['semi_diameter']}", flush=True)
    print(f"S4 new Semi-Diameter: {verify[4]['semi_diameter']}", flush=True)
    print("save status: saved successfully", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply S4 thickness-only margin fix with strict safety checks.")
    parser.add_argument("--lens", required=True, help="Lens path to modify only when --apply is provided.")
    parser.add_argument("--apply", action="store_true", help="Actually save the S4 thickness fix to the original lens.")
    parser.add_argument(
        "--from-pre-aperture-state",
        action="store_true",
        help=(
            "Allow starting from S4 pre-aperture state "
            f"(Thickness~{PRE_APERTURE_THICKNESS}, SemiDiameter~{PRE_APERTURE_SEMI_DIAMETER}) "
            f"and set both S4 SemiDiameter={EXPECTED_SEMI_DIAMETER} and Thickness={TARGET_THICKNESS}."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    apply_s4_thickness_margin_fix(args.lens, args.apply, args.from_pre_aperture_state)
