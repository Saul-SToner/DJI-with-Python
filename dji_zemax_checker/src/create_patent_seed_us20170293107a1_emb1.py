from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import zospy as zp

OUTPUT_PATH = Path(
    r"C:\Users\L2791\OneDrive\Desktop\PatentSeed_US20170293107A1_Emb1_unmodified.ZOS"
)

APERTURE_F_NUMBER = 2.0
FIELD_ANGLES_DEG = [0.0, 21.0, 35.0, 49.0, 63.0, 70.0, 80.0]
WAVELENGTHS_UM = [0.470, 0.550, 0.650]

EVEN_ASPHERE_SURFACES = {1, 2, 3, 4, 5, 6, 12, 13}
STOP_SURFACE = 9

# Surface numbers are Zemax sequential LDE numbers.  The image surface is added
# after S16 by the script; OBJ and IMA are not included in this table.
SURFACES: list[dict[str, Any]] = [
    {"surface": 1, "type": "Even Asphere", "radius": -10.925, "thickness": 0.954, "n": 1.531, "v": 55.754},
    {"surface": 2, "type": "Even Asphere", "radius": 3.454, "thickness": 1.863, "n": None, "v": None},
    {"surface": 3, "type": "Even Asphere", "radius": 43.088, "thickness": 0.551, "n": 1.531, "v": 55.754},
    {"surface": 4, "type": "Even Asphere", "radius": 2.118, "thickness": 0.588, "n": None, "v": None},
    {"surface": 5, "type": "Even Asphere", "radius": 2.731, "thickness": 1.013, "n": 1.636, "v": 23.972},
    {"surface": 6, "type": "Even Asphere", "radius": 3.285, "thickness": 0.227, "n": None, "v": None},
    {"surface": 7, "type": "Standard", "radius": 4.782, "thickness": 1.973, "n": 1.847, "v": 23.778},
    {"surface": 8, "type": "Standard", "radius": -6.916, "thickness": 0.547, "n": None, "v": None},
    {"surface": 9, "type": "Standard STOP", "radius": -8.900, "thickness": 0.612, "n": 1.923, "v": 18.897},
    {"surface": 10, "type": "Standard", "radius": 3.500, "thickness": 1.819, "n": 1.697, "v": 55.532},
    {"surface": 11, "type": "Standard", "radius": -3.912, "thickness": 0.118, "n": None, "v": None},
    {"surface": 12, "type": "Even Asphere", "radius": 5.198, "thickness": 1.974, "n": 1.531, "v": 55.754},
    {"surface": 13, "type": "Even Asphere", "radius": -7.776, "thickness": 2.761, "n": None, "v": None},
    {"surface": 14, "type": "Standard", "radius": math.inf, "thickness": 0.800, "n": 1.517, "v": 64.167},
    {"surface": 15, "type": "Standard", "radius": math.inf, "thickness": 2.600, "n": None, "v": None},
    {"surface": 16, "type": "Standard", "radius": math.inf, "thickness": 0.400, "n": 1.517, "v": 64.167},
]

ASPHERE_COEFFICIENTS: dict[int, dict[str, float]] = {
    1: {"A4": 4.8636e-3, "A6": -1.8355e-4, "A8": 4.4088e-6, "A10": -5.7877e-8, "A12": 3.3790e-10},
    2: {"A4": -9.8072e-3, "A6": 1.5879e-3, "A8": -3.0966e-5, "A10": -5.7476e-6, "A12": 0.0},
    3: {"A4": 6.3618e-3, "A6": -2.0731e-3, "A8": 1.9281e-4, "A10": -6.1805e-6, "A12": 0.0},
    4: {"A4": 4.2738e-2, "A6": -1.3721e-2, "A8": 8.3572e-4, "A10": 3.8572e-5, "A12": 0.0},
    5: {"A4": 7.1455e-3, "A6": -4.4218e-3, "A8": 6.5133e-4, "A10": -8.8262e-5, "A12": 0.0},
    6: {"A4": -5.6176e-4, "A6": 1.4672e-3, "A8": -1.0803e-3, "A10": 3.9596e-5, "A12": 0.0},
    12: {"A4": -1.9814e-4, "A6": -1.4252e-4, "A8": 1.1859e-5, "A10": -2.3742e-7, "A12": 0.0},
    13: {"A4": 5.4287e-3, "A6": -5.2974e-4, "A8": 2.5065e-5, "A10": -4.2085e-8, "A12": 0.0},
}

