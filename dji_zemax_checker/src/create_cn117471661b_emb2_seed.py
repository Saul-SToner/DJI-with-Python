from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
from typing import Any

import zospy as zp


PROTECTED_OLD_SEED = Path(
    r"C:\Users\L2791\OneDrive\Desktop\PatentSeed_US20170293107A1_Emb1_unmodified.zos"
)

APERTURE_F_NUMBER = 2.02
FIELD_ANGLES_DEG = [0.0, 21.0, 35.0, 49.0, 63.0, 70.0, 80.0, 100.0]
WAVELENGTHS: list[tuple[float, float]] = [
    (0.4861, 1.0),
    (0.5461, 2.0),
    (0.5876, 3.0),
    (0.6563, 1.0),
]

# CN117471661B / CN117471661A Embodiment 2 reference values.
# The patent does not disclose semi-diameters or BFL; semi-diameters are left
# automatic and BFL is read from OpticStudio after file creation if available.
REFERENCE = {
    "efl_mm": 2.06,
    "f_number": 2.02,
    "fov_deg": 200.0,
    "ttl_mm": 15.94,
    "image_height_mm": 3.55,
    "d1_mm": 15.42,
    "bfl_mm": None,
}

# Surface numbers are Zemax sequential LDE numbers.  OBJ is surface 0 and IMA
# is inserted after S18 as surface 19.  Glass values are Model Glass n,Vd
# entries and represent the medium after the listed surface.
SURFACES: list[dict[str, Any]] = [
    {"surface": 1, "comment": "S1", "type": "Standard", "radius": 13.384, "thickness": 1.700, "n": 1.95, "v": 32.32, "conic": 0.0},
    {"surface": 2, "comment": "S2", "type": "Standard", "radius": 4.027, "thickness": 1.948, "n": None, "v": None, "conic": 0.0},
    {"surface": 3, "comment": "S3", "type": "Even Asphere", "radius": 8.820, "thickness": 0.600, "n": 1.54, "v": 55.71, "conic": 3.4889e0},
    {"surface": 4, "comment": "S4", "type": "Even Asphere", "radius": 3.306, "thickness": 2.259, "n": None, "v": None, "conic": -1.982e-1},
    {"surface": 5, "comment": "S5", "type": "Even Asphere", "radius": -2.263, "thickness": 0.610, "n": 1.66, "v": 20.37, "conic": -4.222e-1},
    {"surface": 6, "comment": "S6", "type": "Even Asphere", "radius": -5.672, "thickness": 0.050, "n": None, "v": None, "conic": -1.323e1},
    {"surface": 7, "comment": "S7", "type": "Standard", "radius": 6.079, "thickness": 1.671, "n": 1.85, "v": 23.78, "conic": 0.0},
    {"surface": 8, "comment": "S8", "type": "Standard", "radius": -8.787, "thickness": 0.199, "n": None, "v": None, "conic": 0.0},
    {"surface": 9, "comment": "S9", "type": "Even Asphere", "radius": 4.016, "thickness": 1.190, "n": 1.54, "v": 55.71, "conic": 2.2988e0},
    {"surface": 10, "comment": "S10", "type": "Even Asphere", "radius": -26.708, "thickness": 0.222, "n": None, "v": None, "conic": 9.4228e1},
    {"surface": 11, "comment": "STO", "type": "Standard STOP", "radius": math.inf, "thickness": 0.157, "n": None, "v": None, "conic": 0.0},
    {"surface": 12, "comment": "S12", "type": "Even Asphere", "radius": 4.436, "thickness": 1.668, "n": 1.54, "v": 55.71, "conic": 0.0},
    {"surface": 13, "comment": "S13", "type": "Even Asphere", "radius": -1.545, "thickness": 0.600, "n": 1.66, "v": 20.37, "conic": -2.465e0},
    {"surface": 14, "comment": "S14", "type": "Even Asphere", "radius": 12.410, "thickness": 0.463, "n": None, "v": None, "conic": -9.500e1},
    {"surface": 15, "comment": "S15", "type": "Even Asphere", "radius": 4.529, "thickness": 0.903, "n": 1.54, "v": 55.71, "conic": -1.512e1},
    {"surface": 16, "comment": "S16", "type": "Even Asphere", "radius": 7.122, "thickness": 0.700, "n": None, "v": None, "conic": -1.571e1},
    {"surface": 17, "comment": "S17 FILTER", "type": "Standard", "radius": math.inf, "thickness": 0.300, "n": 1.52, "v": 64.20, "conic": 0.0},
    {"surface": 18, "comment": "S18", "type": "Standard", "radius": math.inf, "thickness": 0.696, "n": None, "v": None, "conic": 0.0},
]

