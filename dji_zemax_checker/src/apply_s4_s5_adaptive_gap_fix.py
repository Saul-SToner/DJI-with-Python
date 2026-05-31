from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zospy as zp


SURFACE_A = 4
SURFACE_B = 5
TARGET_MARGIN = 0.10
TTL_LIMIT = 18.0
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
SAMPLE_COUNT = 800
TOLERANCE = 1e-8
_LIVE_ZOS_CONNECTIONS: list[Any] = []


@dataclass
class SurfaceData:
    surface_number: int
    radius: float | None
    thickness: float | None
    glass: str
    semi_diameter: float | None
    conic: float | None
    even_terms: dict[int, float | None]


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _same_value(left: Any, right: Any, tolerance: float = TOLERANCE) -> bool:
    a = _to_float(left)
    b = _to_float(right)
    if a is None or b is None:
        return str(left) == str(right)
    if math.isinf(a) or math.isinf(b):
        return math.isinf(a) and math.isinf(b) and (a > 0) == (b > 0)
    return abs(a - b) <= tolerance


def _fmt(value: Any, digits: int = 9) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    return f"{number:.{digits}g}"


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _get_even_term(surface: Any, term: int) -> float | None:
    data = _safe_get(surface, "SurfaceData")
    if data is None:
        return None
    method = _safe_get(data, "GetNthEvenOrderTerm")
    if callable(method):
        try:
            return _to_float(method(term))
        except Exception:
            pass
    cell_method = _safe_get(data, "NthEvenOrderTermCell")
    if callable(cell_method):
        try:
            cell = cell_method(term)
            for attr in ("DoubleValue", "Value"):
                value = _to_float(_safe_get(cell, attr))
                if value is not None:
                    return value
        except Exception:
            pass
    return None


def _read_surface(surface: Any) -> SurfaceData:
    return SurfaceData(
        surface_number=int(_safe_get(surface, "SurfaceNumber", -1)),
        radius=_to_float(_safe_get(surface, "Radius")),
        thickness=_to_float(_safe_get(surface, "Thickness")),
        glass=str(_safe_get(surface, "Material", "") or ""),
        semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
        conic=_to_float(_safe_get(surface, "Conic")),
        even_terms={term: _get_even_term(surface, term) for term in EVEN_TERMS},
    )


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
            "conic": _safe_get(surface, "Conic"),
            "even_terms": {term: _get_even_term(surface, term) for term in EVEN_TERMS},
        }
    return rows


def _is_plane(radius: float | None) -> bool:
    return radius is None or radius == 0.0 or math.isinf(radius)


