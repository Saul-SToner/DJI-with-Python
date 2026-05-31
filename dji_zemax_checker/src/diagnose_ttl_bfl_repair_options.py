from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from export_surfaces import collect_surfaces
from export_system_summary import _analysis_summary, _direct_optical_summary

LENS_PATH = Path(r"C:\Users\L2791\OneDrive\Desktop\PatentSeed_US20170293107A1_Emb1_unmodified.zos")
PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")

CSV_FIELDS = [
    "surface_number",
    "comment",
    "radius",
    "thickness",
    "glass",
    "semi_diameter",
    "segment_after_surface",
    "classification",
    "is_candidate_degree_of_freedom",
    "suggested_min_safe_thickness",
    "theoretical_max_compression",
    "risk_note",
]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_ttl_bfl")


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


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _is_glass(row: dict[str, Any]) -> bool:
    return bool(str(row.get("glass") or row.get("material") or "").strip())


def _classification(row: dict[str, Any], next_row: dict[str, Any] | None, image_surface: int) -> str:
    surface_number = int(row["surface_number"])
    comment = f"{row.get('comment') or ''} {next_row.get('comment') if next_row else ''}".lower()
    glass = str(row.get("glass") or "").strip()

    if surface_number == image_surface - 1:
        return "image-side final space"
    if "filter" in comment or "cover" in comment:
        if glass:
            return "filter / cover glass"
        return "filter / cover glass gap"
    if glass:
        return "glass thickness"
    return "air gap"


def _suggested_min_safe_thickness(row: dict[str, Any], next_row: dict[str, Any] | None, classification: str) -> float | None:
    if classification != "air gap" and classification != "filter / cover glass gap":
        return None
    surface_number = int(row["surface_number"])
    comment = f"{row.get('comment') or ''} {next_row.get('comment') if next_row else ''}".lower()
    if "filter" in comment or "cover" in comment:
        return 0.10
    if surface_number in {2, 4}:
        return 0.20
    return 0.05


def _candidate_status(classification: str) -> str:
    if classification in {"air gap", "filter / cover glass gap", "image-side final space"}:
        return "yes"
    return "no"


def _risk_note(row: dict[str, Any], next_row: dict[str, Any] | None, classification: str) -> str:
    surface_number = int(row["surface_number"])
    next_number = int(next_row["surface_number"]) if next_row else None
    if surface_number in {2, 4}:
        return "front-group air gap already repaired for overlap; compressing it may reintroduce overlap risk"
    if classification == "image-side final space":
        return "directly affects BFL/image plane position; reducing it worsens already-short or negative BFL"
    comment = f"{row.get('comment') or ''} {next_row.get('comment') if next_row else ''}".lower()
    if "filter" in comment or "cover" in comment:
        return "filter/cover spacing may be mechanically constrained"
    if classification == "air gap":
        return f"air gap S{surface_number}->S{next_number}; candidate only after checking ray clearance and edge gaps"
    if classification == "glass thickness":
        return "glass thickness is not a simple spacing freedom; changing it modifies lens prescription"
    return ""


def _surface_spacing_rows(surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    image_surface = len(surfaces) - 1
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(surfaces):
        surface_number = int(row["surface_number"])
        next_row = surfaces[index + 1] if index + 1 < len(surfaces) else None
        thickness = _to_float(row.get("thickness"))
        classification = _classification(row, next_row, image_surface)
        min_safe = _suggested_min_safe_thickness(row, next_row, classification)
        max_compression = None
        if thickness is not None and min_safe is not None:
            max_compression = max(0.0, thickness - min_safe)
        rows.append(
            {
                "surface_number": surface_number,
                "comment": row.get("comment"),
                "radius": row.get("radius"),
                "thickness": row.get("thickness"),
                "glass": row.get("glass"),
                "semi_diameter": row.get("semi_diameter"),
                "segment_after_surface": f"S{surface_number}->S{surface_number + 1}" if next_row else "",
                "classification": classification,
                "is_candidate_degree_of_freedom": _candidate_status(classification),
                "suggested_min_safe_thickness": min_safe,
                "theoretical_max_compression": max_compression,
                "risk_note": _risk_note(row, next_row, classification),
            }
        )
    return rows


def _write_spacing_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _last_air_thickness_before_image(oss: Any) -> float | None:
    try:
        image_surface = int(oss.LDE.NumberOfSurfaces) - 1
        return _to_float(oss.LDE.GetSurfaceAt(image_surface - 1).Thickness)
    except Exception:
        return None


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

    if _to_float(metrics.get("bfl")) is None:
        metrics["bfl"] = _last_air_thickness_before_image(oss)
        metrics["bfl_source"] = "LDE image-before thickness fallback"
    else:
        metrics["bfl_source"] = "SystemData/direct"
    metrics["ttl_source"] = "SystemData/direct" if _to_float(metrics.get("ttl")) is not None else "unknown"
    return metrics, warnings


def _sum_potential(rows: list[dict[str, Any]], include_final_space: bool) -> float:
    total = 0.0
    for row in rows:
        if row["classification"] == "image-side final space" and not include_final_space:
            continue
        value = _to_float(row.get("theoretical_max_compression"))
        if value is not None:
            total += value
    return total


def _rows_by_surface(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["surface_number"]): row for row in rows}


