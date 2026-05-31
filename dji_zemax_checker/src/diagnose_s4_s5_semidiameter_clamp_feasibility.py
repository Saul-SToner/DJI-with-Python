from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import zospy as zp

from diagnose_ray_failure_surfaces import (
    FIELDS_DEG,
    PUPIL_SAMPLES,
    _field_number,
    _field_table,
    _fmt,
    _parse_trace_rows,
    _pupil_key,
    _read_text_file,
    _safe_get,
    _to_float,
    _trace_one,
)
from zosapi_cleanup import close_all_analysis_windows


PROJECT_ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
SURFACE_A = 4
SURFACE_B = 5
SAFETY_OFFSETS = (0.03, 0.05, 0.08, 0.10)
EVEN_TERMS = (4, 6, 8, 10, 12, 14, 16)
SAMPLE_COUNT = 800


@dataclass
class SurfaceData:
    surface_number: int
    radius: float | None
    thickness: float | None
    glass: str
    semi_diameter: float | None
    conic: float | None
    even_terms: dict[int, float | None]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _get_even_term(surface: Any, term: int) -> float | None:
    data = _safe_get(surface, "SurfaceData")
    if data is None:
        return None
    method = _safe_get(data, "GetNthEvenOrderTerm")
    if callable(method):
        try:
            return _to_float(method(term))
        except Exception:
            pass
    cell_method = _safe_get(data, "NthEvenOrderTermCell")
    if callable(cell_method):
        try:
            cell = cell_method(term)
            for attr in ("DoubleValue", "Value"):
                value = _to_float(_safe_get(cell, attr))
                if value is not None:
                    return value
        except Exception:
            pass
    return None


def _read_surface(surface: Any) -> SurfaceData:
    return SurfaceData(
        surface_number=int(_safe_get(surface, "SurfaceNumber", -1)),
        radius=_to_float(_safe_get(surface, "Radius")),
        thickness=_to_float(_safe_get(surface, "Thickness")),
        glass=str(_safe_get(surface, "Material", "") or ""),
        semi_diameter=_to_float(_safe_get(surface, "SemiDiameter")),
        conic=_to_float(_safe_get(surface, "Conic")),
        even_terms={term: _get_even_term(surface, term) for term in EVEN_TERMS},
    )


def _is_plane(radius: float | None) -> bool:
    return radius is None or radius == 0.0 or math.isinf(radius)


