from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from export_system_summary import _analysis_summary, _direct_optical_summary, _read_fields

LENS_PATH = Path(r"C:\Users\L2791\OneDrive\Desktop\PatentSeed_US20170293107A1_Emb1_unmodified.zos")
PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")

TARGET_IMAGE_RADIUS = 8.0
TARGET_IMAGE_CIRCLE = 16.0
TARGET_HALF_FIELD_DEG = 70.0
TARGET_TTL_MAX = 18.0
TARGET_BFL_MIN = 2.3

CSV_FIELDS = [
    "item",
    "value",
    "unit",
    "status",
    "note",
]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_format_scaling")


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is not None:
        return f"{number:.8g}"
    if value is None:
        return "unknown"
    return str(value)


def _status_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _image_semi_diameter(oss: Any) -> tuple[float | None, str | None]:
    try:
        image_surface = int(oss.LDE.NumberOfSurfaces) - 1
        return _to_float(oss.LDE.GetSurfaceAt(image_surface).SemiDiameter), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc!r}"


def _max_half_field(oss: Any) -> tuple[float | None, str | None]:
    try:
        fields = _read_fields(oss)
        values = [_to_float(row.get("y")) for row in fields]
        finite = [value for value in values if value is not None]
        return max(finite) if finite else None, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc!r}"


