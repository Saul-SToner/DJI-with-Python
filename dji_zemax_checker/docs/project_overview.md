# Project Overview: Zemax Wide-Angle Lens Structure Search Workflow

This repository serves as a personal learning and research archive documenting the automation workflow for wide-angle lens structural searches in Zemax OpticStudio using ZOS-API.

## Core Workflow Stages

1. **Candidate Intake**: CSV prescriptions of candidate designs are parsed from literature or patents.
2. **Reconstruction**: Native sequential `.ZOS` files are generated headlessly using exact model glass solves (`nd`/`vd`) and even-aspheric configurations (up to 16th order).
3. **Mechanical and Geometric Auditing**: Clear aperture sags, center thicknesses, air gaps, and edge thicknesses are checked recursively against target physical limits.
4. **Ray Tracing & Vignetting Analysis**: Normalized field angles are traced under F/2.5 or stage-dependent F-numbers with Real Ray Aiming to isolate trace failures or clipping.
5. **Failure Localization**: Identifies which surfaces violate boundary conditions or trigger trace aborts (e.g. edge pupil vignetting or stop clipping).
6. **Data Preparation**: Processed metrics are exported into structured tables to prepare clean training data for future machine learning screening pipelines.

## Standalone Connection Architecture

The scripts utilize Python's `zospy` library to interface with the ZOS-API in headless `standalone` mode, which launches a background OpticStudio process and allows fully automated system building, editing, and parameter retrieval without GUI thread overhead.
