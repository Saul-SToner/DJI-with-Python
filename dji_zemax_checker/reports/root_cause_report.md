# Root Cause Analysis: High-Field Vignetting and Edge-Pupil Margin Limits

This report analyzes the geometric and ray-tracing bottlenecks that trigger failures at high field angles in wide-angle structures.

## 1. High-Field Vignetting & Ray Clippings

In wide-angle designs ($FOV \ge 140^\circ$), ray angles on the first three elements (L1–L3) are extremely steep. The dominant failure mode during high-field traces ($65^\circ$ to $71.5^\circ$) is ray clipping or Total Internal Reflection (TIR) at:
- **L1/L2 Rear Surfaces**: High angle of incidence leads to TIR for edge pupil rays (`ep_px`, `ep_mx`).
- **L3/STOP Junction**: Severe bending of the chief and upper pupil rays (`ep_py`) results in ray heights exceeding clear semi-diameters, causing surface intercepts to miss the lens element or crash into mechanical apertures.

## 2. Edge-Pupil Margins

When testing the 7 canonical rays (`chief`, `ep_px`, `ep_mx`, `ep_py`, `ep_my`, `in_p7`, `in_m7`), the clearance margins at the STOP and the last optical surface are extremely tight:
- **STOP Clearance**: Real ray coordinates at the STOP must stay within the physical clear aperture diameter. Vignetting solves often shrink the STOP diameter to pass rays, but this increases F-number and violates F/2.5 throughput constraints.
- **Last Surface Margins**: Image-side element clearances to the cover glass/sensor are highly sensitive to BFL compression. Shrinking BFL below 2.3 mm (as in Candidate 2) provides better MTF but causes mechanical interference with cover filters.

## 3. Structural Limits of the Candidates
- **Candidate 1 (US7869141B2)**: Avoids clipping by extending the axial length, which leads directly to the TTL limit violation (18.72 mm).
- **Candidate 2 (CN106154501A)**: Keeps length short (TTL = 17.45 mm) by compressing the image-side relay group, leading directly to BFL compression failure (2.07 mm).