def _write_report(
    path: Path,
    metrics: dict[str, Any],
    spacing_rows: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    ttl = _to_float(metrics.get("ttl"))
    bfl = _to_float(metrics.get("bfl"))
    ttl_excess = ttl - 18.0 if ttl is not None else None
    bfl_shortfall = 2.3 - bfl if bfl is not None else None
    spacing_by_surface = _rows_by_surface(spacing_rows)
    air_compression_without_final = _sum_potential(spacing_rows, include_final_space=False)
    air_compression_with_final = _sum_potential(spacing_rows, include_final_space=True)

    simultaneous_possible = "unknown"
    if ttl_excess is not None and bfl_shortfall is not None:
        if bfl <= 2.3:
            simultaneous_possible = (
                "unlikely by only compressing air gaps; reducing final image-side space would further reduce BFL"
            )
        elif air_compression_without_final >= max(0.0, ttl_excess):
            simultaneous_possible = "possibly, using non-final air gaps only, subject to geometry/ray-clearance checks"
        else:
            simultaneous_possible = "unlikely; available non-final air-gap compression is insufficient"

    lines = [
        "TTL / BFL Repair Options Diagnostic",
        f"lens_path: {LENS_PATH}",
        "read_only: true; no save/save_as/optimization/surface edits are used.",
        "",
        "[current_metrics]",
        f"current TTL: {_fmt(ttl)} mm",
        f"current BFL: {_fmt(bfl)} mm",
        f"BFL source: {metrics.get('bfl_source')}",
        f"TTL source: {metrics.get('ttl_source')}",
        f"TTL distance to <18 mm: {_fmt(ttl_excess if ttl_excess is not None and ttl_excess > 0 else 0.0)} mm",
        f"BFL distance to >2.3 mm: {_fmt(bfl_shortfall if bfl_shortfall is not None and bfl_shortfall > 0 else 0.0)} mm",
        f"non-final air/filter-gap theoretical compression: {_fmt(air_compression_without_final)} mm",
        f"including final image-side space theoretical compression: {_fmt(air_compression_with_final)} mm",
        f"only-air-gap simultaneous feasibility: {simultaneous_possible}",
        "",
        "[important_segments]",
    ]

    for surface_number, label in (
        (2, "S2 thickness"),
        (4, "S4 thickness"),
    ):
        row = spacing_by_surface.get(surface_number)
        if row:
            lines.append(
                f"{label}: thickness={_fmt(row.get('thickness'))} mm, "
                f"classification={row['classification']}, max_compression={_fmt(row.get('theoretical_max_compression'))}, "
                f"risk={row['risk_note']}"
            )

    for row in spacing_rows:
        note = str(row.get("risk_note") or "").lower()
        classification = str(row.get("classification") or "")
        if "filter" in classification.lower() or "cover" in classification.lower() or "filter" in note or "cover" in note:
            lines.append(
                f"filter/cover related {row['segment_after_surface']}: thickness={_fmt(row.get('thickness'))} mm, "
                f"classification={classification}, max_compression={_fmt(row.get('theoretical_max_compression'))}, risk={row['risk_note']}"
            )
        if classification == "image-side final space":
            lines.append(
                f"cover glass to image / final image-side space {row['segment_after_surface']}: "
                f"thickness={_fmt(row.get('thickness'))} mm, max_compression={_fmt(row.get('theoretical_max_compression'))}, "
                f"risk={row['risk_note']}"
            )

    lines.extend(["", "[candidate_air_gap_degrees_of_freedom]"])
    candidates = [
        row
        for row in spacing_rows
        if row["is_candidate_degree_of_freedom"] == "yes" and row["classification"] != "image-side final space"
    ]
    if candidates:
        for row in candidates:
            lines.append(
                f"{row['segment_after_surface']}: thickness={_fmt(row.get('thickness'))} mm, "
                f"min_safe={_fmt(row.get('suggested_min_safe_thickness'))} mm, "
                f"max_compression={_fmt(row.get('theoretical_max_compression'))} mm, risk={row['risk_note']}"
            )
    else:
        lines.append("none")

    lines.extend(["", "[BFL_negative_note]"])
    if bfl is not None and bfl < 0:
        lines.append(
            "BFL is negative. 当前结构像方后焦不满足题面；后续可能需要移动像面、检查/压缩 cover/filter 空间、"
            "或重新分配后组光焦度。仅压缩普通空气间隔通常不能把负 BFL 修成 >2.3 mm。"
        )
    elif bfl is not None and bfl <= 2.3:
        lines.append(
            "BFL is positive but below 2.3 mm. Reducing final image-side space would worsen BFL; repair likely needs optical power or image-plane strategy."
        )
    else:
        lines.append("BFL currently clears 2.3 mm; avoid using final image-side space as TTL compression unless BFL margin is preserved.")

    lines.extend(["", "[warnings]"])
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_ttl_bfl_repair_options() -> None:
    run_id = _run_id()
    output_dir = PROJECT_ROOT / "results" / "ttl_bfl_diagnostics" / run_id
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

    metadata = {"run_id": run_id, "current_lens_file": str(LENS_PATH)}
    surfaces = collect_surfaces(oss, metadata)
    spacing_rows = _surface_spacing_rows(surfaces)
    metrics, warnings = _system_metrics(oss, output_dir, run_id)

    table_path = output_dir / "surface_spacing_table.csv"
    report_path = output_dir / "ttl_bfl_repair_report.txt"
    _write_spacing_csv(table_path, spacing_rows)
    _write_report(report_path, metrics, spacing_rows, warnings)

    print(f"report path: {report_path}", flush=True)


if __name__ == "__main__":
    diagnose_ttl_bfl_repair_options()
