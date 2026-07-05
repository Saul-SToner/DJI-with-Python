# Projection Power Reallocation v2

## Purpose

This stage moves beyond limited perturbation of the CN114-derived prescription and tests grouped projection-power reallocation. The goal is to determine whether front angular capture and rear relay power can raise 70-degree image height without losing BFL, high-field trace, or physical geometry.

No global optimizer, random all-surface search, new donor, or material remapping was used.

## v1 Baseline

The v1 endpoint `FOCUS_048` was selected as the reference because it is geometry-valid and provides:

- BFL: 2.523 mm;
- TTL: 16.495 mm;
- maximum full-pass field: 60 degrees;
- 70-degree chief image height: 2.250189 mm.

v1 established that BFL and 60-degree trace were achievable, while 3 mm image height was not. Projection scale became the dominant blocker.

The v2 staged targets remain 3 mm for feasibility and 4 mm for strong progress. An immediate 8 mm target would not distinguish useful partial scale gain from a completely blocked architecture.

## Experiment Groups

Seventy-four deterministic fresh-load variants were evaluated:

1. **Rear relay magnification:** 48 variants combining grouped rear power, rear spacing, and image-plane shifts.
2. **Front capture + rear relay coupling:** 18 variants combining front power, rear power, and STOP-to-rear shifts.
3. **Projection-scale sanity:** 8 front-only, rear-only, uniform, and opposed-power diagnostics.

Power scaling changed grouped curvatures while preserving materials. Asphere coefficients were unchanged, so these are structural sensitivity experiments rather than strict similarity transforms or final candidates.

## Gate Summary

| Metric | Raw count | Geometry-valid count |
|---|---:|---:|
| Total variants | 74 | 3 |
| BFL >= 2.3 mm | 74 | 3 |
| Max full-pass >= 60 deg | 70 | 0 |
| Image height >= 3.0 mm | 0 | 0 |
| Gates A+B+C | 0 | 0 |
| Image height >= 4.0 mm | 0 | 0 |

Raw trace counts from geometry-failed variants are diagnostic only and are not accepted as design progress.

## Top Diagnostic Results

### Highest Geometry-Valid Image Height

| Variant | Group | Front power | Rear power | BFL (mm) | IH70 (mm) | Gain | Max full-pass | Geometry |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `C_067_uniform_0p85` | sanity | 0.85 | 0.85 | 2.723 | 2.687823 | 1.194488 | none | PASS |
| `C_071_front_only_0p85` | sanity | 0.85 | 1.00 | 2.723 | 2.586981 | 1.149673 | 0 deg | PASS |
| `C_069_rear_only_0p70` | sanity | 1.00 | 0.70 | 2.723 | 2.479934 | 1.102100 | none | PASS |

The highest reliable image height is 2.687823 mm, a 19.45% gain, but it loses all full-pass fields. It is not a balanced candidate.

### Best Raw BFL + Field Balance

Several geometry-failed variants retain 65-70 degree trace with image heights around 2.25-2.38 mm. The strongest raw example, `C_073_opposed_A`, reaches 65 degrees and 2.378329 mm, but fails the hard geometry gate. These variants are rejected.

### Best Accepted Balance

No v2 variant simultaneously passes geometry, BFL, and 60-degree trace. Therefore, v2 has no accepted balanced variant and no Gate A/B/C candidate. The v1 `FOCUS_048` reference remains the best verified BFL/field endpoint, not a v2 result or checkpoint.

## Findings

### Projection-Scale Limited

Grouped power changes can increase image height, but the maximum valid gain is insufficient for Gate C and coincides with trace collapse. The architecture does not provide independent projection-magnification freedom.

### Rear-Relay Magnification Collapse

Rear power changes frequently preserve ray trace only in physically invalid geometries. Geometry-valid rear-only scaling reaches 2.479934 mm but loses all full-pass fields.

### Front-Capture Mismatch

Front-only and uniform power reductions lift image height more strongly than rear-only changes, but destroy admission/pupil continuity. This indicates that front capture and image mapping remain tightly coupled.

### High-Field Trace Limited

No geometry-valid v2 variant retains a 60-degree full-pass boundary. Trace-preserving raw branches provide only small image-height gains and fail geometry.

### Geometry Limited

Only 3 of 74 variants pass the hard geometry gate. Curvature-power scaling changes sag and edge clearance even when center thicknesses are unchanged. Future power allocation must be geometry-presolved rather than applied to an existing envelope.

### BFL Tradeoff

BFL remains above 2.3 mm for all variants and is not the blocker. More final air does not create the missing projection scale.

## Decision

The current CN114-derived full-prescription route should not continue into another local power sweep. v2 confirms that the architecture lacks separable, geometry-valid image-magnification freedom.

A v3 study is recommended only if it creates a new DJI envelope rebuild template with independently allocated modules:

`front admission module -> pupil handoff module -> projection magnification relay -> BFL/field module`

The template must presolve sag/edge geometry before trace and should use CN114 only as a role prior. It should not inherit the full CN114 radii or treat v2 diagnostics as seeds.

## Boundary Statement

- This stage did not complete a DJI lens design.
- It did not produce a final usable optical system.
- No large-scale optimization was executed.
- No `.ZOS` or `.ZMX` file is added to Git.
- Existing v0.1, v0.2, v0.3, and v0.4 conclusions are unchanged.
- Conclusions are limited to projection power reallocation v2.
