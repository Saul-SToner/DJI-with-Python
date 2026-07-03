# Design Constraints & Triage Criteria

This document archives the mechanical and optical constraint gates used to screen candidate designs during structural triage.

## Constraint Parameters

All limits are stage-dependent and subject to adjustment, but the default working baseline targets for the wide-angle search include:

| Metric | Target Value / Limit | Verification Method | Status / Notes |
|---|---|---|---|
| **F-number (F/#)** | `2.5` | Native Zemax System Aperture | Default working target; F/2.0 is stage-dependent and unverified. |
| **Total Track Length (TTL)** | `≤ 18.0 mm` | Cumulative LDE thickness sum | CANDIDATE_01 failed this target (18.72 mm). |
| **Back Focal Length (BFL)** | `≥ 2.3 mm` | Distance from last optical surface to IMA | CANDIDATE_02 failed this target (2.07 mm). |
| **Image Semi-Diameter** | `≥ 4.0 mm` (8.0 mm full circle) | IMA surface semi-diameter solve | Working target for high field sensor coverage. |
| **Max Half Field of View (FOV)** | `71.5°` | System Field Point configuration | Checked via normalized ray trace fields up to 71.5°. |
| **Air Clearances** | `≥ 0.1 mm` | Sag-based mechanical clearance check | Checked on all air/glass interfaces. |
| **Glass Thicknesses** | `≥ 0.3 mm` | Center and edge thickness check | Checked on all element sags. |

All unverified or stage-specific criteria are marked as `TODO` or `UNKNOWN` in the triage scripts to prevent artificial optimization bias.
