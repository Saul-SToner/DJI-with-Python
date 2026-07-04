# Donor Transfer v0 Summary

## Executive Summary

Donor transfer v0 validated an end-to-end Donor-to-DJI material-transfer pipeline:

`native donor replay -> material vector mapping -> DJI material substitution fresh-load`

The pipeline can produce catalog-material substitutions whose material assignments, saved files, SHA256 identities, and fresh-load traces are independently verifiable. It also produced a decisive negative result: simple material substitution does not preserve wide-field optical performance, even when the donor has a strong native trace or a high material-vector score.

CN106 collapsed after both substitutions. CN114 Emb1 retained more of its native behavior, but its maximum full-pass field fell from 70 to 55 degrees. Therefore, the next technical step is structure-level reconstruction guided by both native replay and material compatibility, not continued direct donor substitution.

## Methodology

### 1. Native Donor Replay

The native replay gate determines whether the published donor prescription is sufficiently complete, physically credible, and trace-reproducible before material migration is considered. This prevents a failed reconstruction from being mislabeled as a material-transfer failure.

Allowed progression:

- `NATIVE_PASS`: replayed geometry and principal trace behavior are credible.
- `NATIVE_PARTIAL`: an image is formed, but high-field or edge-ray behavior is not fully reproduced.
- `NATIVE_TRACE_FAIL`, `NATIVE_GEOMETRY_FAIL`, and `NATIVE_INCOMPLETE`: blocked from substitution.

### 2. Material Vector Mapping

Native materials were represented by refractive index, Abbe number, material type when known, lens power sign, functional role, and position role. Two candidate rules were evaluated:

- nearest `nd/Vd` mapping;
- role-aware mapping using `nd/Vd`, role penalty, and type penalty.

The resulting `material_coverage_score` measures vector compatibility only. It is not an optical-performance probability and cannot override native replay, geometry, TTL, BFL, or image-format constraints.

### 3. DJI Material Substitution Fresh-Load

Selected V2 and V3 variants were written locally, saved, reopened in a fresh session, and checked for material readback, system settings, SHA identity, and standard field/ray trace. No curvature, thickness, spacing, STOP position, image plane, or semi-diameter optimization was used to conceal transfer drift.

## Stage 1: Native Replay

Ten public donors were screened and labeled:

| Native status | Donors |
|---|---|
| `NATIVE_PASS` | CN114 Emb1 |
| `NATIVE_PARTIAL` | US702, US755, US806, CN106 |
| `NATIVE_TRACE_FAIL` | US2020, US909, US2009 |
| `NATIVE_INCOMPLETE` | US863, WO2016 |

Only `NATIVE_PASS` and `NATIVE_PARTIAL` donors entered material-vector analysis. This gate excluded prescriptions whose missing assumptions, invalid geometry, or trace failures would make later material conclusions ambiguous.

## Stage 2: Material Vector Mapping

| Donor | Material coverage score | Native gate context |
|---|---:|---|
| CN114 Emb1 | 0.622803 | only `NATIVE_PASS` donor |
| CN106 | 0.711820 | compact `NATIVE_PARTIAL` donor |
| US702 | 0.454764 | partial trace; missing aperture evidence |
| US755 | 0.516777 | partial trace; native TTL 62.6 mm |
| US806 | 0.921968 | partial low-field trace; TTL 40.01 mm |

US806 is the critical counterexample. It has the highest material score, but its native high-field trace fails and its TTL is far outside the target. It was correctly excluded from substitution validation.

This demonstrates that material coverage must be combined with native replay status and physical/system constraints. A high score alone is not a donor-selection gate.

## Stage 3: Fresh-Load Substitution

| Donor/version | Fresh-load | Max full-pass before | Max full-pass after | Transfer result |
|---|---|---:|---:|---|
| CN106 V2 nearest | PASS | 20 deg | none | `TRANSFER_DRIFT` |
| CN106 V3 role-aware | PASS | 20 deg | none | `TRANSFER_DRIFT` |
| CN114 V2 nearest | PASS | 70 deg | 55 deg | `TRANSFER_DRIFT` |
| CN114 V3 role-aware | PASS | 70 deg | 55 deg | `TRANSFER_DRIFT` |

CN106 is not recommended for continued local optimization. Both mappings caused marginal-ray failures at the lowest fields and eliminated every 7/7 field.

CN114 V2 is the only candidate suitable for a narrowly bounded material-sensitivity experiment. It is not a direct DJI candidate: native BFL is 1.923 mm and its 70-degree image height is only about 2.1 mm. These are structural mismatches that material choice cannot repair.

Nearest `nd/Vd` was more stable in this small sample. CN114 V2 showed less image-height drift and avoided the additional 70-degree VC1 failure introduced by V3. The current role-aware penalty model therefore requires recalibration; coarse role labels do not capture complete power, pupil, dispersion, and glass/plastic interactions.

## Key Technical Findings

1. `NATIVE_PASS` was a better predictor of retained substitution behavior than material coverage score. CN114 retained useful trace behavior; CN106 did not.
2. High material coverage does not establish donor transfer value. US806 is the explicit high-score, structure-limited counterexample.
3. Material substitution can produce substantial high-field degradation even when every catalog material assignment and fresh-load readback succeeds.
4. The current role-aware mapping did not outperform nearest `nd/Vd` mapping and introduced an additional CN114 high-field failure.
5. When the EFL API returns nonphysical values, the correct result is `UNKNOWN`. A surrogate metric must not be presented as measured EFL.
6. A DJI-compatible reconstruction requires structural redesign around admissible materials, pupil transfer, image scale, BFL, and TTL. Pure material replacement is insufficient.

## Dataset Value

The negative outcomes remain useful labeled data:

- **CN106**: material-induced bundle-collapse sample following a partial native replay.
- **CN114 Emb1**: material-sensitivity sample with a strong native gate and measurable high-field drift.
- **US806**: high-material-score but structure-limited counterexample.
- **US702 and US755**: lower-priority partial donors for structure and relay-role datasets.
- **US2020, US909, and US2009**: native trace-failure samples.
- **US863 and WO2016**: incomplete or assumption-dependent reconstruction samples.

These labels are suitable for audit and future ranking research, but the dataset is not yet large enough for robust machine learning.

## Recommended Next Direction

The next workflow should be:

`material compatibility scoring + native replay gate + structure-level rebuild`

It should not continue as:

`direct donor material substitution`

Recommended v1 work:

1. Recalibrate role-aware penalties against measured fresh-load drift, not semantic role labels alone.
2. Limit CN114 V2 work to a small sensitivity experiment; do not treat it as a final-design seed.
3. Extract admission, pupil-transfer, relay, and field-correction roles from CN114/CN106 rather than importing their full prescriptions.
4. Build a structure-rebuild template that starts with allowed materials and jointly enforces field admission, TTL, BFL, image scale, aperture, and geometry.
5. Defer ML training until at least 100 candidate-level samples have consistent native, mapping, fresh-load, and failure labels.

## Boundary Statement

- This work did not complete a DJI lens design.
- It did not produce a usable final optical system.
- No large-scale Zemax optimization was performed.
- No `.ZOS` or `.ZMX` file entered Git.
- Existing v0.1 optical conclusions were not modified.
- All conclusions are limited to Donor-to-DJI material transfer v0.

## Evidence Chain

- Stage 1: commit `2e4d1c4`, `research/donor-native-replay-v0`.
- Stage 2: commit `ac8ebf4`, `research/material-vector-mapping-v0`.
- Stage 3: commit `288a6a3`, `research/dji-material-substitution-v0`.
