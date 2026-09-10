# July 2026 generated-case archive

This directory contains 2.9 GB of generated OpenFOAM validation output that
was formerly under `test_cases/`. It is historical evidence, not production
input, and no active workflow reads it.

Contents:

- `bo_case_0044/`, `bo_case_0149/`: two historical BO cases used for CFD and
  particle-tracking diagnosis (about 91 MB combined).
- `structured_mesh_test/`: one full midpoint mesh/CFD case (about 28 MB). Its
  old `potentialFoam` log predates the `-initialiseUBCs` fix.
- `structured_mesh_sweep*/`: 22 mesh-development sweeps (about 2.7 GB),
  including intermediate algorithm, sheath-region, wedge-angle, and hybrid
  meshing trials. Names containing `unstructured` describe rejected local
  meshing experiments; they are not active production modes.
- `structured_random_operational_10/`: ten random structured cases with
  `checkMesh` and short `simpleFoam` evidence (about 114 MB).

The most useful compact evidence is each sweep's `summary.csv`. The final
edge/random checks referenced by the project report are in
`structured_mesh_sweep_sheath_cavity_6edge_wedge5/summary.csv` and
`structured_random_operational_10/summary.csv`.

New generated validation cases belong in the active `test_cases/` directory.
