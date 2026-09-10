# Legacy manual pipeline (July 2026)

These files implement the pre-coordinator workflow based on root-level
`case_*` directories and, in several places, the hard-coded
`initialTrial_92/initialTrial` path. The active finite-radius MOBO workflow does
not call them.

- `root/`: Sobol/CSV case preparation, manual resubmission, particle submission,
  cleanup, and export scripts.
- `base/`: the old mesh generator and manual `latestTime` CFD restart script.
- `baseparticle/`: the old serial `icoUncoupledKinematicParcelFoam` runners.

They are preserved for historical recovery only. The active workflow is
`bo_loop.py` plus `tools/bo_multihost.py` and uses `base/run.sh` and
`baseparticle/loopaerosolDynamics.sh`.
