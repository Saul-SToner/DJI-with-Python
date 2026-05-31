from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import zospy as zp


TARGET_VALUES = {
    "s2_semi_diameter": 3.96746,
    "s3_semi_diameter": 3.96746,
    "s4_thickness": 3.64409,
    "s7_thickness": 1.812449,
    "s9_thickness": 1.270244,
}

ALLOWED_SEMI_DIAMETER_CHANGES = {2: TARGET_VALUES["s2_semi_diameter"], 3: TARGET_VALUES["s3_semi_diameter"]}
ALLOWED_THICKNESS_CHANGES = {4: TARGET_VALUES["s4_thickness"], 7: TARGET_VALUES["s7_thickness"], 9: TARGET_VALUES["s9_thickness"]}
EXPECTED_ORIGINAL_THICKNESS = {4: 2.259, 7: 1.671, 9: 1.190}
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
TOLERANCE = 1e-8
PRECHECK_TOLERANCE = 5e-3
_LIVE_ZOS_CONNECTIONS: list[Any] = []


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number


def _same_value(left: Any, right: Any, tolerance: float = TOLERANCE) -> bool:
    a = _to_float(left)
    b = _to_float(right)
    if a is None or b is None:
        return str(left) == str(right)
    if math.isinf(a) or math.isinf(b):
        return math.isinf(a) and math.isinf(b) and (a > 0) == (b > 0)
    return abs(a - b) <= tolerance


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
    data: dict[int, dict[str, Any]] = {}
    for surface_number in range(int(lde.NumberOfSurfaces)):
        surface = lde.GetSurfaceAt(surface_number)
        data[surface_number] = {
            "radius": surface.Radius,
            "thickness": surface.Thickness,
            "glass": str(surface.Material or ""),
            "semi_diameter": surface.SemiDiameter,
            "comment": str(surface.Comment or ""),
            "conic": _safe_get(surface, "Conic"),
            "even_terms": {term: _get_even_term(surface, term) for term in EVEN_TERMS},
        }
    return data


