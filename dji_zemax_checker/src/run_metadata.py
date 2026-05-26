from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from export_surfaces import json_safe, safe_get


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_run_metadata(
    oss: Any,
    run_id: str,
    export_time: str | None = None,
    output_folder: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lde = safe_get(oss, "LDE")
    system_data = safe_get(oss, "SystemData")
    title_notes = safe_get(system_data, "TitleNotes")
    number_of_surfaces = _to_int(safe_get(lde, "NumberOfSurfaces"))
    image_surface = number_of_surfaces - 1 if number_of_surfaces is not None else None
    last_surface_before_image = image_surface - 1 if image_surface is not None else None

    metadata = {
        "run_id": run_id,
        "export_time": export_time or datetime.now().isoformat(timespec="seconds"),
        "current_lens_file": json_safe(safe_get(oss, "SystemFile")),
        "lens_title": json_safe(safe_get(title_notes, "Title")),
        "system_name": json_safe(safe_get(oss, "SystemName")),
        "mode": json_safe(safe_get(oss, "Mode")),
        "number_of_surfaces": json_safe(number_of_surfaces),
        "stop_surface": json_safe(safe_get(lde, "StopSurface")),
        "image_surface": json_safe(image_surface),
        "last_surface_before_image": json_safe(last_surface_before_image),
        "output_folder": json_safe(str(output_folder)) if output_folder is not None else None,
    }
    if extra:
        metadata.update({key: json_safe(value) for key, value in extra.items()})
    return metadata


def export_run_metadata(
    oss: Any,
    output_path: Path,
    run_id: str,
    export_time: str | None = None,
    output_folder: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = build_run_metadata(oss, run_id, export_time, output_folder=output_folder, extra=extra)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def load_run_metadata(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
