from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "run_id",
    "current_lens_file",
    "surface_number",
    "surface_index",
    "comment",
    "radius",
    "thickness",
    "glass",
    "material",
    "semi_diameter",
    "conic",
    "is_stop",
    "is_image",
    "is_before_image",
]


def safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, attr)
    except Exception:
        return default

    try:
        if callable(value):
            value = value()
    except Exception:
        return default

    return value


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def collect_surfaces(oss: Any, run_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Read basic LDE surface data without failing on individual fields."""
    lde = oss.LDE
    number_of_surfaces = lde.NumberOfSurfaces
    stop_surface = safe_get(lde, "StopSurface")
    image_surface = number_of_surfaces - 1
    last_surface_before_image = image_surface - 1
    run_id = (run_metadata or {}).get("run_id")
    current_lens_file = (run_metadata or {}).get("current_lens_file")

    rows: list[dict[str, Any]] = []

    for i in range(number_of_surfaces):
        try:
            surface = lde.GetSurfaceAt(i)
        except Exception:
            rows.append(
                {field: None for field in FIELDNAMES}
                | {
                    "surface_number": i,
                    "surface_index": i,
                    "run_id": run_id,
                    "current_lens_file": current_lens_file,
                    "is_stop": i == stop_surface,
                    "is_image": i == image_surface,
                    "is_before_image": i == last_surface_before_image,
                }
            )
            continue

        material = safe_get(surface, "Material")
        rows.append(
            {
                "surface_number": i,
                "surface_index": i,
                "run_id": run_id,
                "current_lens_file": current_lens_file,
                "comment": safe_get(surface, "Comment"),
                "radius": safe_get(surface, "Radius"),
                "thickness": safe_get(surface, "Thickness"),
                "glass": material,
                "material": material,
                "semi_diameter": safe_get(surface, "SemiDiameter"),
                "conic": safe_get(surface, "Conic"),
                "is_stop": i == stop_surface,
                "is_image": i == image_surface,
                "is_before_image": i == last_surface_before_image,
            }
        )

    return rows


def export_surfaces(
    oss: Any,
    output_path: Path,
    run_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = collect_surfaces(oss, run_metadata=run_metadata)

    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return rows
