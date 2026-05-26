from __future__ import annotations

from pathlib import Path


RUN_FILE_SUFFIXES = {
    "run_metadata": "run_metadata.json",
    "surfaces": "surfaces.csv",
    "system_data_raw": "system_data_raw.txt",
    "system_summary": "system_summary.json",
    "mtf_fft": "mtf_fft.csv",
    "manufacturing_check": "manufacturing_check.json",
    "summary_for_chatgpt": "summary_for_chatgpt.txt",
    "warnings": "warnings.log",
    "analysis_debug": "analysis_debug.json",
}


def run_file(run_dir: Path, run_id: str, key: str) -> Path:
    return run_dir / f"{run_id}_{RUN_FILE_SUFFIXES[key]}"


def legacy_file(run_dir: Path, key: str) -> Path:
    return run_dir / RUN_FILE_SUFFIXES[key]


def find_run_file(run_dir: Path, key: str) -> Path:
    suffix = RUN_FILE_SUFFIXES[key]
    matches = sorted(run_dir.glob(f"*_{suffix}"))
    if matches:
        return matches[-1]
    return legacy_file(run_dir, key)


def run_id_from_file(path: Path, key: str) -> str | None:
    suffix = f"_{RUN_FILE_SUFFIXES[key]}"
    name = path.name
    if not name.endswith(suffix):
        return None
    return name[: -len(suffix)]
