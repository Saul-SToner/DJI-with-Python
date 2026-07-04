# Donor Native Replay Feasibility Study v0

## Scope

This study establishes a reproducible donor intake and labeling workflow. It does **not** claim completion of a DJI lens design. Native prescriptions and model-glass reconstructions are evaluated before any DJI material substitution. Local `.ZOS`/`.ZMX` files remain untracked.

## Method

1. Screen public patents for radius, thickness, material or `nd/Vd`, stop, image-plane path, field/aperture conditions, and asphere data.
2. Mark a donor `NATIVE_INCOMPLETE` when the native prescription cannot be reconstructed without material assumptions, derived geometry, or unverified OCR.
3. Build/replay V0 native or V1 model-glass only. Record fresh-load trace behavior and geometry evidence.
4. Allow only `NATIVE_PASS` and `NATIVE_PARTIAL` into material-vector analysis.
5. Perform V2 nearest and V3 role-aware DJI mapping later, with before/after metrics. No substitution is treated as evidence in this report.

## Ten-Donor Screen

| Donor | Architecture | Native facts | Replay label | Transfer decision |
|---|---|---|---|---|
| US7023628B1 | 6G + cover fisheye | 180 deg, F/2.0, TTL 20.2 | NATIVE_PARTIAL | enter vector analysis |
| US7554753B2 | 6G distributed relay | 180 deg, F/2.8, TTL 62.6 | NATIVE_PARTIAL | enter with scale warning |
| US8064149B2 | 7G spherical fisheye | 190 deg, F/2.8, TTL 40.01 | NATIVE_PARTIAL | enter sensitivity analysis |
| US20200081231A1 | 7-element mixed glass/plastic | 193 deg, F/2.0, TTL 12.225 | NATIVE_TRACE_FAIL | blocked |
| US8638507B2 | 8-element fisheye | 180 deg, F/1.55, BFL 5.5 | NATIVE_INCOMPLETE | blocked |
| CN106154501A | 6G all-spherical glass | 210 deg, F/2.0, TTL 17.1 | NATIVE_PARTIAL | enter vector analysis |
| WO2016069418A1 | 7G spherical objective | 150 deg, F/2.8, TTL 24.002 | NATIVE_INCOMPLETE | blocked pending PDF check |
| US9091843B1 | compact aspheric wide angle | full table and image-quality reference | NATIVE_TRACE_FAIL | blocked |
| US20090080093A1 | compact wide-angle donor | native chief passes 0/30 deg only | NATIVE_TRACE_FAIL | blocked |
| CN114047597A Emb1 | compact 210-deg admission lens | F/1.79, TTL 15.995, BFL 1.923 | NATIVE_PASS | enter vector analysis |

Sources: [US7023628B1](https://patents.google.com/patent/US7023628B1/en), [US7554753B2](https://patents.google.com/patent/US7554753B2/en), [US8064149B2](https://patents.google.com/patent/US8064149B2/en), [US20200081231A1](https://patents.google.com/patent/US20200081231A1/en), [US8638507B2](https://patents.google.com/patent/US8638507B2/en), [CN106154501A](https://patents.google.com/patent/CN106154501A/en), [WO2016069418A1](https://patents.google.com/patent/WO2016069418A1/en), [US9091843B1](https://patents.google.com/patent/US9091843B1/en), [US20090080093A1](https://patents.google.com/patent/US20090080093A1/en), and [CN114047597A](https://patents.google.com/patent/CN114047597A/en).

## Replay Evidence

- `CN114047597A Emb1` is the only `NATIVE_PASS`: independent fresh-load replay gives hard-geometry PASS and 0-70 deg 7/7. It remains only an admission-gene donor because BFL is 1.923 mm and image semi-height is 3.0 mm.
- `US7023628B1`, `US7554753B2`, `US8064149B2`, and `CN106154501A` form images at low or moderate fields and are labeled `NATIVE_PARTIAL`, not patent-performance reproductions.
- `US20200081231A1`, `US9091843B1`, and `US20090080093A1` are blocked by native trace reproduction failures.
- `US8638507B2` is blocked by a derived image gap and incomplete asphere metadata. `WO2016069418A1` is blocked until OCR-normalized table entries are checked against the primary PDF.
- CN114 Emb3 is deliberately excluded: trace passes, but hard geometry fails at the rear cement and STOP-to-L5 gap.

## Material-Transfer Entry Set

The first material-vector analysis set is:

1. `CN114047597A Emb1` - reproducible native admission gene.
2. `CN106154501A` - compact spherical glass donor with named materials.
3. `US7023628B1` - complete `nd/Vd` control and useful relay sequence.
4. `US7554753B2` - distributed rear relay, with severe native scale mismatch.
5. `US8064149B2` - catalog-glass sensitivity control, not a direct compact donor.

No V2/V3 DJI substitution was executed in v0. Blank DJI match columns are intentional.

## Failure Taxonomy

- `SOURCE_INCOMPLETE`: missing or assumption-dependent native definition.
- `NATIVE_TRACE_REPRODUCTION_FAIL`: prescription builds but major fields do not form valid images.
- `NATIVE_GEOMETRY_FAIL`: physical overlap or clearance violation; trace does not override this label.
- `SCALE_MISMATCH`: native TTL/image scale is incompatible with W9A but still useful as a structural donor.
- `MATERIAL_TRANSFER_BLOCKED`: native gate has not passed.

## Next Stage

Run V1 model-glass replay for the five-entry set while preserving the native geometry and recording every material vector. Then rank DJI candidates by `nd/Vd`, power sign, lens role, and position role. Only after before/after trace, EFL, BFL, TTL, and failure-surface comparison may V2/V3 receive a transfer label.

## Effect On Existing Conclusions

No existing v0.1 optical conclusion is changed. This work adds donor provenance and replay labels only; it does not promote any donor, transferred system, or W9A design to checkpoint status.
