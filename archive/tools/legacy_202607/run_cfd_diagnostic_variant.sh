#!/usr/bin/env bash
#SBATCH --output=slurm-diagnostic-%j.out
#SBATCH --error=slurm-diagnostic-%j.err
#SBATCH --ntasks=1
#SBATCH --mem=5000
#SBATCH --time=01:00:00

set -euo pipefail

if [ "$#" -ne 4 ]; then
    echo "usage: $0 SOURCE_CASE DEST_ROOT VARIANT END_TIME" >&2
    exit 2
fi

source_case=$1
dest_root=$2
variant=$3
end_time=$4

worker_env=${AJP_WORKER_ENV:-/home/tamadate/AJP-worker/worker-env.sh}
if [ -r "$worker_env" ]; then
    # shellcheck disable=SC1090
    source "$worker_env"
fi

set +u
set +e
# shellcheck disable=SC1090
source "${AJP_OPENFOAM_BASHRC:-/usr/lib/openfoam/openfoam2406/etc/bashrc}"
source_rc=$?
set -e
set -u
if [ "$source_rc" -ne 0 ]; then
    echo "failed to source OpenFOAM environment (rc=$source_rc)" >&2
    exit "$source_rc"
fi

case_name=$(basename "$source_case")
dest_case="$dest_root/${case_name}_${variant}"
if [ -e "$dest_case" ]; then
    echo "destination already exists: $dest_case" >&2
    exit 2
fi

mkdir -p "$dest_case"
rsync -a \
    --exclude='/[1-9]*/' \
    --exclude='/CFD_DONE' \
    --exclude='/CFD_FAILED' \
    --exclude='/log.*' \
    --exclude='/output*.txt' \
    --exclude='/error*.txt' \
    "$source_case/" "$dest_case/"

cd "$dest_case"

foamDictionary system/controlDict -entry startFrom -set startTime
foamDictionary system/controlDict -entry startTime -set 0
foamDictionary system/controlDict -entry endTime -set "$end_time"
foamDictionary system/controlDict -entry writeInterval -set 100
foamDictionary system/controlDict -entry purgeWrite -set 0

set_standard_simple()
{
    foamDictionary system/fvSolution -entry SIMPLE/consistent -set no
    foamDictionary system/fvSolution -entry relaxationFactors -set \
        '{ fields { p 0.3; } equations { U 0.7; k 0.7; omega 0.7; } }'
}

set_relaxed_simple()
{
    foamDictionary system/fvSolution -entry SIMPLE/consistent -set no
    foamDictionary system/fvSolution -entry relaxationFactors -set \
        '{ fields { p 0.2; } equations { U 0.3; k 0.3; omega 0.3; } }'
}

case "$variant" in
    laminar)
        foamDictionary constant/turbulenceProperties -entry simulationType -set laminar
        ;;
    simple_toggle_only)
        foamDictionary system/fvSolution -entry SIMPLE/consistent -set no
        ;;
    simplec_standard)
        foamDictionary system/fvSolution -entry SIMPLE/consistent -set yes
        foamDictionary system/fvSolution -entry relaxationFactors -set \
            '{ fields { p 0.3; } equations { U 0.7; k 0.7; omega 0.7; } }'
        ;;
    simplec_no_p)
        foamDictionary system/fvSolution -entry SIMPLE/consistent -set yes
        foamDictionary system/fvSolution -entry relaxationFactors -set \
            '{ equations { U 0.7; k 0.7; omega 0.7; } }'
        ;;
    simple_standard)
        set_standard_simple
        ;;
    simple_relaxed)
        set_relaxed_simple
        ;;
    *)
        echo "unknown diagnostic variant: $variant" >&2
        exit 2
        ;;
esac

{
    echo "source_case=$source_case"
    echo "variant=$variant"
    echo "end_time=$end_time"
    echo "host=$(hostname)"
    echo "started_at=$(date --iso-8601=seconds)"
} > diagnostic_summary.txt

set +e
simpleFoam > log.simpleFoam 2>&1
solver_rc=$?
set -e

last_iteration=$(awk '/^Time = / {value=$3} END {print value}' log.simpleFoam)
clean_end=no
if tail -n 50 log.simpleFoam | grep -q '^End'; then
    clean_end=yes
fi

{
    echo "solver_rc=$solver_rc"
    echo "last_iteration=${last_iteration:-none}"
    echo "clean_end=$clean_end"
    echo "finished_at=$(date --iso-8601=seconds)"
} >> diagnostic_summary.txt

exit "$solver_rc"