def _system_metrics(oss: Any, output_dir: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    direct = _direct_optical_summary(oss)
    raw, raw_warnings, _raw_status = _analysis_summary(
        oss,
        output_dir,
        run_metadata={"run_id": run_id, "current_lens_file": str(LENS_PATH)},
    )
    warnings.extend(raw_warnings)
    metrics = dict(direct)
    if raw:
        for key, value in raw.items():
            if value is not None:
                metrics[key] = value
    return metrics, warnings


def _projection_target_efl(theta_deg: float, image_radius: float) -> dict[str, float]:
    theta = math.radians(theta_deg)
    return {
        "rectilinear": image_radius / math.tan(theta),
        "equidistant": image_radius / theta,
        "equisolid": image_radius / (2.0 * math.sin(theta / 2.0)),
        "stereographic": image_radius / (2.0 * math.tan(theta / 2.0)),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _append(rows: list[dict[str, Any]], item: str, value: Any, unit: str, status: str, note: str) -> None:
    rows.append({"item": item, "value": _fmt(value), "unit": unit, "status": status, "note": note})


def _write_report(path: Path, rows: list[dict[str, Any]], warnings: list[str]) -> None:
    lines = [
        "Format Scaling Feasibility Diagnostic",
        f"lens_path: {LENS_PATH}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        "",
        "[table]",
    ]
    for row in rows:
        lines.append(
            f"{row['item']}: {row['value']} {row['unit']} | status={row['status']} | {row['note']}"
        )
    lines.extend(["", "[warnings]"])
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("none")
    lines.extend(
        [
            "",
            "[interpretation]",
            "当前结构只能证明超广角拓扑，不等于大疆 16 mm 像圆、TTL<18 mm、BFL>2.3 mm 规格 seed。",
            "如果简单按像圆放大导致 TTL 明显超过 18 mm，则 simple scaling 不可行。",
            "如果当前 BFL 为负或远低于 2.3 mm，则仅靠压缩空气间隔通常不能满足 BFL，需要后组光焦度/像方空间重新分配。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_format_scaling_feasibility() -> None:
    run_id = _run_id()
    output_dir = PROJECT_ROOT / "results" / "format_scaling_feasibility" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    if not LENS_PATH.exists():
        print(f"[ERROR] Lens file does not exist: {LENS_PATH}", flush=True)
        raise SystemExit(1)

    try:
        oss.load(str(LENS_PATH), saveifneeded=False)
    except Exception as exc:
        print(f"[ERROR] Failed to open lens: {LENS_PATH}", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    warnings: list[str] = []
    metrics, metric_warnings = _system_metrics(oss, output_dir, run_id)
    warnings.extend(metric_warnings)
    image_radius, image_warning = _image_semi_diameter(oss)
    if image_warning:
        warnings.append(f"image semi-diameter unavailable: {image_warning}")
    max_field, field_warning = _max_half_field(oss)
    if field_warning:
        warnings.append(f"field list unavailable: {field_warning}")

    efl = _to_float(metrics.get("efl"))
    ttl = _to_float(metrics.get("ttl"))
    bfl = _to_float(metrics.get("bfl"))
    rows: list[dict[str, Any]] = []

    _append(rows, "current_efl", efl, "mm", "record", "current patent seed EFL")
    _append(rows, "current_ttl", ttl, "mm", "pass" if ttl is not None and ttl < TARGET_TTL_MAX else "fail", "target TTL < 18 mm")
    _append(rows, "current_bfl", bfl, "mm", "pass" if bfl is not None and bfl > TARGET_BFL_MIN else "fail", "target BFL > 2.3 mm")
    _append(rows, "current_image_radius", image_radius, "mm", "record", "current image semi-diameter")
    _append(rows, "target_image_radius", TARGET_IMAGE_RADIUS, "mm", "record", "16 mm full image circle")
    _append(rows, "current_max_half_field", max_field, "deg", "pass" if max_field is not None and max_field >= TARGET_HALF_FIELD_DEG else "fail", "target half field 70 deg")

    target_efls = _projection_target_efl(TARGET_HALF_FIELD_DEG, TARGET_IMAGE_RADIUS)
    for model, target_efl in target_efls.items():
        ratio = target_efl / efl if efl not in (None, 0) else None
        ttl_scaled = ttl * ratio if ttl is not None and ratio is not None else None
        _append(rows, f"target_efl_{model}", target_efl, "mm", "record", f"projection model y=f(theta), theta={TARGET_HALF_FIELD_DEG:g} deg, y=8 mm")
        _append(rows, f"efl_ratio_target_over_current_{model}", ratio, "x", "record", "target EFL divided by current EFL")
        _append(
            rows,
            f"ttl_estimated_by_target_efl_{model}",
            ttl_scaled,
            "mm",
            "pass" if ttl_scaled is not None and ttl_scaled < TARGET_TTL_MAX else "fail",
            "simple geometric scaling by target EFL ratio",
        )

    image_scale = TARGET_IMAGE_RADIUS / image_radius if image_radius not in (None, 0) else None
    ttl_by_image_scale = ttl * image_scale if ttl is not None and image_scale is not None else None
    _append(rows, "image_radius_scale_to_8mm", image_scale, "x", "record", "8 mm target radius divided by current image radius")
    _append(
        rows,
        "ttl_estimated_by_image_radius_scale",
        ttl_by_image_scale,
        "mm",
        "pass" if ttl_by_image_scale is not None and ttl_by_image_scale < TARGET_TTL_MAX else "fail",
        "simple scaling by image radius",
    )

    bfl_increase_needed = TARGET_BFL_MIN - bfl if bfl is not None else None
    _append(
        rows,
        "bfl_increase_needed_to_clear_2p3",
        bfl_increase_needed if bfl_increase_needed is None or bfl_increase_needed > 0 else 0.0,
        "mm",
        "fail" if bfl is not None and bfl <= TARGET_BFL_MIN else "pass",
        "amount needed for BFL > 2.3 mm",
    )

    simple_scaling_feasible = ttl_by_image_scale is not None and ttl_by_image_scale < TARGET_TTL_MAX and bfl is not None and bfl > TARGET_BFL_MIN
    air_gap_compression_feasible = False if bfl is not None and bfl <= TARGET_BFL_MIN else None
    rear_group_needed = bfl is not None and bfl <= TARGET_BFL_MIN
    large_format_seed_needed = ttl_by_image_scale is not None and ttl_by_image_scale >= TARGET_TTL_MAX
    _append(rows, "simple_scaling_feasible", _status_bool(simple_scaling_feasible), "", "record", "requires scaled TTL <18 and BFL already >2.3")
    _append(rows, "air_gap_compression_feasible", _status_bool(air_gap_compression_feasible), "", "record", "air compression cannot fix negative/short BFL")
    _append(rows, "likely_need_rear_group_power_redistribution", _status_bool(rear_group_needed), "", "record", "based on BFL shortfall")
    _append(rows, "likely_need_new_large_format_seed", _status_bool(large_format_seed_needed), "", "record", "based on scaled TTL/image circle mismatch")

    table_path = output_dir / "format_scaling_table.csv"
    report_path = output_dir / "format_scaling_feasibility_report.txt"
    _write_csv(table_path, rows)
    _write_report(report_path, rows, warnings)

    print(f"report path: {report_path}", flush=True)


if __name__ == "__main__":
    diagnose_format_scaling_feasibility()
