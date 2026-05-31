from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from pandas import DataFrame

from diagnose_mtf_field import _run_fft_mtf_dataframe
from export_chatgpt_summary import _interpolate, _is_real_mtf_curve, _read_mtf
from export_surfaces import safe_get
from scan_radius import _safe_label
from zosapi_cleanup import close_all_analysis_windows


REQUESTED_FIELDS = (0.0, 21.0, 35.0, 49.0)
REQUESTED_FREQS = (20.0, 30.0, 40.0, 50.0)
DEFAULT_IMAGE_DISTANCES = (0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.3, 2.5, 3.0)
FIELD_MATCH_TOLERANCE_DEG = 0.25


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.6g}"
    return "null" if value is None else str(value)


def _field_key(field: float) -> str:
    return f"{field:g}".replace(".", "p")


def _distance_label(value: float) -> str:
    text = f"{value:g}".replace("-", "m").replace("+", "p").replace(".", "p")
    return text if text else "0"


def _unique_run_dir(project_root: Path, label: str) -> tuple[str, Path]:
    root = project_root / "results" / "focus_scan_after_geometry_repair"
    base = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    run_id = base
    run_dir = root / run_id
    suffix = 1
    while run_dir.exists():
        run_id = f"{base}_{suffix:02d}"
        run_dir = root / run_id
        suffix += 1
    return run_id, run_dir


def _finite_thickness(value: Any) -> float | None:
    number = _to_float(value)
    if number is None or not math.isfinite(number):
        return None
    return number


def _sum_ttl_from_lde(oss: Any) -> float | None:
    """Prescription TTL: sum finite thicknesses from S1 through image-1, excluding OBJ."""
    lde = safe_get(oss, "LDE")
    count = safe_get(lde, "NumberOfSurfaces")
    try:
        number_of_surfaces = int(count)
    except (TypeError, ValueError):
        return None

    total = 0.0
    found = False
    for surface_number in range(1, number_of_surfaces - 1):
        try:
            thickness = _finite_thickness(lde.GetSurfaceAt(surface_number).Thickness)
        except Exception:
            thickness = None
        if thickness is None:
            continue
        total += thickness
        found = True
    return total if found else None


def _system_summary(oss: Any) -> dict[str, Any]:
    lde = safe_get(oss, "LDE")
    count = safe_get(lde, "NumberOfSurfaces")
    try:
        number_of_surfaces = int(count)
    except (TypeError, ValueError):
        number_of_surfaces = None

    image_surface = number_of_surfaces - 1 if number_of_surfaces is not None else None
    image_distance = None
    if image_surface is not None and image_surface > 0:
        try:
            image_distance = _to_float(lde.GetSurfaceAt(image_surface - 1).Thickness)
        except Exception:
            image_distance = None

    aperture = safe_get(safe_get(oss, "SystemData"), "Aperture")
    f_number = _to_float(safe_get(aperture, "ApertureValue"))

    efl = None
    for obj in (safe_get(oss, "SystemData"), lde, oss):
        if obj is None:
            continue
        for name in ("EffectiveFocalLength", "EffectiveFocalLengthAir", "EFL", "ParaxialEffectiveFocalLength"):
            efl = _to_float(safe_get(obj, name))
            if efl is not None:
                break
        if efl is not None:
            break

    return {
        "number_of_surfaces": number_of_surfaces,
        "image_surface": image_surface,
        "last_surface_before_image": image_surface - 1 if image_surface is not None and image_surface > 0 else None,
        "image_distance": image_distance,
        "ttl": _sum_ttl_from_lde(oss),
        "bfl": image_distance,
        "efl": efl,
        "f_number": f_number,
    }


def _available_fields(oss: Any) -> list[float]:
    fields = safe_get(safe_get(oss, "SystemData"), "Fields")
    count = safe_get(fields, "NumberOfFields", 0) or 0
    values: list[float] = []
    for index in range(1, int(count) + 1):
        try:
            field = fields.GetField(index)
            value = _to_float(safe_get(field, "Y"))
            if value is not None:
                values.append(value)
        except Exception:
            continue
    return values


