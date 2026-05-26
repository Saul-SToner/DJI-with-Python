from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from export_surfaces import json_safe


MIN_CENTER_THICKNESS = 0.5
MIN_EDGE_THICKNESS = 0.2
MIN_ABS_RADIUS = 5.0


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sag(radius: float | None, semi_diameter: float | None, conic: float | None = 0.0) -> float | None:
    if radius is None or semi_diameter is None:
        return None
    if abs(radius) < 1e-12:
        return None

    curvature = 1.0 / radius
    k = conic or 0.0
    radicand = 1.0 - (1.0 + k) * (curvature**2) * (semi_diameter**2)
    if radicand < 0:
        return None

    denominator = 1.0 + math.sqrt(radicand)
    if abs(denominator) < 1e-12:
        return None

    return curvature * semi_diameter**2 / denominator


def _edge_thickness(front: dict[str, Any], back: dict[str, Any], semi_diameter: float) -> float | None:
    center_thickness = _to_float(front.get("thickness"))
    front_sag = _sag(
        _to_float(front.get("radius")),
        semi_diameter,
        _to_float(front.get("conic")),
    )
    back_sag = _sag(
        _to_float(back.get("radius")),
        semi_diameter,
        _to_float(back.get("conic")),
    )

    if center_thickness is None or front_sag is None or back_sag is None:
        return None

    return center_thickness + back_sag - front_sag


def _find_lens_surfaces(surfaces: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [row for row in surfaces if str(row.get("comment") or "").strip().upper() == label.upper()]


def _status(findings: list[dict[str, str]]) -> str:
    if any(item["level"] == "fail" for item in findings):
        return "fail"
    if any(item["level"] == "warning" for item in findings):
        return "warning"
    return "pass"


def _build_l5_check(surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    l5_surfaces = _find_lens_surfaces(surfaces, "L5")

    if len(l5_surfaces) < 2:
        return {
            "status": "fail",
            "findings": [{"level": "fail", "message": "Could not find two L5 surfaces by comment."}],
            "surfaces": [json_safe(row.get("surface_index")) for row in l5_surfaces],
        }

    front, back = l5_surfaces[0], l5_surfaces[1]
    center_thickness = _to_float(front.get("thickness"))
    front_sd = _to_float(front.get("semi_diameter"))
    back_sd = _to_float(back.get("semi_diameter"))
    common_sd = min(front_sd, back_sd) if front_sd is not None and back_sd is not None else None
    front_radius = _to_float(front.get("radius"))
    back_radius = _to_float(back.get("radius"))
    radii = [abs(r) for r in [front_radius, back_radius] if r is not None]
    minimum_abs_radius = min(radii) if radii else None
    edge_thickness = _edge_thickness(front, back, common_sd) if common_sd is not None else None

    if center_thickness is None:
        findings.append({"level": "fail", "message": "L5 center thickness could not be read."})
    elif center_thickness < MIN_CENTER_THICKNESS:
        findings.append(
            {
                "level": "fail",
                "message": f"L5 center thickness {center_thickness:.6g} is below {MIN_CENTER_THICKNESS:.6g}.",
            }
        )

    if edge_thickness is None:
        findings.append({"level": "warning", "message": "L5 edge thickness could not be calculated."})
    elif edge_thickness < MIN_EDGE_THICKNESS:
        findings.append(
            {
                "level": "fail",
                "message": f"L5 edge thickness {edge_thickness:.6g} is below {MIN_EDGE_THICKNESS:.6g}.",
            }
        )

    if minimum_abs_radius is None:
        findings.append({"level": "warning", "message": "L5 minimum radius could not be calculated."})
    elif minimum_abs_radius < MIN_ABS_RADIUS:
        findings.append(
            {
                "level": "warning",
                "message": f"L5 minimum absolute radius {minimum_abs_radius:.6g} is below {MIN_ABS_RADIUS:.6g}.",
            }
        )

    if edge_thickness is not None and edge_thickness < MIN_EDGE_THICKNESS:
        findings.append({"level": "warning", "message": "L5 has edge thinning risk."})

    return {
        "status": _status(findings),
        "surfaces": [json_safe(front.get("surface_index")), json_safe(back.get("surface_index"))],
        "center_thickness": json_safe(center_thickness),
        "front_radius": json_safe(front_radius),
        "back_radius": json_safe(back_radius),
        "front_semi_diameter": json_safe(front_sd),
        "back_semi_diameter": json_safe(back_sd),
        "common_semi_diameter": json_safe(common_sd),
        "edge_thickness_at_common_semi_diameter": json_safe(edge_thickness),
        "minimum_abs_radius": json_safe(minimum_abs_radius),
        "thresholds": {
            "min_center_thickness": MIN_CENTER_THICKNESS,
            "min_edge_thickness": MIN_EDGE_THICKNESS,
            "min_abs_radius": MIN_ABS_RADIUS,
        },
        "findings": findings,
    }


def _build_global_checks(surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    finite_radii = [
        {
            "surface_index": row.get("surface_index"),
            "comment": row.get("comment"),
            "radius": _to_float(row.get("radius")),
        }
        for row in surfaces
        if _to_float(row.get("radius")) is not None
    ]
    min_radius = min(finite_radii, key=lambda item: abs(item["radius"])) if finite_radii else None

    return {
        "minimum_abs_radius_surface": None
        if min_radius is None
        else {
            "surface_index": json_safe(min_radius["surface_index"]),
            "comment": json_safe(min_radius["comment"]),
            "radius": json_safe(min_radius["radius"]),
            "abs_radius": json_safe(abs(min_radius["radius"])),
        },
    }


def build_manufacturing_check(
    surfaces: list[dict[str, Any]],
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    l5_check = _build_l5_check(surfaces)
    status = l5_check["status"]

    return {
        "run_id": None if run_metadata is None else run_metadata.get("run_id"),
        "current_lens_file": None if run_metadata is None else run_metadata.get("current_lens_file"),
        "run_metadata": run_metadata or {},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "checks": {
            "l5": l5_check,
            "global": _build_global_checks(surfaces),
        },
    }


def export_manufacturing_check(
    surfaces: list[dict[str, Any]],
    output_path: Path,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = build_manufacturing_check(surfaces, run_metadata=run_metadata)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
