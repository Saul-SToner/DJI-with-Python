# Donor Material Transfer Experiment Plan (v0.2)

This report outlines the minimal viable experiment (MVE) for validating the Donor-to-Target material mapping pipeline.

---

## 1. Experimental Setup

We will select **10 public Donor prescriptions** representing typical wide-angle sequential topologies (e.g. Retrofocus, Double-Gauss variants).

For each donor, we will generate and build three distinct versions:
1.  **Native / Model-Glass Baseline** (`V0`/`V1`)
2.  **Nearest Neighbor Mapping** (`V2_dji_nearest`)
3.  **Role-Aware Mapping** (`V3_dji_role_aware`)

---

## 2. Comparison Metrics

We will measure paraxial and real ray tracing changes before and after the material transfer:

-   **EFL Drift ($\Delta \text{EFL}$)**: Paraxial effective focal length change.
-   **BFL Drift ($\Delta \text{BFL}$)**: Back focal length change (important for sensor clearance).
-   **TTL Drift ($\Delta \text{TTL}$)**: Total track length drift.
-   **Max Pass Field Change ($\Delta \omega$)**: The change in maximum field angle that successfully traces without ray aborts.
-   **Failure Surface Change**: If the design fails to trace, check if the failure surface relocates or if new surfaces trigger TIR.

---

## 3. Hypothesis Validation

We will test the following hypothesis:
> **Hypothesis**: The role-aware mapping method (`V3`) leads to significantly smaller paraxial and real ray tracing drift than simple nearest $n_d$/$v_d$ mapping (`V2`), and successfully recovers designs that fail standard nearest-neighbor replacement.

---

## 4. Expected Outputs

The experiment will produce the following structured files under `data/processed/`:
-   `donor_native_table.csv`: Baseline donor specs.
-   `material_vector_table.csv`: Mapped glass vectors.
-   `donor_material_sequence.csv`: Glass sequences by element.
-   `material_transfer_result.csv`: Paraxial comparison table.
-   `donor_transfer_label.csv`: Dataset usability flags for machine learning training.
