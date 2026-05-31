from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
ALLOWED_CSV = ROOT / "allowed_materials_from_DJI_library.csv"
OUT_DIR = ROOT / "results" / "material_mapping" / "cn117471661b_emb2"

TOP_CANDIDATES_CSV = OUT_DIR / "cn117_material_top_candidates.csv"
BEST_MAPPING_CSV = OUT_DIR / "cn117_material_best_mapping.csv"
REPORT_TXT = OUT_DIR / "cn117_material_mapping_report.txt"


TARGETS: list[dict[str, Any]] = [
    {
        "target_name": "CN117_L1_high_index",
        "surfaces": "S1",
        "target_n": 1.95,
        "target_v": 32.32,
    },
    {
        "target_name": "CN117_mid_crown",
        "surfaces": "S3|S9|S12|S15",
        "target_n": 1.54,
        "target_v": 55.71,
    },
    {
        "target_name": "CN117_high_dispersion",
        "surfaces": "S5|S13",
        "target_n": 1.66,
        "target_v": 20.37,
    },
    {
        "target_name": "CN117_flint",
        "surfaces": "S7",
        "target_n": 1.85,
        "target_v": 23.78,
    },
    {
        "target_name": "CN117_filter",
        "surfaces": "S17",
        "target_n": 1.52,
        "target_v": 64.20,
    },
]


OUTPUT_FIELDNAMES = [
    "target_name",
    "surfaces",
    "target_n",
    "target_v",
    "catalog",
    "material",
    "material_n",
    "material_v",
    "delta_n",
    "delta_v",
    "density",
    "score",
]


