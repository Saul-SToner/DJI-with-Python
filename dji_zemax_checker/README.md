# DJI Zemax Checker

Python utilities for inspecting and batch-checking Ansys Zemax OpticStudio sequential lens files through ZOSPy and the ZOS-API.

The project is designed for a local Windows OpticStudio workflow. It exports repeatable CSV/JSON/TXT summaries, runs conservative parameter scans, and provides mechanical/geometry diagnostics for ultra-wide-angle lens development.

## Requirements

- Windows 10 or Windows 11
- Ansys Zemax OpticStudio installed and licensed for ZOS-API
- Python 3.10 to 3.13
- PowerShell

Python 3.11 or 3.12 is recommended for a conservative local setup.

## Setup

```powershell
cd C:\ZemaxAuto\dji_zemax_checker
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks virtual environment activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

## OpticStudio Connection

Most scripts use ZOSPy extension mode.

1. Open OpticStudio.
2. Open the lens file you want to inspect.
3. Start `Programming > Interactive Extension`.
4. Keep that dialog open while Python runs.

Test the connection:

```powershell
python .\src\connect_test.py
```

If connection fails, confirm OpticStudio is open, the lens is loaded, Interactive Extension is active, and the Python process is running in native Windows PowerShell rather than WSL.

## Common Commands

Export the current lens summary:

```powershell
python -u .\src\main.py
```

Close analysis windows if OpticStudio becomes cluttered:

```powershell
python -u .\src\close_all_analysis_windows.py
```

Run a read-only overlap diagnostic:

```powershell
python -u .\src\diagnose_lens_overlap.py --lens "C:\Users\L2791\OneDrive\Desktop\3.2.ZOS"
```

Run a dry-run repair helper without saving:

```powershell
python -u .\src\apply_s4_s5_adaptive_gap_fix.py --lens "C:\Users\L2791\OneDrive\Desktop\3.2.ZOS"
```

Apply scripts save only when explicitly passed `--apply`.

## Project Layout

```text
src/
  export_*.py                 Export helpers for surfaces, MTF, system data, summaries
  scan_*.py                   Conservative parameter scan scripts
  diagnose_*.py               Read-only diagnostic scripts
  apply_*.py                  Limited repair scripts, dry-run by default
  zosapi_cleanup.py           Analysis-window cleanup helper

tools/
  run_scan_and_report.ps1     PowerShell scan/report wrapper

results/
scan_runs/
logs/
reports/
stage_runs/
  Generated local outputs; ignored by Git
```

## Safety Notes

- Diagnostic scripts are intended to be read-only.
- Repair scripts default to dry-run and require `--apply` before saving.
- Scan scripts should copy or generate scan files under `scan_runs/` and write outputs under `results/`.
- The optimizer and Hammer should not be called unless a script explicitly documents that behavior.
- Generated Zemax files, result folders, logs, reports, and local material-library exports are ignored by Git.

## GitHub Upload Notes

Before publishing, verify that no private lens files, competition attachment files, generated reports, or scan results are staged:

```powershell
git status --short
git ls-files results scan_runs logs reports stage_runs
```

If generated files were previously tracked, remove them from the Git index without deleting local files:

```powershell
git rm --cached -r --ignore-unmatch results scan_runs logs reports stage_runs
git rm --cached --ignore-unmatch allowed_materials_from_DJI_library.csv
```

Then run a syntax check:

```powershell
python -m compileall src
```
