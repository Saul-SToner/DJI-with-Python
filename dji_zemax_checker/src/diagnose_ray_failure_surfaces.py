from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp
from zospy.analyses.raysandspots.single_ray_trace import SingleRayTrace

from zosapi_cleanup import close_all_analysis_windows


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
FIELDS_DEG = (0.0, 21.0, 35.0, 49.0, 63.0, 70.0)
PUPIL_SAMPLES = (
    (0.0, 0.0),
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (0.707, 0.707),
    (0.707, -0.707),
    (-0.707, 0.707),
    (-0.707, -0.707),
    (0.5, 0.0),
    (-0.5, 0.0),
    (0.0, 0.5),
    (0.0, -0.5),
)
WATCH_SURFACES = {
    2: "S2/S3 clamp neighborhood",
    3: "S2/S3 clamp neighborhood",
    6: "S6/S7 0.05 mm air gap neighborhood",
    7: "S6/S7 air gap and S7/S8 clamp neighborhood",
    8: "S7/S8 clamp neighborhood",
}


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, digits: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    return f"{number:.{digits}g}"


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _field_key(field: float) -> str:
    return f"{field:g}".replace(".", "p")


def _pupil_key(px: float, py: float) -> str:
    def part(value: float) -> str:
        prefix = "p" if value >= 0 else "m"
        return f"{prefix}{abs(value):g}".replace(".", "p")

    return f"px{part(px)}_py{part(py)}"


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "mbcs"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return path.read_text(errors="replace")


def _numbers_from_line(line: str) -> list[float]:
    values: list[float] = []
    pattern = r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?|[-+]?\.\d+(?:[Ee][-+]?\d+)?"
    for token in re.findall(pattern, line):
        number = _to_float(token)
        if number is not None:
            values.append(number)
    return values


def _actual_ray_trace_lines(text: str) -> list[str]:
    lines = text.splitlines()
    start = 0
    end = len(lines)
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "real ray trace data" in lowered or "实际光线追迹数据" in line:
            start = index + 1
            break
    for index in range(start, len(lines)):
        lowered = lines[index].lower()
        if "paraxial" in lowered or "近轴" in lines[index]:
            end = index
            break
    return lines[start:end]


def _parse_trace_rows(text: str) -> dict[int, dict[str, float]]:
    rows: dict[int, dict[str, float]] = {}
    for line in _actual_ray_trace_lines(text):
        stripped = line.strip()
        if not re.match(r"^\d+\s", stripped):
            continue
        numbers = _numbers_from_line(stripped)
        if len(numbers) < 3:
            continue
        surface = int(numbers[0])
        row = {"x": numbers[1], "y": numbers[2]}
        if len(numbers) >= 7:
            row.update({"z": numbers[3], "l": numbers[4], "m": numbers[5], "n": numbers[6]})
        rows[surface] = row
    return rows


