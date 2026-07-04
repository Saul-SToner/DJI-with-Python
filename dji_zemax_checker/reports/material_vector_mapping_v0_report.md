# Donor Material Vector Mapping v0

## Scope

This stage covers only CN114 Emb1, CN106, US702, US755, and US806. It performs analytical material-vector matching only. No DJI material was written to a Zemax file, no large-scale optimization was run, and no DJI lens design is claimed.

## Mapping Rules

- `D_ndvd = |nd_native - nd_dji| / 0.10 + |Vd_native - Vd_dji| / 20`
- `D_total = D_ndvd + role_penalty + type_penalty`
- `mapping_score = max(0, 1 - D_total)`

Role-aware penalties follow the task specification. Native model-glass type is treated as unknown (`type_penalty=0.2`). Rear-relay and cover roles are conservatively marked uncertain (`role_penalty=0.3`) because nd/Vd alone does not establish optical role. The local target list is marked `DJI_LIBRARY_INCOMPLETE`.

## Donor Summary

| Donor | Native status | Lenses/vectors | Mean nd error | Mean Vd error | Role incompatible | Role uncertain | Coverage score |
|---|---|---:|---:|---:|---:|---:|---:|
| CN114047597A | NATIVE_PASS | 8 | 0.005795 | 0.884924 | 0 | 2 | 0.622803 |
| CN106154501A | NATIVE_PARTIAL | 9 | 0.006066 | 1.883690 | 0 | 4 | 0.711820 |
| US7023628B1 | NATIVE_PARTIAL | 7 | 0.005887 | 0.875864 | 1 | 3 | 0.454764 |
| US7554753B2 | NATIVE_PARTIAL | 10 | 0.000001 | 0.083469 | 2 | 4 | 0.516777 |
| US8064149B2 | NATIVE_PARTIAL | 8 | 0.000204 | 0.019891 | 0 | 2 | 0.921968 |

`material_coverage_score` is the mean top-1 role-aware mapping score across recorded lens/material vectors. It is a prescreen score, not an optical-performance probability.

## Nearest Versus Role-Aware

Nearest mapping minimizes glass-vector distance only. Role-aware mapping can reject a numerically close crown/flint swap and penalizes unknown model-glass type. Consequently, role-aware scores are intentionally lower and may select a slightly farther nd/Vd candidate when its coarse material role is compatible.

| Donor | Mean nearest score | Mean role-aware score |
|---|---:|---:|
| CN114047597A | 0.94 | 0.62 |
| CN106154501A | 0.98 | 0.71 |
| US7023628B1 | 0.97 | 0.45 |
| US7554753B2 | 1.00 | 0.52 |
| US8064149B2 | 1.00 | 0.92 |

The large drops for US702 and US755 are caused by role/type uncertainty rather than poor raw glass-vector proximity. US806 has nearly exact catalog-vector matches, but its weak native replay and 40.01 mm TTL still prevent it from becoming the preferred optical transfer candidate.

## Recommended Fresh-Load Substitution Tests

1. **CN106154501A**: named native materials, compact all-spherical architecture, TTL near the W9A limit, and partial native replay make it the cleanest V2/V3 comparison.
2. **CN114047597A Emb1**: the only native-pass admission gene. Test only as a material-transfer sensitivity control; its BFL and image scale already miss W9A requirements.

## Deferred Donors

- **US7023628B1**: useful vector sequence but missing native apertures and TTL exceeds 20 mm.
- **US7554753B2**: native TTL 62.6 mm makes material substitution inseparable from a later scale redesign.
- **US8064149B2**: catalog-glass donor reproduces only low fields and has TTL 40.01 mm.

## Guardrails

All V2/V3 rows remain `PLANNED_NOT_EXECUTED`. EFL-after, BFL-after, TTL-after, trace-after, and failure-surface-after are `UNKNOWN`. Existing v0.1 optical conclusions are unchanged.
