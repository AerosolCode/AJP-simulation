#!/bin/bash
#SBATCH --output=output.txt
#SBATCH --error=error.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000
#SBATCH --time=04:00:00

set -euo pipefail
finish_cfd()
{
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        rm -f CFD_DONE
        touch CFD_FAILED
    fi
}
trap finish_cfd EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
echo "[run] script start"
# The submitting shell supplies OpenFOAM and Python through the Slurm environment.
CFD_MAX_U_MAG=${AJP_CFD_MAX_U_MAG:-10000}
MESH_MAX_NODES=${AJP_MAX_MESH_NODES:-120000}
MESH_MAX_ELEMENTS=${AJP_MAX_MESH_ELEMENTS:-360000}
PYTHON_BIN=${AJP_PYTHON_BIN:-python3}
for required_command in "$PYTHON_BIN" gmshToFoam potentialFoam simpleFoam postProcess; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "[run] required command unavailable: $required_command. Prepare the environment before submitting the job." >&2
        exit 127
    fi
done
if ! "$PYTHON_BIN" -c 'import gmsh'; then
    echo "[run] the selected Python must provide the gmsh module: $PYTHON_BIN" >&2
    exit 1
fi

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
        echo "[run] no CFD time directory found"
        return 1
    fi

    local check_log="log.fieldMinMax.U"
    if ! postProcess -time "$latest_time" -func "fieldMinMax(U)" -noFunctionObjects > "$check_log" 2>&1; then
        echo "[run] failed to inspect U field at time $latest_time"
        cat "$check_log"
        return 1
    fi

    local max_u
    max_u=$(awk '/max\(mag\(U\)\)/ {print $3; exit}' "$check_log")
    if [ -z "$max_u" ]; then
        echo "[run] failed to parse max(mag(U)) at time $latest_time"
        cat "$check_log"
        return 1
    fi
    if ! awk -v u="$max_u" -v limit="$CFD_MAX_U_MAG" 'BEGIN{exit !((u + 0) >= 0 && (u + 0) <= limit)}'; then
        echo "[run] invalid CFD U field at time $latest_time: max(mag(U))=$max_u exceeds limit=$CFD_MAX_U_MAG"
        cat "$check_log"
        return 1
    fi

    echo "[run] CFD U field sanity OK at time $latest_time: max(mag(U))=$max_u"
}

mesh_count_after_section()
{
    local section="$1"
    awk -v section="$section" '
        $0 == section {
            if (getline value > 0) {
                print value
                exit
            }
        }
    ' meshData.msh
}

check_mesh_size()
{
    local nodes
    local elements
    nodes=$(mesh_count_after_section '$Nodes')
    elements=$(mesh_count_after_section '$Elements')
    if [ -z "$nodes" ] || [ -z "$elements" ]; then
        echo "[run] failed to parse mesh size from meshData.msh"
        return 1
    fi
    echo "[run] mesh size: nodes=$nodes elements=$elements limits nodes=$MESH_MAX_NODES elements=$MESH_MAX_ELEMENTS"
    if [ "$nodes" -gt "$MESH_MAX_NODES" ] || [ "$elements" -gt "$MESH_MAX_ELEMENTS" ]; then
        echo "[run] mesh exceeds configured size limit"
        return 1
    fi
}

echo "[run] using inherited OpenFOAM environment: ${WM_PROJECT_DIR:-PATH}"
echo "[run] python=$PYTHON_BIN"
echo "[run] gmsh=$(command -v gmsh || true)"
echo "[run] gmshToFoam=$(command -v gmshToFoam || true)"
echo "[run] mesh limits: nodes=$MESH_MAX_NODES elements=$MESH_MAX_ELEMENTS"
echo "[run] starting mesh generation"
rm -f CFD_DONE CFD_FAILED
find . -maxdepth 1 -type d \
    | sed 's#^\./##' \
    | grep -E '^[0-9]+(\.[0-9]+)?$' \
    | grep -vx '0' \
    | while read -r time_dir; do
        rm -rf "$time_dir"
        echo "[run] removed stale time directory: $time_dir"
    done || true

"$PYTHON_BIN" meshGen2.py
if ! check_mesh_size; then
    touch CFD_FAILED
    exit 1
fi

echo "[run] converting mesh"
gmshToFoam meshData.msh > log.gmshToFoam 2>&1

echo "[run] updating boundary conditions"
"$PYTHON_BIN" changeBCType.py
"$PYTHON_BIN" BC_omega.py
"$PYTHON_BIN" BC_U.py

echo "[run] running potentialFoam"
touch log.potentialFoam
if ! potentialFoam -initialiseUBCs -writep > log.potentialFoam 2>&1; then
    echo "[run] potentialFoam failed"
    touch CFD_FAILED
    exit 1
fi
if ! tail -n 50 log.potentialFoam | grep -q '^End'; then
    echo "[run] potentialFoam log did not end cleanly"
    touch CFD_FAILED
    exit 1
fi

CASE_NAME=$(basename "$PWD")
touch "${CASE_NAME}.foam"

echo "Running simpleFoam for $CASE_NAME"

echo "[run] running simpleFoam"
touch log.simpleFoam

if ! simpleFoam > log.simpleFoam 2>&1; then
    echo "[run] simpleFoam failed"
    touch CFD_FAILED
    exit 1
fi

if ! tail -n 50 log.simpleFoam | grep -q '^End'; then
    echo "[run] simpleFoam log did not end cleanly"
    touch CFD_FAILED
    exit 1
fi

if ! check_cfd_velocity_field; then
    touch CFD_FAILED
    exit 1
fi

touch CFD_DONE

echo "$CASE_NAME finished"
