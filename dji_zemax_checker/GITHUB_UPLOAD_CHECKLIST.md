# GitHub Upload Checklist

Use this checklist before pushing the repository.

## 1. Keep Only Source Files In Git

Do not upload local lens files, scan copies, generated reports, logs, or competition attachment exports.

Ignored by default:

- `results/`
- `scan_runs/`
- `logs/`
- `reports/`
- `stage_runs/`
- `*.zos`, `*.zmx`, `*.ZOS`, `*.ZMX`, `*.ZDA`
- `allowed_materials*.csv`

## 2. Remove Previously Tracked Generated Files

This removes files from Git tracking only. It does not delete local files.

```powershell
git rm --cached -r --ignore-unmatch results scan_runs logs reports stage_runs
git rm --cached --ignore-unmatch allowed_materials_from_DJI_library.csv
```

## 3. Verify Status

```powershell
git status --short
git ls-files results scan_runs logs reports stage_runs allowed_materials_from_DJI_library.csv
```

The second command should print nothing except intentionally tracked placeholders such as `results/.gitkeep`.

## 4. Syntax Check

```powershell
.\.venv\Scripts\python.exe -m compileall src
```

## 5. Suggested Commit

```powershell
git add .gitignore README.md GITHUB_UPLOAD_CHECKLIST.md requirements.txt src tools
git status --short
git commit -m "Prepare Zemax automation project for GitHub"
```

Review `git status --short` before committing. Do not commit generated Zemax or result files.
