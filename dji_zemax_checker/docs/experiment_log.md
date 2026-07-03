# Experiment Log

This log documents the historical run progression of the wide-angle lens triage and build scripts.

## Run History

### Stage 0: Calibration Validation
- **Hypothesis**: The paraxial ray tracing and single-ray extraction logic match reference wide-angle footprint metrics.
- **Operation**: Execute trace on baseline variant `variants/L4_T2p10.ZOS` at 70° field.
- **Changed Parameters**: None (baseline check).
- **Result**: PASSED.
  - Chief height: `4.002011 mm`
  - Centroid height: `4.172671 mm`
  - Envelope height: `4.898672 mm`
- **Conclusion**: Execution environment is fully calibrated.

### Phase W: R106H Candidate Triage (2026-06-29)
- **Hypothesis**: Native reconstructions of Candidate 1 (US7869141B2), Candidate 2 (CN106154501A), and Candidate 3 (US7929221B2) will meet all paraxial and mechanical constraints.
- **Operation**: Reconstructed sequential models using exact model glass solves and even-aspheric coefficients; evaluated mechanical clearances and traced fields up to 71.5°.
- **Changed Parameters**: Surface-by-surface model glass solves and clear apertures.
- **Result**: `R106H_NO_SEED_READY_FOR_STRICT_AUDIT`.
  - `CANDIDATE_01` (US7869141B2): Traces successfully but violates TTL target (18.72 mm > 18.0 mm limit).
  - `CANDIDATE_02` (CN106154501A): Traces successfully but violates BFL target (2.07 mm < 2.3 mm limit).
  - `CANDIDATE_03` (US7929221B2): Fails trace due to source scale mismatch (Native FOV 68° and EFL 1.25 mm incompatible with W9A target).
- **Conclusion**: None of the three candidates are ready for strict audit. Keep CANDIDATE_01 and CANDIDATE_02 as functional block references.
