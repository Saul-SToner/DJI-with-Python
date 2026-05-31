from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import zospy as zp

LENS_PATH = Path(r"C:\Users\L2791\OneDrive\Desktop\PatentSeed_US20170293107A1_Emb1_unmodified.zos")
S2_THICKNESS = 2.20
S4_THICKNESS = 0.70
ALLOWED_THICKNESS_CHANGES = {2: S2_THICKNESS, 4: S4_THICKNESS}


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number


def _same_number(a: Any, b: Any, tolerance: float = 1e-10) -> bool:
    fa = _to_float(a)
    fb = _to_float(b)
    if fa is None or fb is None:
        return a == b
    if math.isinf(fa) or math.isinf(fb):
        return math.isinf(fa) and math.isinf(fb) and (fa > 0) == (fb > 0)
    return abs(fa - fb) <= tolerance


def _snapshot_basic_lde(oss: Any) -> dict[int, dict[str, Any]]:
    lde = oss.LDE
    snapshot: dict[int, dict[str, Any]] = {}
    for surface_number in range(int(lde.NumberOfSurfaces)):
        surface = lde.GetSurfaceAt(surface_number)
        snapshot[surface_number] = {
            "radius": surface.Radius,
            "thickness": surface.Thickness,
            "material": str(surface.Material or ""),
            "comment": str(surface.Comment or ""),
        }
    return snapshot


def _assert_only_allowed_changes(before: dict[int, dict[str, Any]], after: dict[int, dict[str, Any]]) -> None:
    if set(before) != set(after):
        raise RuntimeError(f"Surface set changed unexpectedly: before={sorted(before)}, after={sorted(after)}")

    failures: list[str] = []
    for surface_number, before_row in before.items():
        after_row = after[surface_number]

        if not _same_number(before_row["radius"], after_row["radius"]):
            failures.append(
                f"S{surface_number} Radius changed: {before_row['radius']} -> {after_row['radius']}"
            )
        if before_row["material"] != after_row["material"]:
            failures.append(
                f"S{surface_number} Material changed: {before_row['material']!r} -> {after_row['material']!r}"
            )

        if surface_number in ALLOWED_THICKNESS_CHANGES:
            expected = ALLOWED_THICKNESS_CHANGES[surface_number]
            if not _same_number(after_row["thickness"], expected):
                failures.append(
                    f"S{surface_number} Thickness expected {expected}, got {after_row['thickness']}"
                )
        elif not _same_number(before_row["thickness"], after_row["thickness"]):
            failures.append(
                f"S{surface_number} Thickness changed unexpectedly: "
                f"{before_row['thickness']} -> {after_row['thickness']}"
            )

    if failures:
        raise RuntimeError("Unexpected LDE modifications detected:\n" + "\n".join(failures))


def repair_front_air_gaps() -> None:
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print(
            "[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.",
            flush=True,
        )
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    if not LENS_PATH.exists():
        print(f"[ERROR] Lens file does not exist: {LENS_PATH}", flush=True)
        raise SystemExit(1)

    try:
        oss.load(str(LENS_PATH), saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens: {LENS_PATH}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    lde = oss.LDE
    if int(lde.NumberOfSurfaces) <= 4:
        print(f"[ERROR] Lens has too few surfaces: NumberOfSurfaces={lde.NumberOfSurfaces}", flush=True)
        raise SystemExit(1)

    before = _snapshot_basic_lde(oss)
    s2 = lde.GetSurfaceAt(2)
    s4 = lde.GetSurfaceAt(4)

    old_s2 = s2.Thickness
    old_s4 = s4.Thickness
    print(f"old S2 thickness: {old_s2}", flush=True)
    print(f"old S4 thickness: {old_s4}", flush=True)

    s2.Thickness = S2_THICKNESS
    s4.Thickness = S4_THICKNESS

    new_s2 = s2.Thickness
    new_s4 = s4.Thickness
    print(f"new S2 thickness: {new_s2}", flush=True)
    print(f"new S4 thickness: {new_s4}", flush=True)

    after = _snapshot_basic_lde(oss)
    try:
        _assert_only_allowed_changes(before, after)
    except Exception as exc:
        print("[ERROR] Safety check failed before save. Lens was not saved by this script.", flush=True)
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        raise SystemExit(1) from exc

    try:
        oss.save()
    except Exception as exc:
        print(f"[ERROR] Failed to save lens to original path: {LENS_PATH}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    print(f"lens path: {LENS_PATH}", flush=True)
    print(f"old S2 thickness: {old_s2}", flush=True)
    print(f"new S2 thickness: {new_s2}", flush=True)
    print(f"old S4 thickness: {old_s4}", flush=True)
    print(f"new S4 thickness: {new_s4}", flush=True)
    print("saved successfully", flush=True)


if __name__ == "__main__":
    repair_front_air_gaps()
