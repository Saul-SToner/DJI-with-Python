# Material Transfer Data Schema

This document defines the schema, units, allowed values, and labeling rules for the CSV files in the Donor-to-Target material mapping pipeline.

---

## 1. `donor_native_table.csv`

Tracks baseline donor lens parameters and native replay validation results.

| Column Name | Type | Unit | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `donor_id` | String | - | Unique identifier for the donor structure (e.g. `US9099999_Ex01`). |
| `source` | String | - | Reference publication, patent number, or general source database. |
| `topology_type` | String | - | Optical classification (e.g. `retrofocus`, `double_gauss`, `fisheye`). |
| `lens_count` | Integer | - | Total number of individual physical lens elements. |
| `surface_count` | Integer | - | Total number of sequential surfaces in the LDE (excluding object/image). |
| `EFL_native` | Float | mm | Paraxial Effective Focal Length of the native prescription. |
| `F_number_native`| Float | - | Paraxial F-number of the native prescription. |
| `HFOV_native` | Float | deg | Half Field of View of the native prescription. |
| `TTL_native` | Float | mm | Total Track Length of the native prescription. |
| `BFL_native` | Float | mm | Back Focal Length of the native prescription. |
| `image_height_native`| Float| mm| Paraxial image height (sensor semi-diagonal). |
| `material_completeness`| Float| % | Ratio of successfully parsed glasses to total powered elements. |
| `native_replay_status`| String | - | Status of native rebuild (`PASS`, `FAIL`, `BLOCKED`). |
| `native_trace_status` | String | - | Status of real ray tracing (`TRACE_PASS`, `RAY_ABORT`, `TIR`, `CLIPPED`). |
| `notes` | String | - | Additional annotations. |

---

## 2. `material_vector_table.csv`

Defines the glass database representing individual material property vectors.

| Column Name | Type | Unit | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `material_id` | String | - | Unique glass identifier. |
| `material_name` | String | - | Glass designation from vendor (e.g. `N-BK7`, `H-ZF52`). |
| `source_library` | String | - | Catalog source (e.g. `SCHOTT`, `CDGM`, `OHARA`, `HOYA`). |
| `nd` | Float | - | Refractive index at helium d-line (587.56 nm). |
| `Vd` | Float | - | Abbe dispersion number at d-line. |
| `PgF` | Float | - | Relative partial dispersion (g-line and F-line). |
| `material_type` | String | - | Classification: `glass`, `plastic`, `cover_plate`. |
| `available_in_dji`| Boolean | - | `True` if present in the target catalog; else `False`. |
| `notes` | String | - | Usage limits or availability flags. |

---

## 3. `donor_material_sequence.csv`

Logs structural role mappings for each lens element in the donor prescription.

| Column Name | Type | Unit | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `donor_id` | String | - | Reference donor design identifier. |
| `lens_id` | Integer | - | 1-based index of the lens element (from object side). |
| `native_material` | String | - | Original material catalog name. |
| `native_nd` | Float | - | Original refractive index. |
| `native_Vd` | Float | - | Original Abbe dispersion number. |
| `lens_power_sign` | Integer | - | Sign of optical power: `1` (positive), `-1` (negative), `0` (flat). |
| `lens_role` | String | - | Functional role (e.g. `front_crown`, `rear_flint`, `stop_adjacent`). |
| `position_role` | String | - | Relative location to stop: `front_group`, `rear_group`, `stop`. |
| `dji_best_match` | String | - | The selected target material name. |
| `dji_nd` | Float | - | Refractive index of target matched glass. |
| `dji_Vd` | Float | - | Abbe number of target matched glass. |
| `nd_error` | Float | - | Refractive index difference ($\Delta n_d = n_{d,\text{target}} - n_{d,\text{native}}$). |
| `Vd_error` | Float | - | Abbe number difference ($\Delta v_d = v_{d,\text{target}} - v_{d,\text{native}}$). |
| `role_match_status`| String | - | Role audit result (`MATCHED`, `DRIFTED`, `MISMATCHED`). |
| `mapping_score` | Float | - | Combined score from the vector matching heuristic (lower is better). |

---

## 4. `material_transfer_result.csv`

Records performance comparisons before and after applying the material mapping.

| Column Name | Type | Unit | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `donor_id` | String | - | Reference donor design identifier. |
| `transfer_version`| String | - | Mapping version (`V2_dji_nearest`, `V3_dji_role_aware`). |
| `mapping_method` | String | - | Heuristics code (`nearest_nd_vd`, `role_aware_vector`). |
| `material_coverage_score`| Float| %| Percentage of lens elements successfully mapped to the target catalog. |
| `EFL_before` | Float | mm | Effective Focal Length before substitution (from V1 model-glass). |
| `EFL_after` | Float | mm | Effective Focal Length after substitution. |
| `BFL_before` | Float | mm | Back Focal Length before substitution. |
| `BFL_after` | Float | mm | Back Focal Length after substitution. |
| `TTL_before` | Float | mm | Total Track Length before substitution. |
| `TTL_after` | Float | mm | Total Track Length after substitution. |
| `max_pass_field_before`| Float| deg| Maximum field successfully traced before substitution. |
| `max_pass_field_after`| Float | deg| Maximum field successfully traced after substitution. |
| `failure_surface_before`| Integer| -| ID of the surface causing ray aborts before substitution (`0` if none). |
| `failure_surface_after`| Integer| -| ID of the surface causing ray aborts after substitution (`0` if none). |
| `transfer_status` | String | - | Result status (`PASS`, `FAIL`, `BLOCKED`). |
| `notes` | String | - | Drift comments or ray tracing diagnostics. |

---

## 5. `donor_transfer_label.csv`

Classifies and filters designs for downstream machine learning datasets.

| Column Name | Type | Unit | Description / Allowed Values |
| :--- | :--- | :--- | :--- |
| `donor_id` | String | - | Reference donor design identifier. |
| `native_status` | String | - | Baseline replay status (`PASS`, `FAIL`, `BLOCKED`). |
| `model_glass_status`| String| -| Model-glass validation status (`PASS`, `FAIL`, `BLOCKED`). |
| `dji_transfer_status`| String| -| Final mapped status (`TRANSFER_PASS`, `TRANSFER_DRIFT`, `TRANSFER_FAIL`). |
| `dominant_failure_reason`| String| -| Root cause explanation (`TIR`, `ABERRATION_BLOWUP`, `GAP_INTERFERENCE`). |
| `usable_for_structure_dataset`| Boolean| -| `True` if layout is structurally feasible (i.e. model-glass traces). |
| `usable_for_material_dataset` | Boolean| -| `True` if target catalog has compatible glasses for this layout. |
| `usable_for_ml_training` | Boolean| -| `True` if both structure and materials are compatible for training. |
| `notes` | String | - | Specific data cleaning exclusions or flags. |