def _formula_sag(surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    radius = surface.radius
    conic = surface.conic or 0.0
    if _is_plane(radius):
        base = 0.0
    else:
        assert radius is not None
        c = 1.0 / radius
        sqrt_arg = 1.0 - (1.0 + conic) * c * c * r * r
        if sqrt_arg < 0:
            return None, f"invalid sag sqrt argument {sqrt_arg:g}"
        denom = 1.0 + math.sqrt(sqrt_arg)
        if denom == 0:
            return None, "invalid sag denominator zero"
        base = c * r * r / denom
    asphere = 0.0
    for term, coeff in surface.even_terms.items():
        if coeff is not None:
            asphere += coeff * (r**term)
    return base + asphere, None


def _surface_sag(lde: Any, surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    try:
        result = lde.GetSag(surface.surface_number, r, 0.0)
        if isinstance(result, tuple) and result and not (isinstance(result[0], bool) and not result[0]):
            for item in result[1:]:
                value = _to_float(item)
                if value is not None:
                    return value, None
    except Exception as exc:
        zemax_warning = f"GetSag failed: {type(exc).__name__}: {exc!r}"
    else:
        zemax_warning = f"GetSag returned no finite sag: {result!r}"

    sag, warning = _formula_sag(surface, r)
    if sag is not None:
        return sag, f"formula fallback after {zemax_warning}"
    return None, f"{zemax_warning}; {warning}"


def _min_gap_s4_s5(lde: Any, s4: SurfaceData, s5: SurfaceData) -> tuple[float | None, float | None, float | None, str]:
    if s4.thickness is None:
        return None, None, None, "S4 thickness unknown"
    if s4.semi_diameter is None or s5.semi_diameter is None:
        return None, None, None, "S4/S5 semi-diameter unknown"
    radius_max = min(s4.semi_diameter, s5.semi_diameter)
    min_gap: float | None = None
    min_radius: float | None = None
    invalid: list[str] = []
    for index in range(SAMPLE_COUNT + 1):
        r = radius_max * index / SAMPLE_COUNT
        sag4, warn4 = _surface_sag(lde, s4, r)
        sag5, warn5 = _surface_sag(lde, s5, r)
        if sag4 is None or sag5 is None:
            invalid.append(f"r={r:g}: S4 {warn4}; S5 {warn5}")
            continue
        gap = s4.thickness + sag5 - sag4
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_radius = r
    note = f"{len(invalid)} invalid samples; first: {invalid[0]}" if invalid else ""
    return min_gap, min_radius, radius_max, note


def _ttl_s1_to_image(oss: Any) -> float | None:
    lde = oss.LDE
    total = 0.0
    found = False
    for surface_number in range(1, int(lde.NumberOfSurfaces) - 1):
        thickness = _to_float(lde.GetSurfaceAt(surface_number).Thickness)
        if thickness is None:
            continue
        total += thickness
        found = True
    return total if found else None


def _validate_only_allowed_changes(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
    target_thickness: float,
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

        if surface_number == SURFACE_A:
            if not _same_value(after_row["thickness"], target_thickness):
                failures.append(f"S4 Thickness expected {target_thickness}, got {after_row['thickness']}")
            if not _same_value(before_row["semi_diameter"], after_row["semi_diameter"]):
                failures.append(f"S4 SemiDiameter changed: {before_row['semi_diameter']} -> {after_row['semi_diameter']}")
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


def apply_s4_s5_adaptive_gap_fix(lens_path: str, apply: bool, force: bool) -> None:
    lens_file = Path(lens_path)
    if not lens_file.exists():
        print(f"[ERROR] Lens file does not exist: {lens_path}", flush=True)
        raise SystemExit(1)

    print(f"lens path: {lens_path}", flush=True)
    print(f"mode: {'apply' if apply else 'dry-run'}", flush=True)
    print(f"force: {str(force).lower()}", flush=True)
    oss = _connect_extension()
    try:
        oss.load(lens_path, saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens: {lens_path}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    lde = oss.LDE
    if int(lde.NumberOfSurfaces) <= SURFACE_B:
        print(f"[ERROR] Lens has too few surfaces: {lde.NumberOfSurfaces}", flush=True)
        raise SystemExit(1)

    before = _snapshot(oss)
    s4 = _read_surface(lde.GetSurfaceAt(SURFACE_A))
    s5 = _read_surface(lde.GetSurfaceAt(SURFACE_B))
    ttl = _ttl_s1_to_image(oss)
    min_gap, min_radius, sampled_radius, note = _min_gap_s4_s5(lde, s4, s5)
    if min_gap is None or s4.thickness is None:
        print(f"[ERROR] Could not calculate S4->S5 min_gap: {note}", flush=True)
        raise SystemExit(1)

    delta = max(0.0, TARGET_MARGIN - min_gap)
    target_thickness = s4.thickness + delta
    estimated_ttl = None if ttl is None else ttl + delta
    ttl_risk = estimated_ttl is not None and estimated_ttl >= TTL_LIMIT

    print(f"current S4 Thickness: {_fmt(s4.thickness)}", flush=True)
    print(f"current S4 Semi-Diameter: {_fmt(s4.semi_diameter)}", flush=True)
    print(f"current S5 Semi-Diameter: {_fmt(s5.semi_diameter)}", flush=True)
    print(f"S4->S5 sampled radius max: {_fmt(sampled_radius)}", flush=True)
    print(f"current_min_gap: {_fmt(min_gap)}", flush=True)
    print(f"current_min_gap_radius: {_fmt(min_radius)}", flush=True)
    print(f"target_margin: {_fmt(TARGET_MARGIN)}", flush=True)
    print(f"delta: {_fmt(delta)}", flush=True)
    print(f"target S4 Thickness: {_fmt(target_thickness)}", flush=True)
    print(f"current TTL estimate: {_fmt(ttl)}", flush=True)
    print(f"estimated TTL after fix: {_fmt(estimated_ttl)}", flush=True)
    if note:
        print(f"[WARNING] gap calculation note: {note}", flush=True)

    if min_gap >= TARGET_MARGIN:
        print("status: already safe; no modification needed.", flush=True)
        print("save status: not saved", flush=True)
        return

    if ttl_risk:
        print(f"[WARNING] estimated TTL after fix is >= {TTL_LIMIT} mm.", flush=True)
        if not force:
            print("[ERROR] TTL risk detected. Re-run with --force to allow apply.", flush=True)
            if apply:
                print("save status: not saved", flush=True)
                raise SystemExit(1)

    if not apply:
        print("save status: dry-run only; lens not modified and not saved.", flush=True)
        print("dry-run completed successfully.", flush=True)
        return

    try:
        lde.GetSurfaceAt(SURFACE_A).Thickness = target_thickness
    except Exception as exc:
        print("[ERROR] Failed while setting S4 Thickness. Lens was not saved.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    after = _snapshot(oss)
    failures, warnings = _validate_only_allowed_changes(before, after, target_thickness)
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
        verify_s4 = _read_surface(oss.LDE.GetSurfaceAt(SURFACE_A))
        verify_s5 = _read_surface(oss.LDE.GetSurfaceAt(SURFACE_B))
        verify_gap, verify_radius, _, verify_note = _min_gap_s4_s5(oss.LDE, verify_s4, verify_s5)
    except Exception as exc:
        print("[ERROR] Saved, but failed to reload/re-read lens for verification.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    verify_failures, verify_warnings = _validate_only_allowed_changes(before, verify, target_thickness)
    if verify_failures:
        print("[ERROR] Post-save verification failed.", flush=True)
        for failure in verify_failures:
            print(f"[ERROR] {failure}", flush=True)
        raise SystemExit(1)
    for warning in verify_warnings:
        print(f"[WARNING] post-save: {warning}", flush=True)

    print(f"S4 old Thickness: {before[4]['thickness']}", flush=True)
    print(f"S4 new Thickness: {verify[4]['thickness']}", flush=True)
    print(f"S4 Semi-Diameter unchanged: {verify[4]['semi_diameter']}", flush=True)
    print(f"post_save_min_gap: {_fmt(verify_gap)}", flush=True)
    print(f"post_save_min_gap_radius: {_fmt(verify_radius)}", flush=True)
    if verify_note:
        print(f"[WARNING] post-save gap calculation note: {verify_note}", flush=True)
    if verify_gap is not None and verify_gap < TARGET_MARGIN:
        print(f"[WARNING] post-save S4->S5 min_gap is still below {TARGET_MARGIN} mm.", flush=True)
    print("save status: saved successfully", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive S4->S5 air-gap fix by changing only S4 Thickness.")
    parser.add_argument("--lens", required=True, help="Lens path to modify only when --apply is provided.")
    parser.add_argument("--apply", action="store_true", help="Actually save the S4 Thickness fix to the original lens.")
    parser.add_argument("--force", action="store_true", help="Allow apply even if estimated TTL after fix is >= 18 mm.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    apply_s4_s5_adaptive_gap_fix(args.lens, args.apply, args.force)
