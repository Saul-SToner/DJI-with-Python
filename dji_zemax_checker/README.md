# Zemax Wide-Angle Lens Structure Search Workflow

This repository serves as a **personal learning / research workflow archive** documenting automated search, triage, and validation scripts for sequential ultra-wide-angle lens configurations.

## Project Positioning & Focus

The core focus of this project is **not** final optical optimization or aberration control. Instead, it defines a pipeline for:
1. **Candidate Structure Auto-Generation**: Reconstructing sequential designs headlessly from patent parameters.
2. **Ray-Tracing & Vignetting Verification**: Auditing high-field transmission limits under $F/2.5$ or stage-dependent apertures using Real Ray Aiming.
3. **Failure Surface Localization**: Identifying which lens surface triggers ray trace aborts or violates mechanical constraints.
4. **Stage-by-Stage Freezing**: Archiving triage runs and categorizing layouts.
5. **Machine Learning Screening**: Exporting structured geometric and performance metrics to compile training data for offline ML screening filters.

---

## Requirements & Setup

### OpticStudio Dependency
> [!IMPORTANT]
> The Python connection requires a local licensed installation of Ansys Zemax OpticStudio on Windows. The underlying ZOS-API DLLs cannot be installed via pip.

### Python Environment Setup
```powershell
cd C:\ZemaxAuto\dji_zemax_checker
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## Project Directory Structure

```text
docs/
  project_overview.md
  design_constraints.md
  experiment_log.md
  data_schema.md
  future_ml_screening_plan.md

reports/
  stage_summary.md
  best_candidate_freeze.md
  root_cause_report.md
  failed_routes.md

data/
  raw/
  processed/
    candidate_table.csv
    trace_result_table.csv
    failure_surface_table.csv
    experiment_log.csv
  manifests/
    zos_file_manifest.csv

src/
  ZOS-API connection, diagnostics, and metric extraction utilities

runner/
  high-level test runners and triage scripts

notebooks/
  exploratory analysis notebooks
```

---

## Repository Constraints & Safety

- **No Raw Design Files in Git**: All `.ZOS`, `.ZMX`, `.ZDA`, and session temporary files are strictly ignored. Only manifests mapping path/SHA256 are checked in.
- **Safety Gate**: Modifying commands default to dry-run behavior to prevent accidental overwrites of baseline design models.
- **No Fictional Data**: All unverified metrics are labeled `UNKNOWN` or `TODO`. No final optical optimization claims are made.
