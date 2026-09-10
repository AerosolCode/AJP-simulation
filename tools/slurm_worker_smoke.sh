#!/bin/bash
#SBATCH --job-name=AJP_env_smoke
#SBATCH --output=slurm_worker_smoke.out
#SBATCH --error=slurm_worker_smoke.err
#SBATCH --ntasks=4
#SBATCH --mem=4000
#SBATCH --time=00:10:00

set -euo pipefail

WORKER_ROOT=${AJP_WORKER_ROOT:-"$HOME/AJP-worker"}
WORKER_ENV=${AJP_WORKER_ENV:-"$WORKER_ROOT/worker-env.sh"}
if [ ! -r "$WORKER_ENV" ]; then
    echo "worker environment not found: $WORKER_ENV" >&2
    exit 2
fi
source "$WORKER_ENV"
set +e
set +u
source "$AJP_OPENFOAM_BASHRC" >/dev/null 2>&1
source_rc=$?
set -euo pipefail
if [ "$source_rc" -ne 0 ]; then
    echo "OpenFOAM environment failed: rc=$source_rc"
    exit "$source_rc"
fi

"$AJP_PYTHON_BIN" -c \
    'import gmsh; gmsh.initialize(); gmsh.model.add("slurm_probe"); gmsh.finalize()'

cd "${AJP_SMOKE_CASE:-$WORKER_ROOT/smoke_case}"
checkMesh > log.checkMesh.slurm 2>&1
grep -q "Mesh OK" log.checkMesh.slurm

mpirun -np "$SLURM_NTASKS" "$AJP_PARTICLE_SOLVER" -help \
    > log.aerosolDynamicsFoam.help.slurm 2>&1
grep -q "Usage: aerosolDynamicsFoam" log.aerosolDynamicsFoam.help.slurm

echo "AJP_WORKER_SMOKE_OK host=$(hostname) tasks=$SLURM_NTASKS"