def _failures_for_unexpected_changes(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
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

        if surface_number in ALLOWED_THICKNESS_CHANGES:
            expected = ALLOWED_THICKNESS_CHANGES[surface_number]
            if not _same_value(after_row["thickness"], expected):
                failures.append(f"S{surface_number} Thickness expected {expected}, got {after_row['thickness']}")
        elif not _same_value(before_row["thickness"], after_row["thickness"]):
            failures.append(f"S{surface_number} Thickness changed unexpectedly: {before_row['thickness']} -> {after_row['thickness']}")

        if surface_number in ALLOWED_SEMI_DIAMETER_CHANGES:
            expected = ALLOWED_SEMI_DIAMETER_CHANGES[surface_number]
            if not _same_value(after_row["semi_diameter"], expected):
                failures.append(f"S{surface_number} SemiDiameter expected {expected}, got {after_row['semi_diameter']}")
        elif not _same_value(before_row["semi_diameter"], after_row["semi_diameter"]):
            warnings.append(
                f"S{surface_number} SemiDiameter changed unexpectedly: "
                f"{before_row['semi_diameter']} -> {after_row['semi_diameter']}"
            )

    return failures, warnings


def _set_semidiameter(surface: Any, value: float) -> None:
    old_value = surface.SemiDiameter
    cell = _safe_get(surface, "SemiDiameterCell")
    if cell is not None:
        for method_name in ("MakeSolveFixed", "MakeSolveNone"):
            method = _safe_get(cell, method_name)
            if callable(method):
                try:
                    method()
                    break
                except Exception:
                    pass
    try:
        surface.SemiDiameter = value
    except Exception as exc:
        raise RuntimeError(
            f"Failed to set S{surface.SurfaceNumber} SemiDiameter. "
            "It may be controlled by an automatic/solve setting."
        ) from exc

    actual = surface.SemiDiameter
    if not _same_value(actual, value):
        try:
            surface.SemiDiameter = old_value
        except Exception:
            pass
        raise RuntimeError(
            f"S{surface.SurfaceNumber} SemiDiameter readback mismatch after set: "
            f"expected {value}, got {actual}. It may be automatic/solve-controlled."
        )


def _print_related(before: dict[int, dict[str, Any]], after: dict[int, dict[str, Any]] | None = None) -> None:
    for surface_number in (2, 3, 4, 7, 9):
        row = before[surface_number]
        print(
            f"before S{surface_number}: "
            f"Radius={row['radius']}, Thickness={row['thickness']}, "
            f"Glass={row['glass']!r}, SemiDiameter={row['semi_diameter']}",
            flush=True,
        )
        if after is not None:
            new = after[surface_number]
            print(
                f"after  S{surface_number}: "
                f"Radius={new['radius']}, Thickness={new['thickness']}, "
                f"Glass={new['glass']!r}, SemiDiameter={new['semi_diameter']}",
                flush=True,
            )


def _print_plan_targets(before: dict[int, dict[str, Any]]) -> None:
    print("Plan B target values:", flush=True)
    print(
        f"S2 SemiDiameter: {before[2]['semi_diameter']} -> {TARGET_VALUES['s2_semi_diameter']}",
        flush=True,
    )
    print(
        f"S3 SemiDiameter: {before[3]['semi_diameter']} -> {TARGET_VALUES['s3_semi_diameter']}",
        flush=True,
    )
    print(f"S4 Thickness: {before[4]['thickness']} -> {TARGET_VALUES['s4_thickness']}", flush=True)
    print(f"S7 Thickness: {before[7]['thickness']} -> {TARGET_VALUES['s7_thickness']}", flush=True)
    print(f"S9 Thickness: {before[9]['thickness']} -> {TARGET_VALUES['s9_thickness']}", flush=True)


def _precheck_thickness_values(before: dict[int, dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for surface_number, target in ALLOWED_THICKNESS_CHANGES.items():
        current = before[surface_number]["thickness"]
        original = EXPECTED_ORIGINAL_THICKNESS[surface_number]
        if _same_value(current, target, PRECHECK_TOLERANCE):
            messages.append(f"S{surface_number} Thickness already applied: {current}")
            continue
        if _same_value(current, original, PRECHECK_TOLERANCE):
            messages.append(f"S{surface_number} Thickness precheck ok: current={current}, target={target}")
            continue
        raise RuntimeError(
            f"S{surface_number} Thickness precheck failed: expected near {original} or already {target}, got {current}"
        )
    return messages


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


def apply_geometry_repair_plan_b(lens_path: str, apply: bool) -> None:
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

    lde = oss.LDE
    if int(lde.NumberOfSurfaces) <= 9:
        print(f"[ERROR] Lens has too few surfaces: {lde.NumberOfSurfaces}", flush=True)
        raise SystemExit(1)

    before = _snapshot(oss)
    print("Before parameters:", flush=True)
    _print_related(before)
    _print_plan_targets(before)

    if not apply:
        print("save status: dry-run only; lens not modified and not saved.", flush=True)
        print("dry-run completed successfully.", flush=True)
        return

    try:
        for message in _precheck_thickness_values(before):
            print(message, flush=True)
    except Exception as exc:
        print("[ERROR] Precheck failed. Lens was not modified or saved by this script.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    try:
        _set_semidiameter(lde.GetSurfaceAt(2), TARGET_VALUES["s2_semi_diameter"])
        _set_semidiameter(lde.GetSurfaceAt(3), TARGET_VALUES["s3_semi_diameter"])
        lde.GetSurfaceAt(4).Thickness = TARGET_VALUES["s4_thickness"]
        lde.GetSurfaceAt(7).Thickness = TARGET_VALUES["s7_thickness"]
        lde.GetSurfaceAt(9).Thickness = TARGET_VALUES["s9_thickness"]
    except Exception as exc:
        print("[ERROR] Failed while applying Plan B edits. Lens was not saved by this script.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    after = _snapshot(oss)
    print("After parameters:", flush=True)
    _print_related(before, after)

    failures, warnings = _failures_for_unexpected_changes(before, after)
    if failures:
        print("[ERROR] Safety check failed. Lens was not saved by this script.", flush=True)
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
        print("[ERROR] Saved, but failed to reopen/re-read lens for verification.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    verify_failures, verify_warnings = _failures_for_unexpected_changes(before, verify)
    if verify_failures:
        print("[ERROR] Post-save verification failed.", flush=True)
        for failure in verify_failures:
            print(f"[ERROR] {failure}", flush=True)
        raise SystemExit(1)
    for warning in verify_warnings:
        print(f"[WARNING] post-save: {warning}", flush=True)

    print(f"old S2 semi-diameter: {before[2]['semi_diameter']}", flush=True)
    print(f"new S2 semi-diameter: {verify[2]['semi_diameter']}", flush=True)
    print(f"old S3 semi-diameter: {before[3]['semi_diameter']}", flush=True)
    print(f"new S3 semi-diameter: {verify[3]['semi_diameter']}", flush=True)
    print(f"old S4 thickness: {before[4]['thickness']}", flush=True)
    print(f"new S4 thickness: {verify[4]['thickness']}", flush=True)
    print(f"old S7 thickness: {before[7]['thickness']}", flush=True)
    print(f"new S7 thickness: {verify[7]['thickness']}", flush=True)
    print(f"old S9 thickness: {before[9]['thickness']}", flush=True)
    print(f"new S9 thickness: {verify[9]['thickness']}", flush=True)
    print("save status: saved successfully", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply CN117 Plan B geometry repair with strict safety checks.")
    parser.add_argument("--lens", required=True, help="Lens path to modify only when --apply is provided.")
    parser.add_argument("--apply", action="store_true", help="Actually save the Plan B edits to the original lens.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    apply_geometry_repair_plan_b(args.lens, args.apply)