def _nearest_series(series: list[dict[str, Any]], field: float, orientation: str) -> tuple[dict[str, Any] | None, float | None]:
    candidates = [
        item
        for item in series
        if _is_real_mtf_curve(item)
        and item.get("orientation") == orientation
        and _to_float(item.get("field")) is not None
    ]
    if not candidates:
        return None, None
    nearest = min(candidates, key=lambda item: abs(float(item["field"]) - field))
    nearest_field = _to_float(nearest.get("field"))
    if nearest_field is None or abs(nearest_field - field) > FIELD_MATCH_TOLERANCE_DEG:
        return None, nearest_field
    return nearest, nearest_field


def _curve_values_for_field(
    frequencies: list[float],
    series: list[dict[str, Any]],
    field: float,
) -> tuple[dict[str, float | None], list[str]]:
    values: dict[str, float | None] = {}
    warnings: list[str] = []
    for orientation in ("T", "S"):
        item, nearest_field = _nearest_series(series, field, orientation)
        if item is None:
            warnings.append(
                f"missing {field:g}{orientation} curve"
                + (f" nearest={nearest_field:g}" if nearest_field is not None else "")
            )
            curve_values = []
        else:
            curve_values = []
            for freq in REQUESTED_FREQS:
                value = _interpolate(frequencies, item["values"], freq)
                values[f"{_field_key(field)}_{orientation}_{int(freq)}"] = value
                if value is not None:
                    curve_values.append(value)

        values[f"{_field_key(field)}_{orientation}_min_20_50"] = min(curve_values) if curve_values else None
    return values, warnings