EVEN_TERM_NUMBER = {"A4": 4, "A6": 6, "A8": 8, "A10": 10, "A12": 12}


def _const(*attrs: str) -> Any:
    obj: Any = zp.constants
    for attr in attrs:
        obj = getattr(obj, attr)
    return obj


def _call(obj: Any, name: str, *args: Any) -> Any:
    return getattr(obj, name)(*args)


def _set_optional_attr(obj: Any, attr: str, value: Any) -> bool:
    try:
        setattr(obj, attr, value)
        return True
    except Exception:
        return False


def _surface_type(surface: Any, name: str) -> Any:
    type_const = _const("Editors", "LDE", "SurfaceType", name)
    return surface.GetSurfaceTypeSettings(type_const)


def _change_surface_type(surface: Any, name: str) -> None:
    settings = _surface_type(surface, name)
    if not surface.ChangeType(settings):
        raise RuntimeError(f"Failed to change surface {surface.SurfaceNumber} to {name}.")


def _ensure_surface_count(lde: Any, image_surface: int) -> None:
    desired_count = image_surface + 1
    while lde.NumberOfSurfaces < desired_count:
        lde.InsertNewSurfaceAt(lde.NumberOfSurfaces - 1)
    while lde.NumberOfSurfaces > desired_count:
        lde.RemoveSurfaceAt(lde.NumberOfSurfaces - 2)


def _set_even_asphere_coefficients(surface: Any, coefficients: dict[str, float]) -> None:
    data = surface.SurfaceData
    failures: list[str] = []
    for coefficient, value in coefficients.items():
        term = EVEN_TERM_NUMBER[coefficient]
        try:
            data.SetNthEvenOrderTerm(term, value)
            continue
        except Exception:
            pass

        try:
            cell = data.NthEvenOrderTermCell(term)
            _set_optional_attr(cell, "DoubleValue", value) or _set_optional_attr(cell, "Value", value)
            continue
        except Exception as exc:
            failures.append(f"{coefficient}={value:g}: {type(exc).__name__}: {exc!r}")

    if failures:
        raise RuntimeError(
            f"Failed to set even asphere coefficients on surface {surface.SurfaceNumber}: "
            + " | ".join(failures)
        )


def _model_glass_string(n: float | None, v: float | None) -> str:
    if n is None or v is None:
        return ""
    # OpticStudio accepts n,V entries in the Material column as model glass.
    return f"{n:.6f},{v:.6f}"


def _configure_aperture(oss: Any) -> None:
    aperture = oss.SystemData.Aperture
    aperture.ApertureType = _const("SystemData", "ZemaxApertureType", "ImageSpaceFNum")
    aperture.ApertureValue = APERTURE_F_NUMBER


def _configure_fields(oss: Any) -> None:
    fields = oss.SystemData.Fields
    fields.SetFieldType(_const("SystemData", "FieldType", "Angle"))
    fields.DeleteAllFields()
    for angle in FIELD_ANGLES_DEG:
        fields.AddField(0.0, angle, 1.0)