def _parse_reported_failed_surface(text: str) -> int | None:
    patterns = (
        r"(?:surface|surf\.?|面)\s*[:=#]?\s*(\d+)",
        r"(?:miss|vignet|fail|error|错误|失败|截光|未命中)[^\n\r]{0,80}?(\d+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _to_float(match.group(1))
            if value is not None and value >= 0:
                return int(value)
    return None


def _surface_table(oss: Any) -> dict[int, dict[str, Any]]:
    lde = oss.LDE
    rows: dict[int, dict[str, Any]] = {}
    for index in range(int(lde.NumberOfSurfaces)):
        surface = lde.GetSurfaceAt(index)
        is_stop = bool(_safe_get(surface, "IsStop", False))
        comment = str(_safe_get(surface, "Comment", "") or "")
        rows[index] = {
            "surface_number": index,
            "comment": comment,
            "radius": _to_float(_safe_get(surface, "Radius")),
            "thickness": _to_float(_safe_get(surface, "Thickness")),
            "glass": str(_safe_get(surface, "Material", "") or ""),
            "semi_diameter": _to_float(_safe_get(surface, "SemiDiameter")),
            "is_stop": is_stop,
            "watch_note": WATCH_SURFACES.get(index, "STOP surface" if is_stop else ""),
        }
    return rows


def _field_table(oss: Any) -> list[dict[str, Any]]:
    fields = _safe_get(_safe_get(oss, "SystemData"), "Fields")
    count = int(_safe_get(fields, "NumberOfFields", 0) or 0)
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        try:
            item = fields.GetField(index)
        except Exception:
            continue
        rows.append(
            {
                "number": index,
                "x": _to_float(_safe_get(item, "X")),
                "y": _to_float(_safe_get(item, "Y")),
                "weight": _to_float(_safe_get(item, "Weight")),
            }
        )
    return rows


def _field_number(fields: list[dict[str, Any]], field_deg: float) -> int | None:
    candidates: list[tuple[float, int]] = []
    for row in fields:
        y = _to_float(row.get("y"))
        number = row.get("number")
        if y is not None and number is not None:
            candidates.append((abs(y - field_deg), int(number)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] < 1e-6 else None


def _likely_failure_type(text: str, failed_surface: int | None, surface_info: dict[str, Any] | None) -> str:
    lower = text.lower()
    combined = lower + " " + str(surface_info or {}).lower()
    if any(token in combined for token in ("vignet", "vignette", "aperture", "semi", "clear", "截光", "孔径")):
        return "likely_aperture_or_vignetting"
    if any(token in combined for token in ("miss", "intersection", "intersect", "ray trace", "未命中", "交点")):
        return "likely_surface_intersection_failure"
    if surface_info and _to_float(surface_info.get("semi_diameter")) is not None:
        return "possible_clear_aperture_or_intersection_failure"
    if failed_surface is None:
        return "unknown"
    return "possible_surface_intersection_failure"


def _trace_one(
    oss: Any,
    *,
    field_number: int,
    field_deg: float,
    px: float,
    py: float,
    image_surface: int,
    raw_path: Path,
) -> tuple[dict[str, Any], str]:
    wrapper_error = None
    text = ""
    try:
        if raw_path.exists():
            raw_path.unlink()
        SingleRayTrace(
            hx=0.0,
            hy=0.0,
            px=px,
            py=py,
            field=field_number,
            raytrace_type="DirectionCosines",
            global_coordinates=False,
        ).run(oss, text_output_file=raw_path)
    except Exception as exc:
        wrapper_error = f"{type(exc).__name__}: {exc!r}"
    finally:
        close_all_analysis_windows(oss)

    if raw_path.exists():
        text = _read_text_file(raw_path)
    rows = _parse_trace_rows(text) if text else {}
    status = "success" if image_surface in rows else "failed"
    last_success = max(rows) if rows else None
    reported_failed = _parse_reported_failed_surface(text)
    inferred_failed = reported_failed
    if inferred_failed is None and last_success is not None and last_success < image_surface:
        inferred_failed = last_success + 1

    last_row = rows.get(last_success) if last_success is not None else None
    reason_parts = []
    if wrapper_error:
        reason_parts.append(f"wrapper_error={wrapper_error}")
    if status == "failed" and not rows:
        reason_parts.append("no parseable real ray trace rows")
    if status == "failed" and rows and image_surface not in rows:
        reason_parts.append(f"trace stopped before image; last_success_surface={last_success}")
    if status == "success" and wrapper_error:
        status = "success_with_wrapper_warning"
    return (
        {
            "field_deg": field_deg,
            "field_number": field_number,
            "px": px,
            "py": py,
            "status": status,
            "failed_surface": inferred_failed,
            "reported_failed_surface": reported_failed,
            "last_success_surface": last_success,
            "last_success_x": None if last_row is None else last_row.get("x"),
            "last_success_y": None if last_row is None else last_row.get("y"),
            "failure_reason": "; ".join(reason_parts) if reason_parts else None,
            "raw_trace_file": str(raw_path),
        },
        text,
    )


def _write_detail(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "field_deg",
        "field_number",
        "px",
        "py",
        "status",
        "failed_surface",
        "failed_surface_comment",
        "failed_surface_glass",
        "failed_surface_watch_note",
        "reported_failed_surface",
        "last_success_surface",
        "last_success_x",
        "last_success_y",
        "likely_failure_type",
        "failure_reason",
        "raw_trace_file",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "surface_number",
        "comment",
        "glass",
        "semi_diameter",
        "is_stop",
        "watch_note",
        "failure_count",
        "fields",
        "pupil_points",
        "likely_failure_types",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summarize_failures(detail_rows: list[dict[str, Any]], surfaces: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in detail_rows:
        if row.get("status") == "success":
            continue
        surface = row.get("failed_surface")
        if surface is None:
            continue
        try:
            grouped[int(surface)].append(row)
        except (TypeError, ValueError):
            continue

    summary_rows: list[dict[str, Any]] = []
    for surface, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        info = surfaces.get(surface, {})
        fields = sorted({_fmt(row.get("field_deg")) for row in rows})
        pupils = sorted({f"({_fmt(row.get('px'))},{_fmt(row.get('py'))})" for row in rows})
        types = sorted({str(row.get("likely_failure_type") or "unknown") for row in rows})
        summary_rows.append(
            {
                "surface_number": surface,
                "comment": info.get("comment"),
                "glass": info.get("glass"),
                "semi_diameter": info.get("semi_diameter"),
                "is_stop": info.get("is_stop"),
                "watch_note": info.get("watch_note"),
                "failure_count": len(rows),
                "fields": "; ".join(fields),
                "pupil_points": "; ".join(pupils),
                "likely_failure_types": "; ".join(types),
            }
        )
    return summary_rows


def _report_field_failures(detail_rows: list[dict[str, Any]], field: float) -> str:
    rows = [row for row in detail_rows if _to_float(row.get("field_deg")) == field and row.get("status") != "success"]
    if not rows:
        return f"{field:g}deg: no sampled ray failures"
    surfaces = sorted({str(row.get("failed_surface") or "unknown") for row in rows})
    pupils = "; ".join(f"({_fmt(row.get('px'))},{_fmt(row.get('py'))})@S{row.get('failed_surface')}" for row in rows)
    return f"{field:g}deg: failures={len(rows)}, surfaces={', '.join(surfaces)}, pupils={pupils}"


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    detail_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> None:
    failed = [row for row in detail_rows if row.get("status") == "failed"]
    success_warn = [row for row in detail_rows if row.get("status") == "success_with_wrapper_warning"]
    top = summary_rows[:5]
    high_fields = [49.0, 63.0, 70.0]
    same_surface_63_70 = "unknown"
    for field in (63.0, 70.0):
        surfaces = {
            row.get("failed_surface")
            for row in failed
            if _to_float(row.get("field_deg")) == field and row.get("failed_surface") is not None
        }
        if len(surfaces) == 1:
            same_surface_63_70 = f"{field:g}deg all failures near S{next(iter(surfaces))}"
        elif len(surfaces) > 1:
            same_surface_63_70 = f"{field:g}deg failures spread across surfaces {sorted(surfaces)}"
            break

    aperture_like = sum(1 for row in failed if "aperture" in str(row.get("likely_failure_type")))
    intersection_like = sum(1 for row in failed if "intersection" in str(row.get("likely_failure_type")))
    if aperture_like > intersection_like:
        failure_style = "More consistent with clear aperture / vignetting."
    elif intersection_like > aperture_like:
        failure_style = "More consistent with ray-surface intersection failure."
    elif failed:
        failure_style = "Failure type is mixed or ambiguous; inspect raw trace files."
    else:
        failure_style = "No sampled failures."

    lines = [
        "Ray Failure Surface Diagnostic",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        "",
        "[field_table]",
        ", ".join(f"#{row.get('number')}={_fmt(row.get('y'))}deg" for row in fields) if fields else "unknown",
        "",
        "[summary]",
        f"total_rays: {len(detail_rows)}",
        f"failed_rays: {len(failed)}",
        f"success_with_wrapper_warning: {len(success_warn)}",
        f"primary_failure_style: {failure_style}",
        "",
        "[top_failed_surfaces]",
    ]
    if top:
        for row in top:
            lines.append(
                "  "
                f"S{row.get('surface_number')}: failures={row.get('failure_count')}, "
                f"comment={row.get('comment')}, glass={row.get('glass')}, "
                f"semi_diameter={_fmt(row.get('semi_diameter'))}, "
                f"watch={row.get('watch_note')}, fields={row.get('fields')}"
            )
    else:
        lines.append("  none")

    lines.extend(["", "[high_field_breakdown]"])
    for field in high_fields:
        lines.append("  " + _report_field_failures(detail_rows, field))
    lines.append(f"63_70_consistency: {same_surface_63_70}")

    lines.extend(["", "[watched_locations]"])
    for surface in (2, 3, 6, 7, 8):
        matches = [row for row in summary_rows if row.get("surface_number") == surface]
        if matches:
            row = matches[0]
            lines.append(f"  S{surface}: failures={row.get('failure_count')} ({row.get('watch_note')})")
        else:
            lines.append(f"  S{surface}: no sampled failures ({WATCH_SURFACES.get(surface, '')})")
    stop_matches = [row for row in summary_rows if str(row.get("is_stop")).lower() == "true"]
    lines.append(
        "  STOP: "
        + (
            "; ".join(f"S{row.get('surface_number')} failures={row.get('failure_count')}" for row in stop_matches)
            if stop_matches
            else "no sampled failures at stop surface"
        )
    )

    lines.extend(
        [
            "",
            "[interpretation]",
            "49deg: " + _report_field_failures(detail_rows, 49.0),
            "63deg: " + _report_field_failures(detail_rows, 63.0),
            "70deg: " + _report_field_failures(detail_rows, 70.0),
            failure_style,
            "If failures concentrate on clamp surfaces S2/S3 or S7/S8, the clear aperture clamps are likely clipping required rays.",
            "If failures occur before/near STOP or at multiple early surfaces, ray aiming / entrance pupil setup should be checked before changing geometry.",
            "",
            "[files]",
            f"ray_failure_surface_summary: {path.parent / 'ray_failure_surface_summary.csv'}",
            f"ray_failure_detail: {path.parent / 'ray_failure_detail.csv'}",
            f"ray_failure_surface_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_ray_failure_surfaces(lens_path: str) -> None:
    lens = Path(lens_path)
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "ray_failure_surfaces" / run_id
    raw_dir = out_dir / "raw_single_ray_traces"
    raw_dir.mkdir(parents=True, exist_ok=True)

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

    print("Loading lens read-only...", flush=True)
    oss.load(lens, saveifneeded=False)
    lde = oss.LDE
    image_surface = int(lde.NumberOfSurfaces) - 1
    surfaces = _surface_table(oss)
    fields = _field_table(oss)
    field_numbers = {field: _field_number(fields, field) for field in FIELDS_DEG}

    detail_rows: list[dict[str, Any]] = []
    for field in FIELDS_DEG:
        field_number = field_numbers[field]
        print(f"Tracing field {field:g} deg", flush=True)
        for px, py in PUPIL_SAMPLES:
            if field_number is None:
                row = {
                    "field_deg": field,
                    "field_number": None,
                    "px": px,
                    "py": py,
                    "status": "failed",
                    "failed_surface": None,
                    "reported_failed_surface": None,
                    "last_success_surface": None,
                    "last_success_x": None,
                    "last_success_y": None,
                    "failure_reason": "Requested field is not present in current lens field table.",
                    "raw_trace_file": None,
                }
                text = ""
            else:
                raw_path = raw_dir / f"field_{_field_key(field)}_{_pupil_key(px, py)}.txt"
                row, text = _trace_one(
                    oss,
                    field_number=field_number,
                    field_deg=field,
                    px=px,
                    py=py,
                    image_surface=image_surface,
                    raw_path=raw_path,
                )
            failed_surface = row.get("failed_surface")
            info = surfaces.get(int(failed_surface), {}) if failed_surface is not None else {}
            row["failed_surface_comment"] = info.get("comment")
            row["failed_surface_glass"] = info.get("glass")
            row["failed_surface_watch_note"] = info.get("watch_note")
            row["likely_failure_type"] = _likely_failure_type(text or str(row.get("failure_reason")), failed_surface, info)
            detail_rows.append(row)

    summary_rows = _summarize_failures(detail_rows, surfaces)
    detail_path = out_dir / "ray_failure_detail.csv"
    summary_path = out_dir / "ray_failure_surface_summary.csv"
    report_path = out_dir / "ray_failure_surface_report.txt"
    _write_detail(detail_path, detail_rows)
    _write_summary(summary_path, summary_rows)
    _write_report(report_path, lens=lens, run_id=run_id, detail_rows=detail_rows, summary_rows=summary_rows, fields=fields)
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "lens": str(lens),
                "image_surface": image_surface,
                "fields": list(FIELDS_DEG),
                "pupil_samples": list(PUPIL_SAMPLES),
                "output_folder": str(out_dir),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    close_all_analysis_windows(oss)

    print(f"ray_failure_surface_summary: {summary_path}", flush=True)
    print(f"ray_failure_detail: {detail_path}", flush=True)
    print(f"ray_failure_surface_report: {report_path}", flush=True)
    for row in summary_rows[:5]:
        print(
            f"S{row.get('surface_number')}: failures={row.get('failure_count')}, "
            f"comment={row.get('comment')}, fields={row.get('fields')}",
            flush=True,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only diagnostic for locating ray trace failure surfaces.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script does not save or modify it.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_ray_failure_surfaces(args.lens)
