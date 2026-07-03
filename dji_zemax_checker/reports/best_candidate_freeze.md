# Best Candidate Freeze Report

This document records the specifications and frozen status of the top structural candidate designs reconstructed during triage.

## CANDIDATE_01_US7869141B2_TABLE1_6G

- **Verification Status**: `KEEP_AS_FUNCTIONAL_BLOCK_REFERENCE`
- **Reason for Freeze**: Traces all high fields up to $71.5^\circ$ successfully without clipping, but fails TTL limit.
- **Key Metrics (Native Zemax)**:
  - Surface Count: `16`
  - Stop Surface: `9`
  - F-number: `2.5` (working target)
  - TTL: `18.72 mm` (violates $\le 18.0$ mm constraint)
  - BFL: `2.78 mm` (meets $\ge 2.3$ mm constraint)
  - Image Semi-Diameter: `4.0 mm`
- **Manifest Reference**: `variants/CANDIDATE_01_US7869141B2_TABLE1_6G.ZOS`

---

## CANDIDATE_02_CN106154501A_EX1_6G

- **Verification Status**: `KEEP_AS_FUNCTIONAL_BLOCK_REFERENCE`
- **Reason for Freeze**: Traces all high fields up to $71.5^\circ$ successfully without clipping, but fails BFL limit.
- **Key Metrics (Native Zemax)**:
  - Surface Count: `18`
  - Stop Surface: `9`
  - F-number: `2.5` (working target)
  - TTL: `17.45 mm` (meets $\le 18.0$ mm constraint)
  - BFL: `2.07 mm` (violates $\ge 2.3$ mm constraint)
  - Image Semi-Diameter: `4.0 mm`
- **Manifest Reference**: `variants/CANDIDATE_02_CN106154501A_EX1_6G.ZOS`

> [!NOTE]
> Neither candidate is approved for optical optimization or production. They serve strictly as structural benchmarks for architectural studies.