ASPHERE_COEFFICIENTS: dict[int, dict[str, float]] = {
    3: {"A4": -5.665e-4, "A6": -3.030e-4, "A8": 4.5866e-5, "A10": -1.132e-6, "A12": -8.363e-8, "A14": 3.9371e-9, "A16": 0.0},
    4: {"A4": 8.3165e-4, "A6": -2.413e-4, "A8": -1.781e-5, "A10": 1.6282e-5, "A12": 3.6919e-14, "A14": 6.6521e-16, "A16": 0.0},
    5: {"A4": 2.6264e-2, "A6": -1.760e-3, "A8": 1.0761e-4, "A10": 7.4129e-7, "A12": 7.3782e-7, "A14": 4.4972e-13, "A16": 0.0},
    6: {"A4": 2.1149e-2, "A6": 4.5430e-4, "A8": -1.494e-4, "A10": 1.6782e-7, "A12": -4.168e-13, "A14": 7.0270e-17, "A16": 0.0},
    9: {"A4": 6.3166e-3, "A6": 8.7986e-5, "A8": -1.053e-4, "A10": 4.1535e-5, "A12": -3.087e-6, "A14": -9.106e-7, "A16": -1.993e-19},
    10: {"A4": 3.6821e-3, "A6": -6.889e-5, "A8": 5.4810e-4, "A10": -1.395e-4, "A12": 3.0785e-6, "A14": 2.5764e-6, "A16": -3.319e-19},
    12: {"A4": -3.528e-3, "A6": -2.724e-3, "A8": 1.0170e-3, "A10": -5.181e-4, "A12": 4.1093e-17, "A14": -5.054e-18, "A16": 0.0},
    13: {"A4": -5.501e-2, "A6": 1.5298e-3, "A8": -1.856e-3, "A10": 7.7710e-4, "A12": 2.4809e-16, "A14": -5.303e-19, "A16": 0.0},
    14: {"A4": 1.4741e-2, "A6": -9.254e-5, "A8": -2.595e-4, "A10": 2.0971e-5, "A12": -7.154e-15, "A14": -5.217e-17, "A16": 0.0},
    15: {"A4": -3.771e-3, "A6": 1.0033e-3, "A8": -1.305e-4, "A10": 6.5361e-6, "A12": -5.938e-8, "A14": 1.4072e-15, "A16": 0.0},
    16: {"A4": -9.810e-3, "A6": 1.1786e-3, "A8": -1.255e-4, "A10": 4.4847e-6, "A12": -2.648e-7, "A14": -1.280e-14, "A16": 0.0},
}

EVEN_TERM_NUMBER = {"A4": 4, "A6": 6, "A8": 8, "A10": 10, "A12": 12, "A14": 14, "A16": 16}
STOP_SURFACE = 11
IMAGE_SURFACE = 19

# ZOSPy's OpticStudioSystem stores only a weak reference to the ZOS instance.
# Keep a strong reference alive for the whole script, otherwise the .NET
# remoting connection can be finalized before the first LDE/SystemData access.
_LIVE_ZOS_CONNECTIONS: list[Any] = []


def _const(*attrs: str) -> Any:
    obj: Any = zp.constants
    for attr in attrs:
        obj = getattr(obj, attr)
    return obj


def _same_windows_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(os.path.normpath(str(right)))


def _path_from_system_file(system_file: Any) -> Path | None:
    try:
        text = str(system_file)
    except Exception:
        return None
    if not text or text.lower() == "none":
        return None
    try:
        return Path(text).expanduser().resolve()
    except Exception:
        return None


def _validate_output_path(output_path: Path, *, modify_existing: bool = False) -> Path:
    output_path = output_path.expanduser().resolve()
    protected = PROTECTED_OLD_SEED.resolve()
    if _same_windows_path(output_path, protected) and not modify_existing:
        raise ValueError(f"Refusing to overwrite protected old seed: {protected}")
    if modify_existing:
        if not output_path.exists():
            raise FileNotFoundError(f"--modify-existing requires an existing lens file: {output_path}")
    elif output_path.exists():
        raise FileExistsError(
            f"Output already exists, refusing to modify an existing lens file: {output_path}"
        )
    if output_path.suffix.lower() not in {".zos", ".zmx"}:
        raise ValueError("Output path must end with .zos or .zmx.")
    return output_path


