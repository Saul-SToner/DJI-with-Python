# DJI Material Substitution Fresh-Load Validation v0

## Purpose

This controlled experiment tests whether two replay-qualified donor systems survive catalog-material substitution. It does not optimize the systems and does not claim a completed or usable DJI lens.

Only CN106154501A and CN114047597A Emb1 were tested. CN106 is compact, spherical, and materially explicit. CN114 Emb1 is the only native-pass admission donor. US806 was excluded despite its 0.921968 vector score because its native high-field trace fails and its TTL is 40.01 mm; vector proximity cannot repair a structurally unsuitable donor.

Local optical files and detailed trace CSVs are stored under:

`results/donor_material_substitution/20260704_095711_DJI_material_substitution_v0`

They are intentionally not tracked by Git.

## Controlled Method

For each donor, V2 nearest-nd/Vd and V3 role-aware mappings used the rank-1 candidates from `material_mapping_candidate.csv`. Curvature, thickness, air spacing, semi-diameter, STOP, field table, aperture, and image plane were unchanged.

CN114 native surfaces used Material Model solves. The material cells were changed to fixed solves before catalog names were written. This is a required file-format conversion, not an optical geometry change. Every material assignment was read back after save and fresh-load.

The standard trace used 7 rays at 0, 20, 35, 45, 50, 55, 60, 65, and 70 degrees. Pass requires `EC=0` and `VC=0`.

## Fresh-Load Results

| Donor/version | Material readback | EFL before/after | BFL before/after (mm) | TTL before/after (mm) | Max full-pass before/after | Result |
|---|---|---|---:|---:|---:|---|
| CN106 V2 nearest | 9/9 PASS | UNKNOWN / UNKNOWN | 1.570 / 1.570 | 17.130 / 17.130 | 20 / none | TRANSFER_DRIFT |
| CN106 V3 role-aware | 9/9 PASS | UNKNOWN / UNKNOWN | 1.570 / 1.570 | 17.130 / 17.130 | 20 / none | TRANSFER_DRIFT |
| CN114 V2 nearest | 8/8 PASS | UNKNOWN / UNKNOWN | 1.923 / 1.923 | 15.995 / 15.995 | 70 / 55 | TRANSFER_DRIFT |
| CN114 V3 role-aware | 8/8 PASS | UNKNOWN / UNKNOWN | 1.923 / 1.923 | 15.995 / 15.995 | 70 / 55 | TRANSFER_DRIFT |

EFL is `UNKNOWN` because the first-order API returns nonphysical values for these reconstructed fisheye systems. No surrogate image-height calculation is presented as EFL.

## CN106

V0 retains 7/7 at 0 and 20 degrees, then fails with EC2 from 35 degrees upward under the locked 105-degree field normalization. Both substitutions fresh-load correctly, but marginal rays already fail at 0 degrees with EC2/EC3. Neither V2 nor V3 retains a single 7/7 field. At 65/70 degrees, additional VC1 failures appear.

This is a material-induced drift on top of an already structure-limited native donor. It is not a useful local-optimization starting point. V2 nearest is only marginally less disruptive than V3 and neither is acceptable.

## CN114 Emb1

V0 fresh-load replay remains 7/7 through 70 degrees. Both substitutions remain 7/7 through 55 degrees, then degrade:

| Version | 60 deg | 65 deg | 70 deg | Chief IH70 (mm) | High-field failures |
|---|---:|---:|---:|---:|---|
| V0 native | 7/7 | 7/7 | 7/7 | 2.104853 | none |
| V2 nearest | 6/7 | 5/7 | 5/7 | 2.126815 | VC10; then VC8/VC10 |
| V3 role-aware | 6/7 | 5/7 | 5/7 | 2.166048 | VC10; VC8/VC10; VC1/VC10 at 70 |

The failure is material-induced high-field pupil/aperture drift. The underlying small image scale and BFL shortfall remain structure-limited.

## Nearest Versus Role-Aware

Nearest nd/Vd is the more stable mapping in this experiment. CN114 V2 has the same pass counts as V3 but smaller image-height drift and avoids the additional VC1 failure at 70 degrees. CN106 shows no meaningful full-pass advantage for either mapping.

Role-aware scoring did not improve trace robustness because its coarse role labels cannot represent the complete power, pupil, dispersion, and plastic/glass interaction of these systems.

## Failure Classification

- CN106 V2/V3: `material-induced drift` plus pre-existing `structure-limited failure`.
- CN114 V2/V3: `material-induced drift`, expressed as high-field VC8/VC10 and V3 VC1.
- Fresh-load construction failure: none.
- Aperture/field setup issue: no new setup change; locked fields and apertures were read back.
- Unknown: EFL remains unknown because first-order extraction is unreliable.

## Recommendation

Do not locally optimize CN106. For CN114, a narrowly bounded V2-nearest sensitivity experiment could be informative, but it should not be treated as a route to the final DJI system: native BFL is 1.923 mm and image height is about 2.1 mm. Structure-level redesign remains necessary.

This stage is only controlled material-substitution fresh-load validation. It does not complete a DJI lens design and does not modify the existing v0.1 optical conclusions.
