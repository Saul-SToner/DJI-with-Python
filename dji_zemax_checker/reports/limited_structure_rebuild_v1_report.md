# Limited Structure Rebuild v1

## Purpose

This stage moves from the complete CN114 prescription toward a limited reconstruction of its structural roles. It tests whether bounded front-group scale, rear-relay scale, STOP-to-rear spacing, rear spacing, and image refocus can jointly improve BFL, trace field, and image scale.

CN114 Emb1 V2 nearest is the only baseline. No new donor, material remapping, global optimizer, or broad surface search was used.

## Staged Targets

An immediate 8 mm image-height requirement would hide useful intermediate structure behavior. The v1 success gate was therefore:

- Gate A: BFL >= 2.3 mm;
- Gate B: maximum full-pass field >= 60 degrees;
- Gate C: 70-degree chief image height >= 3.0 mm.

Image height >= 4.0 mm was reserved as strong progress. Gates E/F at 6 mm and approximately 8 mm remain later structural targets.

## Variable Design

Forty-eight deterministic fresh-load variants were evaluated:

- 32 coupled front/rear group scale and STOP branches;
- 12 rear-relay radius/magnification branches;
- 4 image-refocus controls.

All branches used a bounded L5-L6 spacing reduction and controlled image-plane shift derived from v0.3. Group scaling changed linear dimensions while leaving asphere coefficients unchanged; it is a limited structural perturbation, not a strict similarity transform.

## Gate Summary

| Population | Count |
|---|---:|
| Total variants | 48 |
| Hard-geometry PASS | 10 |
| Geometry-valid Gate A PASS | 9 |
| Geometry-valid Gate B PASS | 6 |
| Geometry-valid Gate A+B PASS | 5 |
| Geometry-valid Gate C PASS | 0 |
| Geometry-valid Gate A+B+C PASS | 0 |
| Geometry-valid image height >= 4 mm | 0 |

Raw trace-only improvements in geometry-failed scaled branches are not accepted as progress.

## Top Geometry-Valid Variants

| Variant | Front scale | Rear scale | Image delta (mm) | TTL (mm) | BFL (mm) | Chief IH70 (mm) | Max full-pass | Gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `FOCUS_048` | 1.00 | 1.00 | +0.60 | 16.495 | 2.523 | 2.250 | 60 deg | A+B |
| `FOCUS_047` | 1.00 | 1.00 | +0.50 | 16.395 | 2.423 | 2.223 | 60 deg | A+B |
| `GRID_022` | 1.00 | 1.00 | +0.40 | 16.295 | 2.323 | 2.195 | 60 deg | A+B |
| `GRID_021` | 1.00 | 1.00 | +0.40 | 16.295 | 2.323 | 2.195 | 60 deg | A+B |
| `FOCUS_046` | 1.00 | 1.00 | +0.40 | 16.295 | 2.323 | 2.195 | 60 deg | A+B |

`FOCUS_048` is the strongest accepted diagnostic endpoint, but it is not a candidate lens or checkpoint.

## Findings

### BFL

BFL is recoverable inside the TTL budget. Nine geometry-valid variants exceed 2.3 mm, and the best accepted branch reaches 2.523 mm at TTL 16.495 mm. BFL is not the dominant remaining feasibility blocker.

### High-Field Trace

Six geometry-valid variants achieve a 60-degree full-pass boundary. Five of them also satisfy BFL. Controlled STOP/rear spacing plus refocus preserves the v0.3 field improvement.

Branches reporting 70-degree trace generally fail the hard geometry gate and are rejected. Trace cannot override physical invalidity.

### Image Height

No variant reaches 3.0 mm. The best geometry-valid A+B branch reaches only 2.250 mm. Some rear-scale branches raise image height to about 2.45 mm but lose all full-pass fields or fail geometry.

This confirms that projection scale cannot be recovered by refocus or simple group scaling around the CN114 prescription. A new projection-power allocation is required.

### Failure Attribution

- **BFL limited:** substantially resolved in valid refocus branches.
- **Image-height limited:** dominant blocker; all variants fail Gate C.
- **High-field trace limited:** improved to 60 degrees, but 70-degree recovery is not geometry-valid.
- **Geometry limited:** 38 of 48 scaled variants fail the hard gate, especially aggressive group-scale branches.
- **Metric conflict:** EFL remains projection-model dependent; image height and trace are used directly instead.

## Decision

The v1 joint success gate is not met because Gate C remains unsolved. Continuing to squeeze the full CN114 prescription is not recommended.

A v2 study is justified only as a new DJI-envelope projection rebuild template. It should preserve the role sequence but reallocate power and conjugates explicitly:

`front admission -> stop handoff -> rear magnification relay -> BFL/field group`

The v2 search should start from geometry-presolved group envelopes and target image height as an independent structural variable. It should not treat `FOCUS_048` as an optimization seed merely because A+B pass.

## Boundary Statement

- This stage did not complete a DJI lens design.
- It did not produce a final usable optical system.
- No large-scale optimization was executed.
- No `.ZOS` or `.ZMX` file is added to Git.
- Existing v0.1, v0.2, and v0.3 conclusions are unchanged.
- Conclusions are limited to limited structure rebuild v1.
