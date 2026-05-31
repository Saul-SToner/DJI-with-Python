param(
    [ValidateSet("radius", "conic", "radius_conic_grid", "thickness")]
    [string]$Mode = "radius_conic_grid",

    [string]$BaseLens,
    [int]$Surface = -1,
    [string[]]$Values,
    [string[]]$Radii,
    [string[]]$Conics,
    [switch]$QuickFocus,
    [string]$Label = "scan",
    [string]$SortBy = "score",
    [int]$TopN = 10,
    [string]$DecisionNote,
    [switch]$NoRun,
    [string]$GridSummaryCsv,
    [string]$GridSummaryTxt
)

$ErrorActionPreference = "Stop"

function Split-ScanValues {
    param([string[]]$Text)
    if ($null -eq $Text -or $Text.Count -eq 0) {
        return @()
    }
    return @($Text | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Resolve-LatestGridSummaryCsv {
    $dir = Join-Path (Get-Location) "results\grid_summaries"
    if (-not (Test-Path $dir)) {
        return $null
    }
    $latest = Get-ChildItem -Path $dir -Filter "*_grid_summary.csv" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        return $latest.FullName
    }
    return $null
}

function Matching-GridSummaryTxt {
    param([string]$CsvPath)
    if ([string]::IsNullOrWhiteSpace($CsvPath)) {
        return $null
    }
    $txt = $CsvPath -replace "_grid_summary\.csv$", "_grid_summary_for_chatgpt.txt"
    if (Test-Path $txt) {
        return $txt
    }
    return $null
}

function Read-SummaryValues {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path $Path)) {
        return $values
    }
    foreach ($line in Get-Content -Path $Path) {
        if ($line.StartsWith("[") -or -not $line.Contains(":")) {
            continue
        }
        $parts = $line.Split(":", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Get-ScanFloat {
    param($Value)
    $number = 0.0
    if ($null -eq $Value) {
        return 0.0
    }
    if ([double]::TryParse([string]$Value, [ref]$number)) {
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) {
            return 0.0
        }
        return $number
    }
    return 0.0
}

function New-SingleScanGridSummary {
    param(
        [string[]]$RunDirs,
        [string]$Label,
        [string]$Timestamp
    )
    if ($RunDirs.Count -eq 0) {
        return $null
    }

    $summaryDir = Join-Path (Get-Location) "results\grid_summaries"
    New-Item -ItemType Directory -Force -Path $summaryDir | Out-Null
    $safe = if ([string]::IsNullOrWhiteSpace($Label)) { "single_scan" } else { $Label -replace "[^A-Za-z0-9_+-]+", "_" }
    $csvPath = Join-Path $summaryDir "$Timestamp`_$safe`_grid_summary.csv"
    $txtPath = Join-Path $summaryDir "$Timestamp`_$safe`_grid_summary_for_chatgpt.txt"

    $rows = @()
    foreach ($dir in $RunDirs) {
        $summary = Get-ChildItem -Path $dir -Filter "*_summary_for_chatgpt.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $summary) {
            continue
        }
        $v = Read-SummaryValues $summary.FullName
        $score =
            4.0 * (Get-ScanFloat $v["MTF40_min"]) +
            2.0 * (Get-ScanFloat $v["MTF50_min"]) +
            (Get-ScanFloat $v["MTF40_mean"]) +
            (Get-ScanFloat $v["MTF50_mean"]) +
            0.5 * (Get-ScanFloat $v["28T40"]) +
            0.5 * (Get-ScanFloat $v["28T50"])
        $rows += [pscustomobject][ordered]@{
            run_id = $v["run_id"]
            status = $v["status"]
            scanned_surface = $v["scanned_surface"]
            scanned_surface_comment = $v["scanned_surface_comment"]
            scanned_radius = $v["scanned_radius"]
            scanned_conic = $v["scanned_conic"]
            output_folder = $dir
            scan_lens = $v["scan_lens"]
            "F/#" = $v["current_f_number"]
            EFL = $v["efl"]
            BFL = $v["bfl"]
            TTL = $v["ttl"]
            "Working F/#" = $v["working_f_number"]
            S13R = $v["S13R"]
            S13_conic = $v["S13_conic"]
            S15T = $v["S15T"]
            L5_edge = $v["L5_edge"]
            MTF40_min = $v["MTF40_min"]
            MTF40_mean = $v["MTF40_mean"]
            MTF50_min = $v["MTF50_min"]
            MTF50_mean = $v["MTF50_mean"]
            "25T20" = $v["25T20"]
            "25T25" = $v["25T25"]
            "25T30" = $v["25T30"]
            "25T35" = $v["25T35"]
            "25T40" = $v["25T40"]
            "25T50" = $v["25T50"]
            "25S50" = $v["25S50"]
            "27p5T40" = $v["27p5T40"]
            "28T40" = $v["28T40"]
            "28T50" = $v["28T50"]
            score = $score
            summary_extraction_warning = $v["summary_extraction_warning"]
            failure_reason = $v["failure_reason"]
        }
    }

    if ($rows.Count -eq 0) {
        return $null
    }
    $rows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8
    @(
        "label: $Label",
        "total points: $($rows.Count)",
        "failed points: $(($rows | Where-Object { $_.status -eq 'failed' -or $_.failure_reason }).Count)",
        "source: synthesized from single-variable scan summaries"
    ) | Set-Content -Path $txtPath -Encoding UTF8
    return @{ Csv = $csvPath; Txt = $txtPath }
}

