# Data Schema Documentation

This document defines the columns and schemas of the processed CSV tables in `data/processed/`.

## 1. Candidate Table (`candidate_table.csv`)

| Column | Type | Description |
|---|---|---|
| `candidate_id` | String | Unique identifier of the candidate design. |
| `stage` | String | Project stage (e.g. `R106H`). |
| `topology_type` | String | Structural topology code (e.g. `6G`, `7G`, `UNKNOWN`). |
| `source_family` | String | Source patent or design family. |
| `zos_path` | String | Relative path to the `.ZOS` design file. |
| `zos_sha256` | String | SHA-256 hash of the `.ZOS` file. |
| `surface_count` | Integer | Number of surfaces in the LDE. |
| `lens_count` | Integer | Number of physical elements. |
| `stop_surface` | Integer | Surface index of the system STOP. |
| `F_number` | Float | System focal ratio. |
| `TTL_mm` | Float | Total track length in millimeters. |
| `BFL_mm` | Float | Back focal length in millimeters. |
| `image_sd_mm` | Float | Image semi-diameter in millimeters. |
| `max_pass_field_deg` | Float | Maximum field angle that successfully traced without failure. |
| `status` | String | Evaluation status (e.g. `FAILED_TTL`, `PASSED_TRACE`). |
| `notes` | String | Explanatory remarks. |

---

## 2. Trace Result Table (`trace_result_table.csv`)

| Column | Type | Description |
|---|---|---|
| `candidate_id` | String | Candidate identifier. |
| `stage` | String | Project stage. |
| `field_deg` | Float | Field angle traced in degrees. |
| `ray_type` | String | Ray identifier (e.g. `chief`, `ep_px`, `ep_mx`). |
| `pass_fail` | String | Trace result (`PASS` or `FAIL`). |
| `failure_surface` | Integer | Surface index where the ray tracing failed or clipped. |
| `failure_surface_label` | String | Comment/label of the failing surface. |
| `failure_type` | String | Failure code (e.g. `vignetting`, `tir`, `missed`). |
| `ray_height_mm` | Float | Real ray intercept height at the failure surface. |
| `semi_diameter_mm` | Float | Clear semi-diameter of the failure surface. |
| `physical_margin_mm` | Float | Distance between ray intercept and clear aperture edge. |
| `trace_status` | String | Trace status message. |
| `notes` | String | Remarks. |

---

## 3. Failure Surface Table (`failure_surface_table.csv`)

| Column | Type | Description |
|---|---|---|
| `candidate_id` | String | Candidate identifier. |
| `stage` | String | Project stage. |
| `failure_field_deg` | Float | Field angle triggering the failure. |
| `failure_ray` | String | Ray identifier that clipped. |
| `failure_surface` | Integer | Surface index where clipping occurred. |
| `failure_surface_label` | String | Comment/label of the surface. |
| `failure_type` | String | Type of failure (e.g. `EDGE_COLLISION`, `TIR`). |
| `physical_margin_mm` | Float | Remaining clearance margin. |
| `dominant_limiter` | String | Constraint limiting performance. |
| `repair_attempted` | Boolean | Whether an automated/manual repair was attempted. |
| `repair_effect` | String | Result of the repair attempt. |
| `notes` | String | Remarks. |

---

## 4. Experiment Log (`experiment_log.csv`)

| Column | Type | Description |
|---|---|---|
| `stage` | String | Project stage/phase identifier. |
| `date` | String | Date of execution. |
| `hypothesis` | String | Goal or expectation tested. |
| `operation` | String | Process or script run. |
| `changed_parameters` | String | Parameters modified in the run. |
| `result` | String | Quantitative/qualitative outcome. |
| `conclusion` | String | Decisive takeaway. |
| `output_path` | String | Output directory or result file path. |
| `review_status` | String | Status of results validation. |
| `notes` | String | Remarks. |
