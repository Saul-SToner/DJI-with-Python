# DJI Zemax Checker

This project uses Python, ZOSPy, and the OpticStudio ZOS-API to inspect the lens file currently open in Ansys Zemax OpticStudio.

The first stage only connects to OpticStudio in extension mode and exports basic Lens Data Editor surface data plus lightweight summary checks to `results/YYYYMMDD_HHMMSS/`.

## Requirements

- Windows 10 or Windows 11
- Ansys Zemax OpticStudio installed and licensed
- Python 3.10 to 3.13
- PowerShell

Python 3.11 or 3.12 is a conservative choice. Python 3.13 is also supported by current ZOSPy releases.

## Create The Project Environment

Open PowerShell and run:

```powershell
cd C:\ZemaxAuto\dji_zemax_checker
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks venv activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

## Start OpticStudio Interactive Extension

1. Open Ansys Zemax OpticStudio.
2. Open the lens file you want to inspect.
3. In OpticStudio, choose `Programming > Interactive Extension`.
4. Keep the Interactive Extension window open while the Python script runs.

The scripts use ZOSPy extension mode, which connects to an already running OpticStudio instance.

## Test The Connection

With the venv active:

```powershell
python .\src\connect_test.py
```

Expected result:

```text
Initializing ZOSPy...
Connecting to OpticStudio in extension mode...
Connected.
Number of surfaces: ...
```

## Export Surface Data

With OpticStudio open and Interactive Extension active:

```powershell
python .\src\main.py
```

The output is written to:

```text
results/YYYYMMDD_HHMMSS/
  surfaces.csv
  system_summary.json
  manufacturing_check.json
```

The CSV columns are:

- `surface_index`
- `comment`
- `radius`
- `thickness`
- `material`
- `semi_diameter`
- `conic`

If an individual field cannot be read from ZOS-API, the script writes an empty value for that field and continues.

`system_summary.json` contains system metadata, aperture data, fields, wavelengths, and calculated optical summary fields when the ZOSPy System Data report can be parsed.

`manufacturing_check.json` currently checks L5 by comment label and reports center thickness, approximate edge thickness, minimum absolute radius, and edge thinning risk.

## Scope

This first stage does not run the optimizer, does not modify the lens file, and does not export MTF or manufacturing checks.

## Codex CLI

Install Node.js for Windows first, then open a new PowerShell window and run:

```powershell
npm i -g @openai/codex
cd C:\ZemaxAuto\dji_zemax_checker
codex
```

On this machine, `node` and `codex` currently resolve to the Codex desktop app package under `C:\Program Files\WindowsApps`, and PowerShell cannot execute those binaries directly. Install the standalone Node.js LTS build so `npm` is available on PATH before installing Codex CLI.
