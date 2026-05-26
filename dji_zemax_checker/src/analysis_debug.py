from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from export_surfaces import json_safe
from run_files import run_file


def update_analysis_debug(run_dir: Path, run_id: str | None, updates: dict[str, Any]) -> None:
    if not run_id:
        return

    path = run_file(run_dir, run_id, "analysis_debug")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}

    data.update({key: json_safe(value) for key, value in updates.items()})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