def _norm(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _pick_col(fieldnames: list[str], candidates: list[str]) -> str | None:
    lookup = {_norm(name): name for name in fieldnames}
    for candidate in candidates:
        key = _norm(candidate)
        if key in lookup:
            return lookup[key]
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _fmt(value: Any, digits: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "unknown"
    return f"{number:.{digits}g}"


def _load_allowed_materials(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Allowed materials CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        raise RuntimeError(f"No rows found in allowed materials CSV: {path}")

    material_col = _pick_col(
        fieldnames,
        [
            "material_name",
            "material",
            "glass",
            "glass_name",
            "glassname",
            "name",
        ],
    )
    catalog_col = _pick_col(
        fieldnames,
        [
            "catalog_name",
            "catalog",
            "catalogue",
            "library",
            "source",
            "cat",
        ],
    )
    nd_col = _pick_col(fieldnames, ["nd", "n_d", "n", "refractive_index", "refractiveindex", "index"])
    vd_col = _pick_col(fieldnames, ["vd", "v_d", "abbe", "abbe_number", "abbenumber", "v"])
    density_col = _pick_col(fieldnames, ["density", "rho", "specific_gravity", "specificgravity"])

    if material_col is None or nd_col is None or vd_col is None:
        raise RuntimeError(
            "Cannot identify required material columns. "
            f"material_col={material_col}, nd_col={nd_col}, vd_col={vd_col}, "
            f"available={fieldnames}"
        )

    materials: list[dict[str, Any]] = []
    for row in rows:
        material = str(row.get(material_col, "")).strip()
        nd = _to_float(row.get(nd_col))
        vd = _to_float(row.get(vd_col))
        if not material or nd is None or vd is None:
            continue
        materials.append(
            {
                "material": material,
                "catalog": str(row.get(catalog_col, "")).strip() if catalog_col else "",
                "material_n": nd,
                "material_v": vd,
                "density": _to_float(row.get(density_col)) if density_col else None,
            }
        )

    if not materials:
        raise RuntimeError(f"No usable rows with material name, nd and Vd found in {path}")

    return materials


def _score(material_n: float, material_v: float, target_n: float, target_v: float) -> float:
    return abs(material_n - target_n) / 0.03 + abs(material_v - target_v) / 10.0


def _risk_label(delta_n: float, delta_v: float, score: float) -> str:
    abs_dn = abs(delta_n)
    abs_dv = abs(delta_v)
    if abs_dn > 0.03 or abs_dv > 10.0 or score > 2.0:
        return "high_risk"
    if abs_dn > 0.015 or abs_dv > 5.0 or score > 1.0:
        return "moderate_risk"
    return "low_risk"


def _candidate_record(target: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
    target_n = float(target["target_n"])
    target_v = float(target["target_v"])
    material_n = float(material["material_n"])
    material_v = float(material["material_v"])
    delta_n = material_n - target_n
    delta_v = material_v - target_v
    score = _score(material_n, material_v, target_n, target_v)
    return {
        "target_name": target["target_name"],
        "surfaces": target["surfaces"],
        "target_n": target_n,
        "target_v": target_v,
        "catalog": material["catalog"],
        "material": material["material"],
        "material_n": material_n,
        "material_v": material_v,
        "delta_n": delta_n,
        "delta_v": delta_v,
        "density": material.get("density"),
        "score": score,
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)


def _write_report(
    path: Path,
    allowed_count: int,
    top_records: list[dict[str, Any]],
    best_records: list[dict[str, Any]],
) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in top_records:
        grouped.setdefault(str(record["target_name"]), []).append(record)

    lines: list[str] = [
        "CN117471661B Embodiment 2 Material Mapping Report",
        "",
        f"allowed_materials_csv: {ALLOWED_CSV}",
        f"usable_allowed_material_count: {allowed_count}",
        f"top_candidates_csv: {TOP_CANDIDATES_CSV}",
        f"best_mapping_csv: {BEST_MAPPING_CSV}",
        "",
        "Scoring",
        "score = abs(n - target_n)/0.03 + abs(Vd - target_v)/10",
        "Density is reported but not included in this first-pass score.",
        "",
        "Best Mapping",
    ]

    needs_review: list[str] = []
    for record in best_records:
        risk = _risk_label(float(record["delta_n"]), float(record["delta_v"]), float(record["score"]))
        if risk != "low_risk":
            needs_review.append(str(record["target_name"]))
        lines.extend(
            [
                "",
                f"target_name: {record['target_name']}",
                f"surfaces: {record['surfaces']}",
                f"target_n / target_Vd: {_fmt(record['target_n'])} / {_fmt(record['target_v'])}",
                f"best_material: {record['catalog']}:{record['material']}",
                f"material_n / material_Vd: {_fmt(record['material_n'])} / {_fmt(record['material_v'])}",
                f"delta_n: {_fmt(record['delta_n'])}",
                f"delta_Vd: {_fmt(record['delta_v'])}",
                f"density: {_fmt(record['density'])}",
                f"score: {_fmt(record['score'])}",
                f"risk: {risk}",
            ]
        )

        top = grouped.get(str(record["target_name"]), [])[:5]
        lines.append("top_5_candidates:")
        for index, candidate in enumerate(top, start=1):
            lines.append(
                "  "
                f"{index}. {candidate['catalog']}:{candidate['material']} "
                f"n={_fmt(candidate['material_n'])}, Vd={_fmt(candidate['material_v'])}, "
                f"dn={_fmt(candidate['delta_n'])}, dVd={_fmt(candidate['delta_v'])}, "
                f"density={_fmt(candidate['density'])}, score={_fmt(candidate['score'])}"
            )

    lines.extend(["", "Review Notes"])
    if needs_review:
        lines.append(
            "Targets needing manual review because the nearest official material is not a close optical match: "
            + ", ".join(needs_review)
        )
    else:
        lines.append("All first-pass best matches are low_risk by the current n/Vd thresholds.")

    lines.extend(
        [
            "",
            "Important",
            "This script only creates a material matching table. It does not open, modify, save, optimize, or rescale any Zemax lens.",
            "The selected materials should be verified in OpticStudio after substitution because aberration balance and thickness constraints can shift.",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    materials = _load_allowed_materials(ALLOWED_CSV)

    top_records: list[dict[str, Any]] = []
    best_records: list[dict[str, Any]] = []

    for target in TARGETS:
        candidates = [_candidate_record(target, material) for material in materials]
        candidates.sort(key=lambda row: float(row["score"]))
        top_15 = candidates[:15]
        top_records.extend(top_15)
        best_records.append(top_15[0])

    _write_csv(TOP_CANDIDATES_CSV, top_records)
    _write_csv(BEST_MAPPING_CSV, best_records)
    _write_report(REPORT_TXT, len(materials), top_records, best_records)

    print("CN117 material mapping complete.", flush=True)
    print(f"usable_allowed_material_count: {len(materials)}", flush=True)
    print(f"top_candidates_csv: {TOP_CANDIDATES_CSV}", flush=True)
    print(f"best_mapping_csv: {BEST_MAPPING_CSV}", flush=True)
    print(f"report: {REPORT_TXT}", flush=True)
    print("", flush=True)
    for record in best_records:
        risk = _risk_label(float(record["delta_n"]), float(record["delta_v"]), float(record["score"]))
        print(
            f"{record['target_name']} ({record['surfaces']}) -> "
            f"{record['catalog']}:{record['material']} "
            f"dn={float(record['delta_n']):+.6f}, "
            f"dVd={float(record['delta_v']):+.3f}, "
            f"score={float(record['score']):.3f}, risk={risk}",
            flush=True,
        )


if __name__ == "__main__":
    main()
