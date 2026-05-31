from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path(r"C:\ZemaxAuto\dji_zemax_checker")
IN_CSV = ROOT / "allowed_materials_from_DJI_library.csv"
OUT_DIR = ROOT / "results" / "material_mapping"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_ALL = OUT_DIR / "us20170293107a1_to_official_materials_top_candidates.csv"
OUT_BEST = OUT_DIR / "us20170293107a1_to_official_materials_best.csv"


TARGETS = [
    {"target_name": "L1_L2_L7_target", "target_n": 1.531, "target_v": 55.754},
    {"target_name": "L3_target",       "target_n": 1.636, "target_v": 23.972},
    {"target_name": "L4_target",       "target_n": 1.847, "target_v": 23.778},
    {"target_name": "L5_target",       "target_n": 1.923, "target_v": 18.897},
    {"target_name": "L6_target",       "target_n": 1.697, "target_v": 55.532},
    {"target_name": "Filter_target",   "target_n": 1.517, "target_v": 64.167},
]


def norm(s: str) -> str:
    return s.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def pick_col(fieldnames: list[str], candidates: list[str]) -> str | None:
    lookup = {norm(c): c for c in fieldnames}
    for cand in candidates:
        key = norm(cand)
        if key in lookup:
            return lookup[key]
    return None


def to_float(x):
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    if not IN_CSV.exists():
        raise FileNotFoundError(f"Missing official material CSV: {IN_CSV}")

    with IN_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        raise RuntimeError(f"No rows found in {IN_CSV}")

    print("Detected columns:")
    for c in fieldnames:
        print(f"  - {c}")

    catalog_col = pick_col(fieldnames, ["catalog", "catalogue", "cat", "library", "source"])
    material_col = pick_col(fieldnames, ["material", "glass", "name", "glassname", "materialname"])
    n_col = pick_col(fieldnames, ["nd", "n_d", "n", "refractiveindex", "index"])
    v_col = pick_col(fieldnames, ["vd", "v_d", "abbe", "abbenumber", "v"])

    if material_col is None or n_col is None or v_col is None:
        raise RuntimeError(
            "Cannot identify required columns. "
            f"material_col={material_col}, n_col={n_col}, v_col={v_col}. "
            "Please inspect allowed_materials_from_DJI_library.csv."
        )

    usable = []
    for r in rows:
        n = to_float(r.get(n_col))
        v = to_float(r.get(v_col))
        mat = str(r.get(material_col, "")).strip()
        if n is None or v is None or not mat:
            continue
        usable.append({
            "catalog": str(r.get(catalog_col, "")).strip() if catalog_col else "",
            "material": mat,
            "material_n": n,
            "material_v": v,
            "raw": r,
        })

    print(f"\nUsable official materials: {len(usable)}")

    if not usable:
        raise RuntimeError("No usable material rows with n/V found.")

    all_records = []
    best_records = []

    for t in TARGETS:
        candidates = []
        for m in usable:
            dn = m["material_n"] - t["target_n"]
            dv = m["material_v"] - t["target_v"]

            # n is more critical than V for first-order power.
            # V is still important for color correction.
            score = abs(dn) / 0.03 + abs(dv) / 10.0

            rec = {
                "target_name": t["target_name"],
                "target_n": t["target_n"],
                "target_v": t["target_v"],
                "catalog": m["catalog"],
                "material": m["material"],
                "material_n": m["material_n"],
                "material_v": m["material_v"],
                "delta_n": dn,
                "delta_v": dv,
                "score": score,
            }
            candidates.append(rec)

        candidates.sort(key=lambda x: x["score"])
        top = candidates[:10]
        all_records.extend(top)
        best_records.append(top[0])

    fieldnames_out = [
        "target_name", "target_n", "target_v",
        "catalog", "material", "material_n", "material_v",
        "delta_n", "delta_v", "score",
    ]

    with OUT_ALL.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames_out)
        w.writeheader()
        w.writerows(all_records)

    with OUT_BEST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames_out)
        w.writeheader()
        w.writerows(best_records)

    print("\nBest official material mapping:")
    for r in best_records:
        cat = f"{r['catalog']}:" if r["catalog"] else ""
        print(
            f"{r['target_name']:18s} -> {cat}{r['material']:20s} "
            f"n={r['material_n']:.6f}, V={r['material_v']:.3f}, "
            f"dn={r['delta_n']:+.6f}, dV={r['delta_v']:+.3f}, score={r['score']:.3f}"
        )

    print(f"\nSaved top candidates: {OUT_ALL}")
    print(f"Saved best mapping:    {OUT_BEST}")


if __name__ == "__main__":
    main()
