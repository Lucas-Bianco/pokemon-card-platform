"""Honest authenticity tooling for scanned cards.

This package does NOT do image-forensic counterfeit detection. That premise was
tested and disproven on this dataset: halftone rosette (FFT), holographic
coverage, edge sharpness, and color-delta-vs-catalog are all unmeasurable from
the 600x825 rectified phone-photo crops the pipeline produces, and the project
has zero confirmed-counterfeit samples to calibrate against anyway.

What it does instead mirrors the Grading Studio: measure the one signal that IS
honestly computable from existing data (the printed collector number OCR read
vs the catalog number of the recognized card — see ``consistency``), and surface
the rest as a transparent, user-driven physical checklist (see ``checklist``).
Never a fake/real verdict — only honest signals and honest caveats.
"""