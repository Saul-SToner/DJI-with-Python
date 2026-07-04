# CN114 Structure Rebuild Feasibility v0

## Purpose

This stage moves from donor material substitution to structure-level rebuild feasibility. It asks whether CN114 Emb1 can supply transferable optical roles under DJI constraints, without treating its complete prescription as a final design.

No new donor was introduced. No global optimization, broad curvature search, or forced 70-degree recovery was performed.

## Baseline

CN114 Emb1 was selected because it is the only `NATIVE_PASS` donor in donor transfer v0. Its native/model-glass baseline fresh-loads with 0-70 degrees at 7/7. After catalog substitution, V2 and V3 retain full pass only through 55 degrees, which is still substantially stronger than CN106's transfer behavior.

CN114 is not a direct DJI solution:

- native mechanical BFL: 1.923 mm;
- 70-degree chief image height: about 2.1 mm;
- required DJI-class image scale: about 8 mm half image height;
- V2/V3 high-field trace is material-sensitive.

It is therefore evaluated only as a structure-sensitivity and role template.

## Metric Sanity Audit

The native, V2-nearest, and V3-role-aware systems were audited with API, chief-ray projection estimates, and low-field estimates.

| Version | Zemax EFL API | Equidistant estimate at 70 deg (mm) | Equidistant estimate at 20 deg (mm) | Rectilinear estimate at 20 deg (mm) | F/# | TTL (mm) | BFL (mm) | Max full-pass |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| V0 native | invalid | 1.722846 | 1.732899 | 1.661937 | 1.79 | 15.995 | 1.923 | 70 deg |
| V2 nearest | invalid | 1.740822 | 1.749509 | 1.677867 | 1.79 | 15.995 | 1.923 | 55 deg |
| V3 role-aware | invalid | 1.772934 | 1.776990 | 1.704224 | 1.79 | 15.995 | 1.923 | 55 deg |

`GetFirstOrderData()` returns nonphysical/raw values for these reconstructed fisheye files and is labeled `EFL_API_INVALID`. Equidistant estimates are internally consistent, but projection-model choice changes the inferred focal length by about four percent. The overall EFL classification is therefore `EFL_CONFLICT`, not a verified Zemax EFL.

The equidistant values remain useful as projection-scale diagnostics. They are not substituted into the API EFL field.

## Structure Sensitivity Matrix

Twenty-six fresh-load variants were evaluated from CN114 V2 nearest:

- 1 baseline;
- 7 image-plane/refocus shifts;
- 6 L5-L6 rear-gap perturbations;
- 6 L7-to-plate gap perturbations;
- 4 bounded STOP shifts;
- 2 uniform linear-scale diagnostics.

### BFL Sensitivity

Image-plane shift changes mechanical BFL directly. A +0.40 mm shift raises BFL from 1.923 to 2.323 mm while TTL rises from 15.995 to 16.395 mm. Geometry remains PASS and the maximum full-pass field remains 55 degrees.

This demonstrates mechanical BFL feasibility inside the 18 mm track budget, but not optical completion: focus quality was not optimized or validated. BFL is partly recoverable through packaging/refocus freedom, while final focus and image quality remain unresolved.

### Image-Height Sensitivity

The largest tested image-plane shift raises chief image height from 2.1268 to 2.2363 mm. Positive L5-L6 and L7-plate spacing changes also raise image height slightly, with the largest local values remaining near 2.17 mm.

No local variable approaches an 8 mm half-image-height class. Image scale is therefore a structure-level projection constraint, not a rear-gap or refocus correction.

### Field-Trace Sensitivity

Two geometry-valid variants improve maximum full-pass field from 55 to 60 degrees:

| Variant | Change | BFL (mm) | Chief IH70 (mm) | Max full-pass |
|---|---|---:|---:|---:|
| `L5L6_-0.10` | L5-L6 gap -0.10 mm | 1.923 | 2.0854 | 60 deg |
| `STOP_+0.02` | STOP +0.02 mm with conjugate interval compensation | 1.923 | 2.1267 | 60 deg |

Positive L5-L6 spacing progressively degrades the full-pass boundary to 50 and then 45 degrees. Negative STOP shifts also degrade the trace boundary. These responses support a pupil-handoff/relay interpretation for the 70-to-55-degree material-transfer loss.

No variant restores 70-degree full pass. The experiment was not intended to force that recovery.

### Geometry Sensitivity

All local refocus, gap, and STOP variants pass the hard geometry gate. Both uniform linear-scale diagnostics fail geometry. They also omit asphere-coefficient rescaling and are diagnostic only, not optical candidates.

## Structure Role Extraction

The role table records engineering hypotheses, not established design truth:

- **L1/L2 front group:** coupled negative admission pair for wide-angle front capture and angular compression.
- **L3:** middle positive correction element, plausibly sharing distortion/field mapping correction.
- **L4 near STOP:** weak aspheric pupil-control/handoff element.
- **L5:** first post-STOP positive relay; L5-L6 spacing measurably changes high-field acceptance.
- **L6/L7 cemented pair:** rear correction/relay block, plausibly balancing field curvature, pupil transfer, and image-side power.
- **Equivalent plate:** cover/filter region; additional field function remains unknown.

The entire chain is highly coupled. The transferable object is the role sequence and conjugate topology, not the numerical radii or complete prescription.

## Answers To Feasibility Questions

1. **Why did substitution reduce 70 to 55 degrees?** The small matrix points to material-induced pupil-handoff and rear-relay sensitivity. STOP +0.02 and L5-L6 -0.10 recover 60 degrees, but not 70.
2. **Are BFL and image height structural constraints?** BFL can be mechanically moved above 2.3 mm inside TTL 18 mm, although focus quality remains unproven. The approximately 2.1 mm image scale is decisively structural.
3. **Can EFL be read reliably without the API?** Equidistant chief-ray estimates give a useful 1.72-1.78 mm diagnostic range, but projection-model conflict prevents a verified EFL claim.
4. **Is CN114 suitable as a template?** Yes, as a role and conjugate template. No, as a complete prescription template.
5. **Is a limited rebuild worthwhile?** Yes, if it starts from DJI materials and jointly rebuilds front admission, STOP handoff, rear relay, BFL, and projection scale.

## Decision

`CN114_LIMITED_STRUCTURE_REBUILD_RECOMMENDED`

The next stage should build a new DJI-envelope reconstruction template using CN114's role sequence as a prior:

`front admission -> middle correction -> stop-near pupil control -> rear relay/correction -> cover`

Hard constraints must be active from the first seed: allowed materials, 8 mm-class half image height, BFL above 2.3 mm, TTL at or below 18 mm, target F-number, geometry, and native fresh-load trace. Direct continuation from the full CN114 prescription is not recommended.

## Boundary Statement

- This stage did not complete a DJI lens design.
- It did not produce a final usable optical system.
- It did not run large-scale optimization.
- No `.ZOS` or `.ZMX` file is added to Git.
- Existing v0.1 and v0.2 conclusions are unchanged.
- Conclusions are limited to CN114 structure-rebuild feasibility v0.