def _surface_type(surface: Any, name: str) -> Any:
    surface_type = _const("Editors", "LDE", "SurfaceType", name)
    return surface.GetSurfaceTypeSettings(surface_type)


def _change_surface_type(surface: Any, surface_type_name: str) -> None:
    settings = _surface_type(surface, surface_type_name)
    if not surface.ChangeType(settings):
        raise RuntimeError(
            f"Failed to change surface {surface.SurfaceNumber} to {surface_type_name}."
        )


def _set_optional_attr(obj: Any, attr: str, value: Any) -> bool:
    try:
        setattr(obj, attr, value)
        return True
    except Exception:
        return False


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
            if _set_optional_attr(cell, "DoubleValue", value) or _set_optional_attr(cell, "Value", value):
                continue
            failures.append(f"{coefficient}={value:g}: coefficient cell has no writable value attribute")
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
    return f"{n:.6f},{v:.6f}"


def _ensure_surface_count(lde: Any, image_surface: int) -> None:
    desired_count = image_surface + 1
    while lde.NumberOfSurfaces < desired_count:
        lde.InsertNewSurfaceAt(lde.NumberOfSurfaces - 1)
    while lde.NumberOfSurfaces > desired_count:
        lde.RemoveSurfaceAt(lde.NumberOfSurfaces - 2)


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

    for wave, weight in WAVELENGTHS:
        wavelengths.AddWavelength(wave, weight)

    # Use the d-line as primary wavelength.
    try:
        wavelengths.GetWavelength(3).MakePrimary()
    except Exception:
        pass


def _configure_lens_data(oss: Any) -> None:
    lde = oss.LDE
    _ensure_surface_count(lde, IMAGE_SURFACE)

    obj = lde.GetSurfaceAt(0)
    obj.Comment = "OBJ"
    obj.Radius = 2000.0
    obj.Thickness = 1000.0
    obj.Material = ""

    for row in SURFACES:
        surface_number = int(row["surface"])
        surface = lde.GetSurfaceAt(surface_number)
        surface.Comment = str(row["comment"])

        if row["type"] == "Even Asphere":
            _change_surface_type(surface, "EvenAspheric")
        else:
            _change_surface_type(surface, "Standard")

        surface.Radius = row["radius"]
        surface.Thickness = row["thickness"]
        surface.Material = _model_glass_string(row["n"], row["v"])
        surface.Conic = row["conic"]

        if surface_number in ASPHERE_COEFFICIENTS:
            _set_even_asphere_coefficients(surface, ASPHERE_COEFFICIENTS[surface_number])

    lde.GetSurfaceAt(STOP_SURFACE).IsStop = True

    image = lde.GetSurfaceAt(IMAGE_SURFACE)
    _change_surface_type(image, "Standard")
    image.Comment = "IMA"
    image.Radius = math.inf
    image.Thickness = 0.0
    image.Material = ""
    image.Conic = 0.0


def _finite_thickness_total() -> float:
    return sum(float(row["thickness"]) for row in SURFACES if math.isfinite(float(row["thickness"])))


def _safe_float(value: Any) -> float | None:
    try:
        return float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None


def _last_air_thickness_before_image(oss: Any) -> float | None:
    try:
        return _safe_float(oss.LDE.GetSurfaceAt(IMAGE_SURFACE - 1).Thickness)
    except Exception:
        return None


def _image_semi_diameter(oss: Any) -> float | None:
    try:
        return _safe_float(oss.LDE.GetSurfaceAt(IMAGE_SURFACE).SemiDiameter)
    except Exception:
        return None


def _summary(oss: Any) -> dict[str, Any]:
    prescription_ttl = _finite_thickness_total()
    summary: dict[str, Any] = {
        "efl": None,
        "f_number": APERTURE_F_NUMBER,
        "ttl": prescription_ttl,
        "system_total_track_raw": None,
        "bfl": _last_air_thickness_before_image(oss),
        "image_semi_diameter": _image_semi_diameter(oss),
    }

    try:
        from export_system_summary import _direct_optical_summary

        direct = _direct_optical_summary(oss)
        for key in ("efl", "f_number", "bfl"):
            if direct.get(key) is not None:
                summary[key] = direct[key]
        summary["system_total_track_raw"] = direct.get("ttl")
    except Exception:
        pass

    return summary


