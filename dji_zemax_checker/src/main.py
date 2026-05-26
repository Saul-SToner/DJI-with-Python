from __future__ import annotations

from datetime import datetime
from pathlib import Path

import zospy as zp

from console_summary import print_run_console_summary
from export_surfaces import export_surfaces
from export_surfaces import FIELDNAMES as SURFACE_FIELDNAMES
import export_surfaces as export_surfaces_module
from export_system_summary import export_system_summary
from export_system_summary import _raw_lens_file, _read_raw_text
from export_system_summary import _same_windows_path
from export_mtf import export_mtf
from export_chatgpt_summary import export_chatgpt_summary
from manufacturing_check import export_manufacturing_check
from run_metadata import build_run_metadata, export_run_metadata, load_run_metadata
from run_files import run_file
from summarize_results import summarize_results

import csv
import json


def _unique_run_dir(project_root: Path) -> tuple[str, Path]:
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = project_root / "results"
    run_id = base
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = results_dir / run_id
        suffix += 1
    return run_id, run_dir


def _check_run_consistency(run_dir: Path, run_id: str) -> list[str]:
    errors: list[str] = []
    metadata_path = run_file(run_dir, run_id, "run_metadata")
    system_summary_path = run_file(run_dir, run_id, "system_summary")
    surfaces_path = run_file(run_dir, run_id, "surfaces")
    mtf_path = run_file(run_dir, run_id, "mtf_fft")
    manufacturing_path = run_file(run_dir, run_id, "manufacturing_check")

    for key in (
        "run_metadata",
        "surfaces",
        "system_data_raw",
        "system_summary",
        "mtf_fft",
        "manufacturing_check",
        "summary_for_chatgpt",
    ):
        path = run_file(run_dir, run_id, key)
        if not path.exists():
            errors.append(f"ERROR: expected output file is missing: {path.name}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"ERROR: failed to read {metadata_path.name}: {repr(exc)}"]

    try:
        system_summary = json.loads(system_summary_path.read_text(encoding="utf-8"))
        summary_run_id = (system_summary.get("run_metadata") or {}).get("run_id")
        if summary_run_id != metadata.get("run_id"):
            errors.append(
                "ERROR: run_id mismatch between run_metadata.json "
                f"({metadata.get('run_id')}) and system_summary.json ({summary_run_id})."
            )
    except Exception as exc:
        errors.append(f"ERROR: failed to read {system_summary_path.name}: {repr(exc)}")

    try:
        manufacturing = json.loads(manufacturing_path.read_text(encoding="utf-8"))
        manufacturing_run_id = manufacturing.get("run_id") or (manufacturing.get("run_metadata") or {}).get("run_id")
        if manufacturing_run_id != metadata.get("run_id"):
            errors.append(
                "ERROR: run_id mismatch between run_metadata.json "
                f"({metadata.get('run_id')}) and manufacturing_check.json ({manufacturing_run_id})."
            )
    except Exception as exc:
        errors.append(f"ERROR: failed to read {manufacturing_path.name}: {repr(exc)}")

    try:
        with surfaces_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            has_before_image = any(str(row.get("is_before_image")).lower() == "true" for row in rows)
            bad_run_ids = sorted({row.get("run_id") for row in rows if row.get("run_id") != metadata.get("run_id")})
        if not has_before_image:
            errors.append("ERROR: surfaces.csv does not contain is_before_image=True.")
        if bad_run_ids:
            errors.append(f"ERROR: surfaces.csv contains mismatched run_id values: {bad_run_ids}.")
    except Exception as exc:
        errors.append(f"ERROR: failed to check {surfaces_path.name}: {repr(exc)}")

    try:
        with mtf_path.open(newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        missing = {"run_id", "current_lens_file"}.difference(header)
        if missing:
            errors.append(f"ERROR: mtf_fft.csv missing required columns: {', '.join(sorted(missing))}")
    except Exception as exc:
        errors.append(f"ERROR: failed to check {mtf_path.name}: {repr(exc)}")

    return errors


def _check_surface_header(path: Path) -> list[str]:
    required = {"run_id", "current_lens_file", "is_stop", "is_image", "is_before_image"}
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
    except Exception as exc:
        return [f"ERROR: failed to read surfaces.csv header: {repr(exc)}"]

    missing = sorted(required.difference(header))
    if missing:
        return [f"ERROR: surfaces.csv missing required columns: {', '.join(missing)}"]
    return []


def _raw_header_status(run_dir: Path, run_id: str) -> tuple[str | None, bool | None, str | None]:
    metadata_path = run_file(run_dir, run_id, "run_metadata")
    raw_path = run_file(run_dir, run_id, "system_data_raw")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = metadata.get("current_lens_file")
    except Exception as exc:
        return None, None, f"ERROR: failed to read metadata for raw check: {repr(exc)}"

    if not raw_path.exists():
        return None, None, f"ERROR: {raw_path.name} does not exist."

    try:
        raw_text = _read_raw_text(raw_path)
        raw_file = _raw_lens_file(raw_text)
    except Exception as exc:
        return None, None, f"ERROR: failed to read system_data_raw.txt for raw check: {repr(exc)}"

    if raw_file is None:
        return None, False, "ERROR: system_data_raw.txt has no File/文件 header."

    is_match = _same_windows_path(raw_file, expected)

    error = None if is_match else f"ERROR: raw header file mismatch. raw={raw_file}; metadata={expected}"
    return raw_file, is_match, error


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]

    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
        print("Connected to OpticStudio", flush=True)
    except Exception as exc:
        raise RuntimeError(
            "Failed to connect to OpticStudio. Make sure OpticStudio is open "
            "and Programming > Interactive Extension is active."
        ) from exc

    run_id, run_dir = _unique_run_dir(project_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    export_time = datetime.now().isoformat(timespec="seconds")
    metadata = build_run_metadata(oss, run_id, export_time, output_folder=run_dir)

    print("Run ID:", run_id, flush=True)
    print("Output folder:", run_dir, flush=True)
    print("Lens file:", metadata["current_lens_file"], flush=True)
    print("Lens title:", metadata["lens_title"], flush=True)
    print("Number of surfaces:", metadata["number_of_surfaces"], flush=True)
    print("Stop surface:", metadata["stop_surface"], flush=True)
    print("Image surface:", metadata["image_surface"], flush=True)
    print("Last surface before image:", metadata["last_surface_before_image"], flush=True)
    print("export_surfaces module:", export_surfaces_module.__file__, flush=True)
    print("surface columns:", ", ".join(SURFACE_FIELDNAMES), flush=True)

    warnings_path = run_dir / "warnings.log"
    warnings_path = run_file(run_dir, run_id, "warnings")

    def warn(message: str) -> None:
        print("[WARNING]", message, flush=True)
        with warnings_path.open("a", encoding="utf-8") as f:
            f.write(message + "\n")

    surfaces = []

    try:
        metadata_path = run_file(run_dir, run_id, "run_metadata")
        metadata = export_run_metadata(oss, metadata_path, run_id, export_time, output_folder=run_dir)
        metadata = load_run_metadata(metadata_path)
        print("Exported:", metadata_path, flush=True)
    except Exception as exc:
        warn(f"Failed to export run_metadata.json: {repr(exc)}")

    try:
        surfaces_path = run_file(run_dir, run_id, "surfaces")
        surfaces = export_surfaces(oss, surfaces_path, run_metadata=metadata)
        print("Exported:", surfaces_path, flush=True)
        for error in _check_surface_header(surfaces_path):
            warn(error)
    except Exception as exc:
        warn(f"Failed to export surfaces.csv: {repr(exc)}")

    try:
        system_summary_path = run_file(run_dir, run_id, "system_summary")
        system_summary = export_system_summary(oss, system_summary_path, run_metadata=metadata)
        print("Exported:", system_summary_path, flush=True)
        print("System Data raw valid:", system_summary.get("system_data_raw_valid"), flush=True)
        print("System Data raw lens file:", system_summary.get("system_data_raw_lens_file"), flush=True)
        print("System Data current lens file:", system_summary.get("current_lens_file"), flush=True)
        for warning in system_summary.get("warnings", []):
            if str(warning).startswith("ERROR:"):
                print(warning, flush=True)
    except Exception as exc:
        warn(f"Failed to export system_summary.json: {repr(exc)}")

    try:
        mtf_path = run_file(run_dir, run_id, "mtf_fft")
        if export_mtf(oss, mtf_path, run_metadata=metadata):
            print("Exported:", mtf_path, flush=True)
        else:
            print("[WARNING] Failed to export mtf_fft.csv", flush=True)
    except Exception as exc:
        warn(f"Failed to export mtf_fft.csv: {repr(exc)}")

    try:
        if not surfaces:
            surfaces = export_surfaces(oss, run_file(run_dir, run_id, "surfaces"), run_metadata=metadata)
        manufacturing_path = run_file(run_dir, run_id, "manufacturing_check")
        export_manufacturing_check(surfaces, manufacturing_path, run_metadata=metadata)
        print("Exported:", manufacturing_path, flush=True)
    except Exception as exc:
        warn(f"Failed to export manufacturing_check.json: {repr(exc)}")

    try:
        chatgpt_summary_path = run_file(run_dir, run_id, "summary_for_chatgpt")
        export_chatgpt_summary(run_dir, run_id, chatgpt_summary_path)
        print("Exported:", chatgpt_summary_path, flush=True)
    except Exception as exc:
        warn(f"Failed to export summary_for_chatgpt.txt: {repr(exc)}")

    try:
        summary_paths = summarize_results(project_root)
        for path in summary_paths.values():
            print("Updated:", path, flush=True)
    except Exception as exc:
        warn(f"Failed to update summary outputs: {repr(exc)}")

    for error in _check_run_consistency(run_dir, run_id):
        warn(error)

    raw_file, raw_matches_metadata, raw_error = _raw_header_status(run_dir, run_id)
    print("System Data raw header file:", raw_file, flush=True)
    print("System Data metadata/raw match:", raw_matches_metadata, flush=True)
    if raw_error:
        warn(raw_error)

    print("Done.", flush=True)
    print_run_console_summary(run_dir, run_id)
    print("Image surface:", metadata.get("image_surface"), flush=True)
    print("Last surface before image:", metadata.get("last_surface_before_image"), flush=True)
    print("Result directory:", run_dir, flush=True)


if __name__ == "__main__":
    main()