def _run_mtf_at_current_focus(
    oss: Any,
    run_dir: Path,
    image_distance: float,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        data, mtf_warnings = _run_fft_mtf_dataframe(oss, max(REQUESTED_FREQS))
    finally:
        close_all_analysis_windows(oss)
    warnings.extend(mtf_warnings)
    if data is None or not isinstance(data, DataFrame) or data.empty:
        raise RuntimeError("FFT MTF returned no usable DataFrame.")

    raw_path = run_dir / f"raw_mtf_image_distance_{_distance_label(image_distance)}.csv"
    data.to_csv(raw_path, index=True, encoding="utf-8-sig")
    frequencies, series = _read_mtf(raw_path)
    if not frequencies or not series:
        raise RuntimeError("Could not parse FFT MTF curves from raw DataFrame.")

    values: dict[str, Any] = {"raw_mtf_csv": str(raw_path)}
    for field in REQUESTED_FIELDS:
        field_values, field_warnings = _curve_values_for_field(frequencies, series, field)
        values.update(field_values)
        warnings.extend(field_warnings)
    return values, warnings


def _row_score(row: dict[str, Any], fields: tuple[float, ...] = REQUESTED_FIELDS) -> tuple[float | None, float | None]:
    mins: list[float] = []
    for field in fields:
        for orientation in ("T", "S"):
            value = _to_float(row.get(f"field_{_field_key(field)}_{orientation}_min_20_50"))
            if value is not None:
                mins.append(value)
    if not mins:
        return None, None
    return min(mins), sum(mins) / len(mins)


def _center_score(row: dict[str, Any]) -> float | None:
    values = [
        _to_float(row.get("field_0_T_min_20_50")),
        _to_float(row.get("field_0_S_min_20_50")),
    ]
    valid = [value for value in values if value is not None]
    return min(valid) if valid else None


def _best_row(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("status") in {"success", "partial"} and _to_float(row.get(score_key)) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _to_float(row.get(score_key)) or -1.0)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "image_distance",
        "estimated_TTL",
        "BFL",
        "EFL",
        "field_0_T_min_20_50",
        "field_0_S_min_20_50",
        "field_21_T_min_20_50",
        "field_21_S_min_20_50",
        "field_35_T_min_20_50",
        "field_35_S_min_20_50",
        "field_49_T_min_20_50",
        "field_49_S_min_20_50",
        "center_score",
        "worst_score_0_21_35_49",
        "mean_score_0_21_35_49",
        "ttl_lt_18",
        "bfl_gt_2p3",
        "status",
        "failure_reason",
        "warnings",
        "raw_mtf_csv",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _best_line(label: str, row: dict[str, Any] | None, score_key: str) -> str:
    if row is None:
        return f"{label}: none"
    return (
        f"{label}: image_distance={_fmt(row.get('image_distance'))}, "
        f"{score_key}={_fmt(row.get(score_key))}, "
        f"TTL={_fmt(row.get('estimated_TTL'))}, BFL={_fmt(row.get('BFL'))}, "
        f"ttl_lt_18={row.get('ttl_lt_18')}, bfl_gt_2p3={row.get('bfl_gt_2p3')}"
    )


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    base_summary: dict[str, Any],
    rows: list[dict[str, Any]],
    original_restored: bool,
    available_fields: list[float],
) -> None:
    center_best = _best_row(rows, "center_score")
    overall_best = _best_row(rows, "mean_score_0_21_35_49")
    failed = [row for row in rows if row.get("status") == "failed"]
    partial = [row for row in rows if row.get("status") == "partial"]

    lines = [
        "Focus Scan After Geometry Repair",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        f"original_image_distance_restored: {str(original_restored).lower()}",
        "",
        "[base_system]",
        f"EFL: {_fmt(base_summary.get('efl'))}",
        f"F_number: {_fmt(base_summary.get('f_number'))}",
        f"TTL: {_fmt(base_summary.get('ttl'))}",
        f"BFL: {_fmt(base_summary.get('bfl'))}",
        f"image_surface: {_fmt(base_summary.get('image_surface'))}",
        f"last_surface_before_image: {_fmt(base_summary.get('last_surface_before_image'))}",
        f"original_image_distance: {_fmt(base_summary.get('image_distance'))}",
        f"available_lens_fields: {', '.join(_fmt(field) for field in available_fields) if available_fields else 'unknown'}",
        "",
        "[best_points]",
        _best_line("center_field_best", center_best, "center_score"),
        _best_line("combined_0_21_35_49_best", overall_best, "mean_score_0_21_35_49"),
        "",
        "[scan_rows]",
    ]

    for row in rows:
        lines.append(
            "  "
            f"d={_fmt(row.get('image_distance'))}: "
            f"TTL={_fmt(row.get('estimated_TTL'))}, BFL={_fmt(row.get('BFL'))}, "
            f"0T={_fmt(row.get('field_0_T_min_20_50'))}, 0S={_fmt(row.get('field_0_S_min_20_50'))}, "
            f"21T={_fmt(row.get('field_21_T_min_20_50'))}, 21S={_fmt(row.get('field_21_S_min_20_50'))}, "
            f"35T={_fmt(row.get('field_35_T_min_20_50'))}, 35S={_fmt(row.get('field_35_S_min_20_50'))}, "
            f"49T={_fmt(row.get('field_49_T_min_20_50'))}, 49S={_fmt(row.get('field_49_S_min_20_50'))}, "
            f"mean={_fmt(row.get('mean_score_0_21_35_49'))}, worst={_fmt(row.get('worst_score_0_21_35_49'))}, "
            f"status={row.get('status')}"
            + (f", failure={row.get('failure_reason')}" if row.get("failure_reason") else "")
        )

    lines.extend(
        [
            "",
            "[interpretation]",
        ]
    )
    if overall_best is None:
        lines.append("No usable FFT MTF result was produced; focus state cannot be diagnosed from this run.")
    else:
        base_distance = _to_float(base_summary.get("image_distance"))
        best_distance = _to_float(overall_best.get("image_distance"))
        if base_distance is not None and best_distance is not None:
            delta = best_distance - base_distance
            if abs(delta) <= 0.05:
                lines.append("The best combined point is close to the current image distance; gross defocus is unlikely to be the only issue.")
            else:
                lines.append(
                    f"The best combined point shifts image distance by {delta:.6g} mm; current performance may be focus-position limited."
                )
        lines.append(
            "Use this as a diagnostic only. The script did not save the lens and did not perform Quick Focus or optimization."
        )

    if partial:
        lines.append(f"partial_points: {len(partial)}; some requested field/orientation curves were missing.")
    if failed:
        lines.append(f"failed_points: {len(failed)}")
        for row in failed:
            lines.append(f"  image_distance={_fmt(row.get('image_distance'))}: {row.get('failure_reason')}")

    lines.extend(
        [
            "",
            "[files]",
            f"focus_scan_summary_csv: {path.parent / 'focus_scan_summary.csv'}",
            f"focus_scan_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scan_distances(current: float | None) -> list[float]:
    values = set(DEFAULT_IMAGE_DISTANCES)
    if current is not None:
        values.add(round(current, 10))
    return sorted(values)


def scan_focus(project_root: Path, lens: Path, label: str) -> Path:
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id, run_dir = _unique_run_dir(project_root, label)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"actual lens path: {lens}", flush=True)
    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    print("Loading lens read-only diagnostic session...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    base_summary = _system_summary(oss)
    available_fields = _available_fields(oss)

    image_surface = base_summary.get("image_surface")
    last_surface = base_summary.get("last_surface_before_image")
    if not isinstance(image_surface, int) or not isinstance(last_surface, int) or last_surface <= 0:
        raise RuntimeError("Could not identify image surface and image-side final thickness surface.")

    original_distance = _to_float(base_summary.get("image_distance"))
    if original_distance is None:
        raise RuntimeError("Could not read original image-side final thickness.")

    target_surface = lde.GetSurfaceAt(last_surface)
    rows: list[dict[str, Any]] = []
    restored = False

    try:
        for distance in _scan_distances(original_distance):
            print(f"Scanning image_distance={distance:g} mm", flush=True)
            row: dict[str, Any] = {
                "image_distance": distance,
                "estimated_TTL": (
                    base_summary["ttl"] + (distance - original_distance)
                    if _to_float(base_summary.get("ttl")) is not None
                    else None
                ),
                "BFL": distance,
                "EFL": base_summary.get("efl"),
                "status": "failed",
                "failure_reason": None,
                "warnings": None,
            }
            try:
                target_surface.Thickness = distance
                try:
                    oss.update_status()
                except Exception:
                    pass

                mtf_values, mtf_warnings = _run_mtf_at_current_focus(oss, run_dir, distance)
                for key, value in mtf_values.items():
                    if key == "raw_mtf_csv":
                        row[key] = value
                        continue
                    # key shape: 21_T_min_20_50
                    row[f"field_{key}"] = value
                if mtf_warnings:
                    row["warnings"] = " | ".join(mtf_warnings)

                center = _center_score(row)
                worst, mean = _row_score(row)
                row["center_score"] = center
                row["worst_score_0_21_35_49"] = worst
                row["mean_score_0_21_35_49"] = mean
                row["ttl_lt_18"] = bool(_to_float(row.get("estimated_TTL")) is not None and float(row["estimated_TTL"]) < 18.0)
                row["bfl_gt_2p3"] = bool(distance > 2.3)
                row["status"] = "partial" if mtf_warnings else "success"
            except Exception as exc:
                row["failure_reason"] = f"{type(exc).__name__}: {exc!r}"
                row["ttl_lt_18"] = bool(_to_float(row.get("estimated_TTL")) is not None and float(row["estimated_TTL"]) < 18.0)
                row["bfl_gt_2p3"] = bool(distance > 2.3)
            rows.append(row)
    finally:
        try:
            target_surface.Thickness = original_distance
            try:
                oss.update_status()
            except Exception:
                pass
            restored = _to_float(target_surface.Thickness) == original_distance
        except Exception:
            restored = False
        close_all_analysis_windows(oss)

    metadata = {
        "run_id": run_id,
        "lens": str(lens),
        "output_folder": str(run_dir),
        "read_only": True,
        "saved_lens": False,
        "optimized": False,
        "scanned_surface": last_surface,
        "original_image_distance": original_distance,
        "scan_distances": _scan_distances(original_distance),
        "fields": list(REQUESTED_FIELDS),
        "frequencies": list(REQUESTED_FREQS),
        "base_summary": base_summary,
        "original_image_distance_restored": restored,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(run_dir / "focus_scan_summary.csv", rows)
    _write_report(
        run_dir / "focus_scan_report.txt",
        lens=lens,
        run_id=run_id,
        base_summary=base_summary,
        rows=rows,
        original_restored=restored,
        available_fields=available_fields,
    )

    print(f"run_id: {run_id}", flush=True)
    print(f"output_folder: {run_dir}", flush=True)
    print(f"focus_scan_summary: {run_dir / 'focus_scan_summary.csv'}", flush=True)
    print(f"focus_scan_report: {run_dir / 'focus_scan_report.txt'}", flush=True)
    print(f"original_image_distance_restored: {str(restored).lower()}", flush=True)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Temporarily scan image-side final thickness to diagnose defocus after geometry repair."
    )
    parser.add_argument("--lens", required=True, type=Path, help="Lens path. The script does not save or modify the file.")
    parser.add_argument("--label", default="focus_scan_after_geometry_repair", help="Label used in output run_id.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    scan_focus(project_root, args.lens, args.label)


if __name__ == "__main__":
    main()