def _formula_sag(surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    radius = surface.radius
    conic = surface.conic or 0.0
    if _is_plane(radius):
        base = 0.0
    else:
        assert radius is not None
        c = 1.0 / radius
        sqrt_arg = 1.0 - (1.0 + conic) * c * c * r * r
        if sqrt_arg < 0:
            return None, f"invalid sag sqrt argument {sqrt_arg:g}"
        denom = 1.0 + math.sqrt(sqrt_arg)
        if denom == 0:
            return None, "invalid sag denominator zero"
        base = c * r * r / denom
    asphere = 0.0
    for term, coeff in surface.even_terms.items():
        if coeff is not None:
            asphere += coeff * (r**term)
    return base + asphere, None


def _surface_sag(lde: Any, surface: SurfaceData, r: float) -> tuple[float | None, str | None]:
    try:
        result = lde.GetSag(surface.surface_number, r, 0.0)
        if isinstance(result, tuple) and result and not (isinstance(result[0], bool) and not result[0]):
            for item in result[1:]:
                value = _to_float(item)
                if value is not None:
                    return value, None
    except Exception as exc:
        zemax_warning = f"GetSag failed: {type(exc).__name__}: {exc!r}"
    else:
        zemax_warning = f"GetSag returned no finite sag: {result!r}"
    fallback, fallback_warning = _formula_sag(surface, r)
    if fallback is not None:
        return fallback, f"formula fallback after {zemax_warning}"
    return None, f"{zemax_warning}; {fallback_warning}"


def _min_gap_to_radius(
    lde: Any,
    s4: SurfaceData,
    s5: SurfaceData,
    radius_max: float | None,
) -> tuple[float | None, float | None, str]:
    if radius_max is None:
        return None, None, "radius_max unknown"
    if s4.thickness is None:
        return None, None, "S4 thickness unknown"
    min_gap: float | None = None
    min_radius: float | None = None
    invalid: list[str] = []
    for index in range(SAMPLE_COUNT + 1):
        r = radius_max * index / SAMPLE_COUNT
        sag4, warn4 = _surface_sag(lde, s4, r)
        sag5, warn5 = _surface_sag(lde, s5, r)
        if sag4 is None or sag5 is None:
            invalid.append(f"r={r:g}: S4 {warn4}; S5 {warn5}")
            continue
        gap = s4.thickness + sag5 - sag4
        if min_gap is None or gap < min_gap:
            min_gap = gap
            min_radius = r
    note = f"{len(invalid)} invalid samples; first: {invalid[0]}" if invalid else ""
    return min_gap, min_radius, note


def _current_common_radius(s4: SurfaceData, s5: SurfaceData) -> float | None:
    if s4.semi_diameter is None or s5.semi_diameter is None:
        return None
    return min(s4.semi_diameter, s5.semi_diameter)


def _safe_field_token(field: float) -> str:
    return f"{field:g}".replace(".", "p")


def _trace_s5_footprint(oss: Any, raw_dir: Path, image_surface: int) -> tuple[list[dict[str, Any]], float | None]:
    fields = _field_table(oss)
    field_numbers = {field: _field_number(fields, field) for field in FIELDS_DEG}
    rows: list[dict[str, Any]] = []
    max_radius: float | None = None
    for field in FIELDS_DEG:
        field_number = field_numbers[field]
        for px, py in PUPIL_SAMPLES:
            raw_path = raw_dir / f"field_{_safe_field_token(field)}_{_pupil_key(px, py)}.txt"
            if raw_path.suffix.lower() != ".txt":
                raise RuntimeError(f"Internal error: ray trace raw path does not end with .txt: {raw_path}")
            if field_number is None:
                row = {
                    "field_deg": field,
                    "px": px,
                    "py": py,
                    "status": "failed",
                    "s5_ray_radius": None,
                    "failure_reason": "Requested field is not present in current lens field table.",
                    "raw_trace_file": str(raw_path),
                }
            else:
                trace, _text = _trace_one(
                    oss,
                    field_number=field_number,
                    field_deg=field,
                    px=px,
                    py=py,
                    image_surface=image_surface,
                    raw_path=raw_path,
                )
                points = _parse_trace_rows(_read_text_file(raw_path)) if raw_path.exists() else {}
                s5 = points.get(SURFACE_B)
                radius = None
                if s5 is not None:
                    x = _to_float(s5.get("x"))
                    y = _to_float(s5.get("y"))
                    if x is not None and y is not None:
                        radius = math.hypot(x, y)
                        max_radius = radius if max_radius is None else max(max_radius, radius)
                row = {
                    "field_deg": field,
                    "px": px,
                    "py": py,
                    "status": trace.get("status"),
                    "s5_ray_radius": radius,
                    "failed_surface": trace.get("failed_surface"),
                    "last_success_surface": trace.get("last_success_surface"),
                    "failure_reason": trace.get("failure_reason"),
                    "raw_trace_file": str(raw_path),
                }
            rows.append(row)
    return rows, max_radius


def _candidate_rows(
    lde: Any,
    s4: SurfaceData,
    s5: SurfaceData,
    actual_max: float | None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[str, float | None]] = []
    if actual_max is not None:
        for offset in SAFETY_OFFSETS:
            candidates.append((f"actual_max_plus_{offset:g}".replace(".", "p"), actual_max + offset))
    candidates.append(("current_s5_semi_diameter", s5.semi_diameter))

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for label, candidate in candidates:
        key = "unknown" if candidate is None else f"{candidate:.9g}"
        if key in seen:
            continue
        seen.add(key)
        common_radius = None
        if candidate is not None and s4.semi_diameter is not None:
            common_radius = min(candidate, s4.semi_diameter)
        min_gap, min_radius, note = _min_gap_to_radius(lde, s4, s5, common_radius)
        no_clip = None if actual_max is None or candidate is None else candidate >= actual_max
        no_clip_005 = None if actual_max is None or candidate is None else candidate >= actual_max + 0.05
        rows.append(
            {
                "candidate_label": label,
                "candidate_s5_semi_diameter": candidate,
                "actual_max_ray_radius": actual_max,
                "actual_max_plus_0p03": None if actual_max is None else actual_max + 0.03,
                "actual_max_plus_0p05": None if actual_max is None else actual_max + 0.05,
                "actual_max_plus_0p08": None if actual_max is None else actual_max + 0.08,
                "actual_max_plus_0p10": None if actual_max is None else actual_max + 0.10,
                "current_s4_semi_diameter": s4.semi_diameter,
                "current_s5_semi_diameter": s5.semi_diameter,
                "common_radius_used_for_gap": common_radius,
                "min_gap": min_gap,
                "min_gap_radius": min_radius,
                "does_not_clip_actual_ray_footprint": no_clip,
                "candidate_ge_actual_max_plus_0p05": no_clip_005,
                "gap_ge_0": None if min_gap is None else min_gap >= 0.0,
                "gap_ge_0p05": None if min_gap is None else min_gap >= 0.05,
                "gap_ge_0p10": None if min_gap is None else min_gap >= 0.10,
                "recommended": bool(no_clip_005 and min_gap is not None and min_gap >= 0.05),
                "gap_note": note,
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "candidate_label",
        "candidate_s5_semi_diameter",
        "actual_max_ray_radius",
        "actual_max_plus_0p03",
        "actual_max_plus_0p05",
        "actual_max_plus_0p08",
        "actual_max_plus_0p10",
        "current_s4_semi_diameter",
        "current_s5_semi_diameter",
        "common_radius_used_for_gap",
        "min_gap",
        "min_gap_radius",
        "does_not_clip_actual_ray_footprint",
        "candidate_ge_actual_max_plus_0p05",
        "gap_ge_0",
        "gap_ge_0p05",
        "gap_ge_0p10",
        "recommended",
        "gap_note",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(
    path: Path,
    *,
    lens: Path,
    run_id: str,
    s4: SurfaceData,
    s5: SurfaceData,
    current_gap: float | None,
    current_gap_radius: float | None,
    actual_max: float | None,
    candidate_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
) -> None:
    recommended = [row for row in candidate_rows if row.get("recommended")]
    failures = [row for row in trace_rows if row.get("status") == "failed"]
    lines = [
        "S4/S5 Semi-Diameter Clamp Feasibility Diagnostic",
        "",
        f"run_id: {run_id}",
        f"lens: {lens}",
        "read_only: true",
        "saved_lens: false",
        "optimized: false",
        "",
        "[current_geometry]",
        f"S4 Radius: {_fmt(s4.radius)}",
        f"S4 Thickness: {_fmt(s4.thickness)}",
        f"S4 Glass: {s4.glass!r}",
        f"S4 Semi-Diameter: {_fmt(s4.semi_diameter)}",
        f"S5 Radius: {_fmt(s5.radius)}",
        f"S5 Thickness: {_fmt(s5.thickness)}",
        f"S5 Glass: {s5.glass!r}",
        f"S5 Semi-Diameter: {_fmt(s5.semi_diameter)}",
        f"current S4->S5 min_gap: {_fmt(current_gap)}",
        f"current S4->S5 min_gap_radius: {_fmt(current_gap_radius)}",
        "",
        "[ray_footprint]",
        f"S5 actual max ray radius: {_fmt(actual_max)}",
        f"S5 actual max ray radius + 0.03: {_fmt(None if actual_max is None else actual_max + 0.03)}",
        f"S5 actual max ray radius + 0.05: {_fmt(None if actual_max is None else actual_max + 0.05)}",
        f"S5 actual max ray radius + 0.08: {_fmt(None if actual_max is None else actual_max + 0.08)}",
        f"S5 actual max ray radius + 0.10: {_fmt(None if actual_max is None else actual_max + 0.10)}",
        f"ray trace failed samples: {len(failures)}",
        "",
        "[candidate_clamps]",
    ]
    for row in candidate_rows:
        lines.append(
            "  "
            f"{row['candidate_label']}: S5_SD={_fmt(row.get('candidate_s5_semi_diameter'))}, "
            f"common_r={_fmt(row.get('common_radius_used_for_gap'))}, "
            f"min_gap={_fmt(row.get('min_gap'))}, "
            f"no_clip+0.05={row.get('candidate_ge_actual_max_plus_0p05')}, "
            f"gap>=0.05={row.get('gap_ge_0p05')}, recommended={row.get('recommended')}"
        )

    lines.extend(["", "[conclusion]"])
    if actual_max is None:
        lines.append("UNKNOWN: S5 actual ray footprint could not be obtained from ray trace raw text.")
        lines.append("No feasibility conclusion is made. Fix ray trace/export parsing or inspect raw trace files before deciding clamp vs thickness.")
    elif recommended:
        best = min(recommended, key=lambda row: float(row["candidate_s5_semi_diameter"]))
        lines.append(
            "S5 clamp is feasible by this diagnostic: "
            f"recommended S5 clear semi-diameter ~= {_fmt(best.get('candidate_s5_semi_diameter'))} mm."
        )
        lines.append("This suggests the remaining S4->S5 overlap may be driven mainly by automatic S5 semi-diameter being larger than needed.")
    else:
        lines.append("No tested S5 clamp simultaneously preserves actual ray footprint +0.05 mm and S4->S5 min_gap >= 0.05 mm.")
        lines.append("This suggests clamp alone is insufficient; revisit S4 thickness / S4 curvature / seed priority.")

    if failures:
        lines.append("")
        lines.append("[ray_trace_failures]")
        for row in failures[:20]:
            lines.append(
                "  "
                f"field={_fmt(row.get('field_deg'))}, pupil=({_fmt(row.get('px'))},{_fmt(row.get('py'))}), "
                f"failed_surface={row.get('failed_surface')}, last_success={row.get('last_success_surface')}, "
                f"reason={row.get('failure_reason')}"
            )
        if len(failures) > 20:
            lines.append(f"  ... {len(failures) - 20} more")

    lines.extend(
        [
            "",
            "[files]",
            f"s4_s5_clamp_feasibility_csv: {path.parent / 's4_s5_clamp_feasibility.csv'}",
            f"s4_s5_clamp_feasibility_report: {path}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def diagnose_s4_s5_clamp_feasibility(lens_path: str) -> None:
    lens = Path(lens_path)
    if not lens.exists():
        raise FileNotFoundError(f"Lens not found: {lens}")

    run_id = _run_id()
    out_dir = PROJECT_ROOT / "results" / "s4_s5_clamp_feasibility" / run_id
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
    s4 = _read_surface(lde.GetSurfaceAt(SURFACE_A))
    s5 = _read_surface(lde.GetSurfaceAt(SURFACE_B))
    current_common = _current_common_radius(s4, s5)
    current_gap, current_gap_radius, current_note = _min_gap_to_radius(lde, s4, s5, current_common)
    trace_rows, actual_max = _trace_s5_footprint(oss, raw_dir, image_surface)
    rows = _candidate_rows(lde, s4, s5, actual_max)

    csv_path = out_dir / "s4_s5_clamp_feasibility.csv"
    report_path = out_dir / "s4_s5_clamp_feasibility_report.txt"
    _write_csv(csv_path, rows)
    _write_report(
        report_path,
        lens=lens,
        run_id=run_id,
        s4=s4,
        s5=s5,
        current_gap=current_gap,
        current_gap_radius=current_gap_radius,
        actual_max=actual_max,
        candidate_rows=rows,
        trace_rows=trace_rows,
    )
    (out_dir / "s5_ray_footprint_samples.json").write_text(
        json.dumps(trace_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "lens": str(lens),
                "output_folder": str(out_dir),
                "current_gap_note": current_note,
                "read_only": True,
                "saved_lens": False,
                "optimized": False,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    close_all_analysis_windows(oss)

    print(f"current_min_gap: {_fmt(current_gap)}", flush=True)
    print(f"S5 actual max ray radius: {_fmt(actual_max)}", flush=True)
    print(f"S5 actual max ray radius + 0.03: {_fmt(None if actual_max is None else actual_max + 0.03)}", flush=True)
    print(f"S5 actual max ray radius + 0.05: {_fmt(None if actual_max is None else actual_max + 0.05)}", flush=True)
    print(f"S5 actual max ray radius + 0.08: {_fmt(None if actual_max is None else actual_max + 0.08)}", flush=True)
    print(f"S5 actual max ray radius + 0.10: {_fmt(None if actual_max is None else actual_max + 0.10)}", flush=True)
    recommended = [row for row in rows if row.get("recommended")]
    if actual_max is None:
        print("recommended S5 clamp: UNKNOWN", flush=True)
    elif recommended:
        best = min(recommended, key=lambda row: float(row["candidate_s5_semi_diameter"]))
        print(f"recommended S5 clamp: {_fmt(best['candidate_s5_semi_diameter'])}", flush=True)
    else:
        print("recommended S5 clamp: none", flush=True)
    print(f"csv: {csv_path}", flush=True)
    print(f"report: {report_path}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only S4/S5 S5 clear semi-diameter clamp feasibility diagnostic.")
    parser.add_argument("--lens", required=True, help="Path to lens file. The script does not save or modify it.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    diagnose_s4_s5_clamp_feasibility(args.lens)
