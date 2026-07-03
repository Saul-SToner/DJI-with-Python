# Failed Routes and Design Bottlenecks

This report logs the design paths, perturbations, and candidate scales that failed during structural triage.

## 1. Scale Mismatch Failures (CANDIDATE_03)

- **Source Family**: US7929221B2 Table 1
- **Failure Mode**: Scale Incompatibility
- **Detail**: The original design's half-FOV is $68^\circ$ and EFL is $1.25$ mm. Attempting to fit it into the W9A sensor profile ($y_{ref} \approx 4.0$ mm at $70^\circ$) required scaling up the elements. However, scaling caused the lens thicknesses and sags to expand proportionally, violating both TTL and clear aperture gates. Keeping it unscaled resulted in extreme image compression that failed high-field ray tracing.
- **Conclusion**: Candidates with highly compressed focal lengths (<1.5 mm) cannot be scaled linearly to meet W9A paraxial specifications.

## 2. Relocating STOP Surface

- **Attempted Route**: Shifting the physical STOP position forward (e.g., placing it directly on L2 rear or L3 front) to compress front element diameters.
- **Bottleneck**: Moving the STOP changes the entrance pupil position, causing extreme principal ray angles at L1 and L2. This triggers immediate total internal reflection (TIR) or ray failures on the outer edges of the front elements at fields $\ge 60^\circ$.
- **Conclusion**: Wide-angle admission requires keeping the STOP nested deep behind L3, or utilizing complex negative-meniscus power distributions in L1/L2.

## 3. Naive BFL Compression (CANDIDATE_02 Bending)
- **Attempted Route**: Scaling down rear-group thicknesses to fit within TTL constraints.
- **Bottleneck**: Shrinking elements 5 and 6 reduces the back focal distance. Attempting to maintain the paraxial image height shifts the principal ray convergence point forward, reducing BFL to 2.07 mm, which crashes into the 2.3 mm cover-glass exclusion zone.
- **Conclusion**: Rear-group thickness cannot be reduced independently of the front-group power distribution.
