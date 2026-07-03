# Stage Summary: Wide-Angle Structure Search Triage

This report compiles the outcomes of the key triage phases executed in this workspace.

## 1. Stage 0: Execution Environment Calibration
- **Goal**: Verify ray trace extraction accuracy.
- **Variant**: `variants/L4_T2p10.ZOS`
- **Field**: `70掳`
- **Result**: PASSED. Chief height = 4.002011 mm, Centroid = 4.172671 mm, Envelope = 4.898672 mm.
- **Conclusion**: Standalone API connections, field setups, and single-ray tracing are verified and matching baseline data.

## 2. Phase W: R106H Candidate Triage
- **Goal**: Native rebuild and geometric gate evaluation of three candidate seeds.
- **Candidates**:
  - `CANDIDATE_01`: US7869141B2 Table 1 (6G)
  - `CANDIDATE_02`: CN106154501A Ex 1 (6G)
  - `CANDIDATE_03`: US7929221B2 Table 1 + Derived Cover (6G)
- **Outcome**: `R106H_NO_SEED_READY_FOR_STRICT_AUDIT`
  - Candidate 1 successfully traced all high fields but failed the mechanical TTL constraint (18.72 mm > 18.0 mm limit).
  - Candidate 2 successfully traced all high fields but failed the mechanical BFL constraint (2.07 mm < 2.3 mm limit).
  - Candidate 3 failed to trace high fields due to source scale mismatch (FOV/EFL incompatibility).
- **Current Decision**: Keep Candidates 1 & 2 as functional block reference layouts. Reject Candidate 3.
