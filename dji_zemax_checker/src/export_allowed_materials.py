from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any


FIELDNAMES = ["material_name", "catalog_name", "nd", "vd", "density", "comment"]


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "gbk", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeError:
            continue
        if text.count("\x00") < max(1, len(text) // 20):
            return text
    return path.read_text(encoding="utf-8", errors="replace")


def parse_agf(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    catalog_name = path.stem

    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        tag = parts[0].upper()

        if tag == "NM":
            if current is not None:
                rows.append(current)

            current = {
                "material_name": parts[1] if len(parts) > 1 else None,
                "catalog_name": catalog_name,
                "nd": _to_float(parts[4] if len(parts) > 4 else None),
                "vd": _to_float(parts[5] if len(parts) > 5 else None),
                "density": None,
                "comment": "",
            }
        elif tag == "GC" and current is not None:
            current["comment"] = line[2:].strip()
        elif tag == "ED" and current is not None:
            # In Zemax AGF, ED often includes density as the third numeric value.
            current["density"] = _to_float(parts[3] if len(parts) > 3 else None)

    if current is not None:
        rows.append(current)

    return rows


def _catalog_paths(catalog_path: Path, catalog_name: str | None) -> list[Path]:
    if catalog_path.is_file():
        return [catalog_path]

    if not catalog_path.is_dir():
        raise FileNotFoundError(f"Catalog path not found: {catalog_path}")

    if catalog_name:
        matches = [
            path
            for path in catalog_path.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".agf"
            and path.stem.lower() == catalog_name.lower()
        ]
        if not matches:
            raise FileNotFoundError(f"Catalog {catalog_name!r} not found under {catalog_path}")
        return matches

    matches = sorted(path for path in catalog_path.iterdir() if path.is_file() and path.suffix.lower() == ".agf")
    if len(matches) > 1:
        names = ", ".join(path.stem for path in matches)
        raise ValueError(
            "Multiple AGF catalogs found. Specify --catalog-name or pass one .AGF file with --catalog-path. "
            f"Found: {names}"
        )
    if not matches:
        raise FileNotFoundError(f"No .AGF catalogs found under {catalog_path}")
    return matches


def export_allowed_materials(catalog_path: Path, output_path: Path, catalog_name: str | None = None) -> list[dict[str, Any]]:
    paths = _catalog_paths(catalog_path, catalog_name)
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(parse_agf(path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export allowed materials from a DJI competition AGF catalog.")
    parser.add_argument("--catalog-path", required=True, type=Path, help="Path to one .AGF file or a catalog folder.")
    parser.add_argument("--catalog-name", help="Required when --catalog-path is a folder containing multiple AGF files.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all AGF files under --catalog-path. Use only when the folder itself is the allowed library.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("allowed_materials_from_DJI_library.csv"),
        help="Output CSV path.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.all and args.catalog_path.is_dir():
        rows = []
        for path in sorted(args.catalog_path.iterdir()):
            if path.is_file() and path.suffix.lower() == ".agf":
                rows.extend(parse_agf(path))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
    else:
        rows = export_allowed_materials(args.catalog_path, args.output, catalog_name=args.catalog_name)
    print(f"Exported {len(rows)} materials to {args.output}", flush=True)