$projectRoot = Get-Location
if (-not (Test-Path (Join-Path $projectRoot "src")) -or -not (Test-Path (Join-Path $projectRoot ".venv\Scripts\python.exe"))) {
    throw "Current directory is not the dji_zemax_checker project root. Please run from C:\ZemaxAuto\dji_zemax_checker."
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "reports") | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$safeLabel = if ([string]::IsNullOrWhiteSpace($Label)) { "scan" } else { $Label -replace "[^A-Za-z0-9_+-]+", "_" }
$logPath = Join-Path $projectRoot "logs\$timestamp`_$safeLabel.log"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$beforeResultDirs = @()
if (Test-Path (Join-Path $projectRoot "results")) {
    $beforeResultDirs = @(Get-ChildItem -Path (Join-Path $projectRoot "results") -Directory | ForEach-Object { $_.FullName })
}

if (-not $NoRun) {
    if ([string]::IsNullOrWhiteSpace($BaseLens)) {
        throw "-BaseLens is required unless -NoRun is used with -GridSummaryCsv or an existing latest grid summary."
    }
    if (-not (Test-Path $BaseLens)) {
        throw "Base lens not found: $BaseLens"
    }
    if ($Surface -lt 0) {
        throw "-Surface is required for scan execution."
    }

    $scanArgs = @("-u")
    if ($Mode -eq "radius_conic_grid") {
        $radiiValues = Split-ScanValues $Radii
        $conicValues = Split-ScanValues $Conics
        if ($radiiValues.Count -eq 0 -or $conicValues.Count -eq 0) {
            throw "-Radii and -Conics are required for radius_conic_grid."
        }
        $scanArgs += @(
            ".\src\scan_radius_conic_grid.py",
            "--base-lens", $BaseLens,
            "--surface", "$Surface",
            "--radii"
        )
        $scanArgs += $radiiValues
        $scanArgs += @("--conics")
        $scanArgs += $conicValues
        if ($QuickFocus) { $scanArgs += "--quick-focus" }
        $scanArgs += @("--label", $Label, "--sort-by", $SortBy)
    } elseif ($Mode -eq "radius") {
        $scanValues = Split-ScanValues $Values
        if ($scanValues.Count -eq 0) {
            throw "-Values is required for radius mode."
        }
        $scanArgs += @(
            ".\src\scan_radius.py",
            "--base-lens", $BaseLens,
            "--surface", "$Surface",
            "--values"
        )
        $scanArgs += $scanValues
        if ($QuickFocus) { $scanArgs += "--quick-focus" }
        $scanArgs += @("--label", $Label)
    } elseif ($Mode -eq "conic") {
        $scanValues = Split-ScanValues $Values
        if ($scanValues.Count -eq 0) {
            throw "-Values is required for conic mode."
        }
        $scanArgs += @(
            ".\src\scan_conic.py",
            "--base-lens", $BaseLens,
            "--surface", "$Surface",
            "--values"
        )
        $scanArgs += $scanValues
        if ($QuickFocus) { $scanArgs += "--quick-focus" }
        $scanArgs += @("--label", $Label)
    } elseif ($Mode -eq "thickness") {
        $scanValues = Split-ScanValues $Values
        if ($scanValues.Count -eq 0) {
            throw "-Values is required for thickness mode."
        }
        $scanArgs += @(
            ".\src\scan_thickness.py",
            "--base-lens", $BaseLens,
            "--surface", "$Surface",
            "--values"
        )
        $scanArgs += $scanValues
        if ($QuickFocus) { $scanArgs += "--quick-focus" }
        $scanArgs += @("--label", $Label)
    }

    Write-Host "Running scan..."
    Write-Host "$python $($scanArgs -join ' ')"
    & $python @scanArgs 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) {
        throw "Scan command failed with exit code $LASTEXITCODE. Log: $logPath"
    }
} else {
    "NoRun mode. Scan command was not executed." | Tee-Object -FilePath $logPath | Out-Null
}