def _configure_wavelengths(oss: Any) -> None:
    wavelengths = oss.SystemData.Wavelengths
    while wavelengths.NumberOfWavelengths > 0:
        if not wavelengths.RemoveWavelength(1):
            break

    if wavelengths.NumberOfWavelengths == 0:
        for wave in WAVELENGTHS_UM:
            wavelengths.AddWavelength(wave, 1.0)
    else:
        for index, wave in enumerate(WAVELENGTHS_UM, start=1):
            if index <= wavelengths.NumberOfWavelengths:
                row = wavelengths.GetWavelength(index)
            else:
                row = wavelengths.AddWavelength(wave, 1.0)
            row.Wavelength = wave
            row.Weight = 1.0
        while wavelengths.NumberOfWavelengths > len(WAVELENGTHS_UM):
            wavelengths.RemoveWavelength(len(WAVELENGTHS_UM) + 1)

    wavelengths.GetWavelength(2).MakePrimary()


def _configure_lens_data(oss: Any) -> None:
    lde = oss.LDE
    image_surface = len(SURFACES) + 1
    _ensure_surface_count(lde, image_surface)

    try:
        obj = lde.GetSurfaceAt(0)
        obj.Comment = "OBJ"
        obj.Radius = math.inf
        obj.Thickness = math.inf
    except Exception:
        pass

    for data in SURFACES:
        surface_number = int(data["surface"])
        surface = lde.GetSurfaceAt(surface_number)
        surface.Comment = f"S{surface_number}" + (" STOP" if surface_number == STOP_SURFACE else "")

        if surface_number in EVEN_ASPHERE_SURFACES:
            _change_surface_type(surface, "EvenAspheric")
        else:
            _change_surface_type(surface, "Standard")

        surface.Radius = data["radius"]
        surface.Thickness = data["thickness"]
        surface.Material = _model_glass_string(data["n"], data["v"])
        surface.Conic = 0.0

        if surface_number in ASPHERE_COEFFICIENTS:
            _set_even_asphere_coefficients(surface, ASPHERE_COEFFICIENTS[surface_number])

    lde.GetSurfaceAt(STOP_SURFACE).IsStop = True

    image = lde.GetSurfaceAt(image_surface)
    image.Comment = "IMA"
    image.Radius = math.inf
    image.Thickness = 0.0
    image.Material = ""


def _finite_thickness_total() -> float:
    return sum(float(row["thickness"]) for row in SURFACES if math.isfinite(float(row["thickness"])))


def _first_order_summary(oss: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "efl": None,
        "f_number": APERTURE_F_NUMBER,
        "ttl": _finite_thickness_total(),
    }

    try:
        first_order = oss.LDE.GetFirstOrderData()
        if isinstance(first_order, tuple):
            numeric = [value for value in first_order if isinstance(value, (int, float))]
            if numeric:
                summary["efl"] = numeric[0]
    except Exception:
        pass

    try:
        from export_system_summary import _direct_optical_summary

        direct = _direct_optical_summary(oss)
        summary["efl"] = direct.get("efl") if direct.get("efl") is not None else summary["efl"]
        summary["f_number"] = direct.get("f_number") if direct.get("f_number") is not None else summary["f_number"]
        summary["ttl"] = direct.get("ttl") if direct.get("ttl") is not None else summary["ttl"]
    except Exception:
        pass

    return summary


def create_patent_seed() -> None:
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

    print("Creating new sequential lens...", flush=True)
    oss.new(saveifneeded=False)
    oss.make_sequential()

    _configure_aperture(oss)
    _configure_fields(oss)
    _configure_wavelengths(oss)
    _configure_lens_data(oss)

    try:
        oss.update_status()
    except Exception:
        pass

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    oss.save_as(str(OUTPUT_PATH))

    summary = _first_order_summary(oss)
    print("\nPrescription Summary", flush=True)
    print(f"EFL: {summary['efl']}", flush=True)
    print(f"F/#: {summary['f_number']}", flush=True)
    print(f"TTL: {summary['ttl']}", flush=True)
    print(f"number of surfaces: {oss.LDE.NumberOfSurfaces}", flush=True)
    print(f"output path: {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    create_patent_seed()