def _connect(mode: str = "extension") -> Any:
    print(f"Connecting to OpticStudio via ZOSPy {mode} mode...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect(mode)
        _LIVE_ZOS_CONNECTIONS.append(zos)
        return oss
    except Exception as exc:
        print(f"[ERROR] Failed to connect to OpticStudio through ZOSPy {mode} mode.", flush=True)
        if mode == "extension":
            print(
                "[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.",
                flush=True,
            )
        else:
            print(
                "[ERROR] Make sure OpticStudio can start locally and the license permits ZOS-API standalone mode.",
                flush=True,
            )
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc


def _new_blank_sequential_system(connection_mode: str) -> Any:
    last_error: Exception | None = None

    for attempt in (1, 2):
        oss = _connect(connection_mode)
        try:
            print(
                f"Creating new sequential lens in OpticStudio... attempt {attempt}/2",
                flush=True,
            )
            oss.new(saveifneeded=False)
            oss.make_sequential()
            return oss
        except Exception as exc:
            last_error = exc
            print(
                "[WARNING] OpticStudio failed while creating a new lens session: "
                f"{type(exc).__name__}: {exc!r}",
                flush=True,
            )
            if attempt == 1:
                print(
                    f"[WARNING] Retrying with a fresh ZOSPy {connection_mode} connection.",
                    flush=True,
                )

    print("[ERROR] Could not create a new Sequential Lens through the active ZOS-API session.", flush=True)
    if connection_mode == "extension":
        print(
            "[ERROR] In OpticStudio, reopen Programming > Interactive Extension, keep that dialog open, "
            "then rerun this script.",
            flush=True,
        )
    else:
        print(
            "[ERROR] Standalone connection was created, but New() failed. "
            "Use --connection standalone --modify-existing again after this script update; "
            "that path now skips New().",
            flush=True,
        )
    if last_error is not None:
        print(f"[ERROR] Last error: {type(last_error).__name__}: {last_error!r}", flush=True)
    raise SystemExit(1)


def create_seed(output_path: Path, *, use_current: bool = False, modify_existing: bool = False) -> None:
    create_seed_with_connection(output_path, use_current=use_current, modify_existing=modify_existing)


def create_seed_with_connection(
    output_path: Path,
    *,
    use_current: bool = False,
    modify_existing: bool = False,
    connection_mode: str = "extension",
) -> None:
    output_path = _validate_output_path(output_path, modify_existing=modify_existing)

    print("Creating new sequential lens from CN117471661B Embodiment 2 prescription...", flush=True)
    if modify_existing and not use_current and connection_mode == "standalone":
        print(
            "[WARNING] --modify-existing with --connection standalone will not load the old file. "
            "It will use the standalone PrimarySystem, write the prescription, "
            "and Save As over the requested existing path.",
            flush=True,
        )
        oss = _connect(connection_mode)
        print("Standalone primary system acquired; skipping optional mode/path reads.", flush=True)
    elif modify_existing and not use_current:
        if _same_windows_path(output_path, PROTECTED_OLD_SEED.resolve()):
            print(
                "[WARNING] You explicitly enabled --modify-existing for the old protected seed path. "
                "The script will overwrite that existing file with the CN117471661B Embodiment 2 prescription.",
                flush=True,
            )
        else:
            print(
                "[WARNING] --modify-existing is enabled. The script will overwrite this existing lens file: "
                f"{output_path}",
                flush=True,
            )
        oss = _connect(connection_mode)
        try:
            oss.load(str(output_path), saveifneeded=False)
        except Exception as exc:
            print(f"[ERROR] Failed to load existing lens file: {output_path}", flush=True)
            print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
            raise SystemExit(1) from exc
    elif use_current:
        print(
            "[WARNING] --use-current is enabled. The script will write the prescription into "
            "the currently active OpticStudio system and then Save As the --output path.",
            flush=True,
        )
        print(
            "[WARNING] Use this only after you manually create/open a blank Sequential Lens in OpticStudio.",
            flush=True,
        )
        if connection_mode != "extension":
            print("[ERROR] --use-current only works with --connection extension.", flush=True)
            raise SystemExit(1)
        oss = _connect(connection_mode)
        print(
            "Current OpticStudio system acquired; skipping optional SystemFile/Mode reads.",
            flush=True,
        )
    else:
        oss = _new_blank_sequential_system(connection_mode)

    print("Writing LDE prescription first...", flush=True)
    _configure_lens_data(oss)

    system_data_failures: list[str] = []
    for label, func in (
        ("aperture", _configure_aperture),
        ("fields", _configure_fields),
        ("wavelengths", _configure_wavelengths),
    ):
        try:
            print(f"Configuring SystemData {label}...", flush=True)
            func(oss)
        except Exception as exc:
            message = f"SystemData {label} failed: {type(exc).__name__}: {exc!r}"
            system_data_failures.append(message)
            print(f"[WARNING] {message}", flush=True)

    try:
        oss.update_status()
    except Exception as exc:
        print(f"[WARNING] update_status failed: {type(exc).__name__}: {exc!r}", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if modify_existing and use_current:
        try:
            oss.save()
        except Exception:
            oss.save_as(str(output_path))
    elif modify_existing and not use_current and connection_mode == "standalone":
        oss.save_as(str(output_path))
    elif modify_existing and not use_current:
        try:
            oss.save()
        except Exception:
            oss.save_as(str(output_path))
    else:
        oss.save_as(str(output_path))

    try:
        summary = _summary(oss)
    except Exception as exc:
        print(f"[WARNING] Summary read failed: {type(exc).__name__}: {exc!r}", flush=True)
        summary = {
            "efl": None,
            "f_number": APERTURE_F_NUMBER if not system_data_failures else None,
            "ttl": _finite_thickness_total(),
            "system_total_track_raw": None,
            "bfl": None,
            "image_semi_diameter": None,
        }
    print("\nCN117471661B Embodiment 2 Seed Summary", flush=True)
    print(f"Reference EFL / f: {REFERENCE['efl_mm']} mm", flush=True)
    print(f"Reference F/#: {REFERENCE['f_number']}", flush=True)
    print(f"Reference TTL: {REFERENCE['ttl_mm']} mm", flush=True)
    print(f"Reference Ymax / ImgH: {REFERENCE['image_height_mm']} mm", flush=True)
    print(f"EFL: {summary['efl']}", flush=True)
    print(f"F/#: {summary['f_number']}", flush=True)
    print(f"TTL S1-to-image prescription sum: {summary['ttl']}", flush=True)
    if summary.get("system_total_track_raw") is not None:
        print(
            f"SystemData total track raw: {summary['system_total_track_raw']} "
            "(may include OBJ distance)",
            flush=True,
        )
    print(f"BFL: {summary['bfl']}", flush=True)
    print(f"image semi-diameter: {summary['image_semi_diameter']}", flush=True)
    try:
        number_of_surfaces = oss.LDE.NumberOfSurfaces
    except Exception:
        number_of_surfaces = None
    print(f"number of surfaces: {number_of_surfaces}", flush=True)
    print(f"output path: {output_path}", flush=True)
    if system_data_failures:
        print("\n[WARNING] LDE prescription was written, but one or more SystemData settings failed.", flush=True)
        print("[WARNING] Manually verify/set F/#, fields, and wavelengths in OpticStudio.", flush=True)
        for failure in system_data_failures:
            print(f"[WARNING] {failure}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a Zemax Sequential Lens seed for CN117471661B Embodiment 2 "
            "using Model Glass n,Vd prescription data. No optimization is run."
        )
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output .zos/.zmx path. Must not already exist and must not be the protected old seed path.",
    )
    parser.add_argument(
        "--use-current",
        action="store_true",
        help=(
            "Do not call OpticStudio New(). Instead, write the prescription into the current active system. "
            "Use only after manually creating/opening a blank Sequential Lens."
        ),
    )
    parser.add_argument(
        "--modify-existing",
        action="store_true",
        help=(
            "Allow --output to point to an existing lens file. The script loads that file, "
            "writes the CN117471661B Embodiment 2 prescription into it, and saves it in place. "
            "Use only when you intentionally want to overwrite the existing file."
        ),
    )
    parser.add_argument(
        "--connection",
        choices=("extension", "standalone"),
        default="extension",
        help=(
            "ZOS-API connection mode. Use standalone to load and overwrite an existing file "
            "without relying on Programming > Interactive Extension."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    create_seed_with_connection(
        args.output,
        use_current=args.use_current,
        modify_existing=args.modify_existing,
        connection_mode=args.connection,
    )