$logText = if (Test-Path $logPath) { Get-Content -Raw -Path $logPath } else { "" }
if ([string]::IsNullOrWhiteSpace($GridSummaryCsv)) {
    $match = [regex]::Match($logText, "grid_summary_csv:\s*(.+)")
    if ($match.Success) {
        $GridSummaryCsv = $match.Groups[1].Value.Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($GridSummaryTxt)) {
    $match = [regex]::Match($logText, "grid_summary_for_chatgpt:\s*(.+)")
    if ($match.Success) {
        $GridSummaryTxt = $match.Groups[1].Value.Trim()
    }
}
if (-not $NoRun -and $Mode -ne "radius_conic_grid" -and [string]::IsNullOrWhiteSpace($GridSummaryCsv)) {
    $afterResultDirs = @()
    if (Test-Path (Join-Path $projectRoot "results")) {
        $afterResultDirs = @(Get-ChildItem -Path (Join-Path $projectRoot "results") -Directory | ForEach-Object { $_.FullName })
    }
    $newResultDirs = @($afterResultDirs | Where-Object { $beforeResultDirs -notcontains $_ })
    $synthesized = New-SingleScanGridSummary -RunDirs $newResultDirs -Label $Label -Timestamp $timestamp
    if ($synthesized) {
        $GridSummaryCsv = $synthesized.Csv
        $GridSummaryTxt = $synthesized.Txt
    }
}
if ([string]::IsNullOrWhiteSpace($GridSummaryCsv)) {
    $GridSummaryCsv = Resolve-LatestGridSummaryCsv
}
if ([string]::IsNullOrWhiteSpace($GridSummaryTxt)) {
    $GridSummaryTxt = Matching-GridSummaryTxt $GridSummaryCsv
}

if ([string]::IsNullOrWhiteSpace($GridSummaryCsv) -or -not (Test-Path $GridSummaryCsv)) {
    throw "Could not locate grid_summary_csv. For radius/conic single-variable scans, provide -GridSummaryCsv or run a grid scan first."
}

$reportArgs = @(
    ".\src\build_scan_report.py",
    "--grid-summary-csv", $GridSummaryCsv,
    "--log", $logPath,
    "--top-n", "$TopN",
    "--sort-by", $SortBy,
    "--out-dir", "reports"
)
if (-not [string]::IsNullOrWhiteSpace($GridSummaryTxt) -and (Test-Path $GridSummaryTxt)) {
    $reportArgs += @("--grid-summary-txt", $GridSummaryTxt)
}
if (-not [string]::IsNullOrWhiteSpace($DecisionNote)) {
    $reportArgs += @("--decision-note", $DecisionNote)
}

$reportOutput = & $python @reportArgs
$reportOutput | ForEach-Object { Write-Host $_ }
$markdownReport = ($reportOutput | Select-String -Pattern "^markdown_report:\s*(.+)$").Matches.Groups[1].Value
$txtReport = ($reportOutput | Select-String -Pattern "^txt_report:\s*(.+)$").Matches.Groups[1].Value

Write-Host "log path: $logPath"
Write-Host "markdown report path: $markdownReport"
Write-Host "txt report path: $txtReport"
Write-Host "csv summary path: $GridSummaryCsv"
if (-not [string]::IsNullOrWhiteSpace($GridSummaryTxt)) {
    Write-Host "txt summary path: $GridSummaryTxt"
}
