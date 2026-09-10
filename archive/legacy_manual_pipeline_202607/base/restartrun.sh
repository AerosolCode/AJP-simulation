#!/bin/bash
#SBATCH --output=output_restart.txt
#SBATCH --error=error_restart.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000
#SBATCH --time=04:00:00

set -e
WORKER_ENV=${AJP_WORKER_ENV:-/home/tamadate/AJP-worker/worker-env.sh}
if [ -r "$WORKER_ENV" ]; then
    source "$WORKER_ENV"
fi
set +u
set +e
source "${AJP_OPENFOAM_BASHRC:-/usr/lib/openfoam/openfoam2406/etc/bashrc}"
source_rc=$?
set -e
if [ "$source_rc" -ne 0 ]; then
    echo "[restart] failed to source OpenFOAM bashrc (rc=$source_rc)"
    exit "$source_rc"
fi
set -euo pipefail
CFD_MAX_U_MAG=${AJP_CFD_MAX_U_MAG:-10000}

latest_numeric_dir()
{
    find . -maxdepth 1 -type d \
        | sed 's#^\./##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1
}

check_cfd_velocity_field()
{
    local latest_time
    latest_time=$(latest_numeric_dir)
    if [ -z "$latest_time" ]; then
        echo "[restart] no CFD time directory found"
        return 1
    fi

    local check_log="log.fieldMinMax.U"
    if ! postProcess -time "$latest_time" -func "fieldMinMax(U)" -noFunctionObjects > "$check_log" 2>&1; then
        echo "[restart] failed to inspect U field at time $latest_time"
        cat "$check_log"
        return 1
    fi

    local max_u
    max_u=$(awk '/max\(mag\(U\)\)/ {print $3; exit}' "$check_log")
    if [ -z "$max_u" ]; then
        echo "[restart] failed to parse max(mag(U)) at time $latest_time"
        cat "$check_log"
        return 1
    fi
    if ! awk -v u="$max_u" -v limit="$CFD_MAX_U_MAG" 'BEGIN{exit !((u + 0) >= 0 && (u + 0) <= limit)}'; then
        echo "[restart] invalid CFD U field at time $latest_time: max(mag(U))=$max_u exceeds limit=$CFD_MAX_U_MAG"
        cat "$check_log"
        return 1
    fi

    echo "[restart] CFD U field sanity OK at time $latest_time: max(mag(U))=$max_u"
}

echo "[restart] OpenFOAM sourced"
echo "[restart] python3=$(command -v python3 || true)"
echo "[restart] gmsh=$(command -v gmsh || true)"
echo "[restart] gmshToFoam=$(command -v gmshToFoam || true)"

CASE_NAME=$(basename "$PWD")
scontrol update JobId=$SLURM_JOB_ID JobName=$CASE_NAME

echo "Restarting simpleFoam for $CASE_NAME"
echo "Case directory: $PWD"
rm -f CFD_DONE CFD_FAILED

# latestTime から再開
sed -i 's/startFrom[[:space:]]\+.*;/startFrom       latestTime;/' system/controlDict

# 最新時刻を確認
latest_time=$(find . -maxdepth 1 -type d \
    | sed 's#^\./##' \
    | grep -E '^[0-9]+(\.[0-9]+)?$' \
    | sort -g \
    | tail -1)

echo "Latest time directory: $latest_time"

if [ -z "$latest_time" ] || [ "$latest_time" = "0" ]; then
    echo "No restart time found. Abort restart."
    exit 1
fi

touch "${CASE_NAME}.foam"

if ! simpleFoam > log.simpleFoam.restart 2>&1; then
    echo "[restart] simpleFoam failed"
    touch CFD_FAILED
    exit 1
fi

if ! tail -n 50 log.simpleFoam.restart | grep -q '^End'; then
    echo "[restart] simpleFoam restart log did not end cleanly"
    touch CFD_FAILED
    exit 1
fi

if ! check_cfd_velocity_field; then
    touch CFD_FAILED
    exit 1
fi

touch CFD_DONE

echo "$CASE_NAME restart finished"
