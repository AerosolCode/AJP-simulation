#!/bin/bash
#SBATCH --output=output_particle.txt
#SBATCH --error=error_particle.txt
#SBATCH --ntasks=4
#SBATCH --mem=8000
#SBATCH --time=02:00:00

set -euo pipefail
finish_particle()
{
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        rm -f PARTICLE_DONE
        touch PARTICLE_FAILED
    fi
}
trap finish_particle EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

echo "[particle] script start"
# The submitting shell supplies OpenFOAM, the solver, and Python through Slurm.
PYTHON_BIN=${AJP_PYTHON_BIN:-python3}
for required_command in "$PYTHON_BIN" foamFormatConvert checkMesh postProcess; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "[particle] required command unavailable: $required_command. Prepare the environment before submitting the job." >&2
        exit 127
    fi
done
echo "[particle] using inherited OpenFOAM environment: ${WM_PROJECT_DIR:-PATH}"

CASE_NAME=$(basename "$(dirname "$PWD")")
CASE_NUM=$(echo "$CASE_NAME" | sed 's/case_//')
CASE_DIR=${SLURM_SUBMIT_DIR:-$PWD}

echo "Aerosol dynamics loop for $CASE_NAME"
echo "Directory: $PWD"
echo "Host: $(hostname)"

# =========================================================
# settings
# =========================================================

INJECTION_POINTS=${AJP_INJECTION_POINTS:-100}
TOTAL_PARTICLES=${AJP_TOTAL_PARTICLES:-$((INJECTION_POINTS * 10))}
TARGET_RATIO=${AJP_TARGET_RATIO:-0.95}
CHUNK=${AJP_CHUNK:-0.1}
MAX_TIME_SETTING=${AJP_MAX_TIME:-auto}
MAX_TIME_FACTOR=${AJP_MAX_TIME_FACTOR:-3.0}
MAX_TIME_MIN=${AJP_MAX_TIME_MIN:-0.5}
MAX_TIME_MAX=${AJP_MAX_TIME_MAX:-5.0}
DELTA_T=${AJP_DELTA_T:-1e-4}
MAX_U_MAG=${AJP_MAX_U_MAG:-10000}
LOG_TAIL_LINES=${AJP_LOG_TAIL_LINES:-400}
KEEP_FULL_LOG=${AJP_KEEP_FULL_PARTICLE_LOG:-0}
echo "[particle] injection_points=$INJECTION_POINTS total_particles=$TOTAL_PARTICLES"

SOLVER=${AJP_PARTICLE_SOLVER:-}
if [ -z "$SOLVER" ]; then
    if command -v aerosolDynamicsFoam >/dev/null 2>&1; then
        SOLVER=$(command -v aerosolDynamicsFoam)
    elif command -v aerosolEulerFoam >/dev/null 2>&1; then
        SOLVER=$(command -v aerosolEulerFoam)
    fi
fi
if [ -n "$SOLVER" ]; then
    requested_solver=$SOLVER
    SOLVER=$(command -v "$requested_solver" || true)
    if [ -z "$SOLVER" ] || [ ! -x "$SOLVER" ]; then
        echo "[particle] requested solver unavailable: $requested_solver" >&2
        exit 127
    fi
fi
LOG=${AJP_PARTICLE_LOG:-log.aerosolDynamicsFoam}

NPROCS=${SLURM_NTASKS:-${AJP_PARTICLE_NPROCS:-4}}
PARALLEL_LAUNCHER=${AJP_PARALLEL_LAUNCHER:-mpirun}

WRITE_INTERVAL=$(awk -v c="$CHUNK" -v dt="$DELTA_T" 'BEGIN{printf "%d", c/dt}')
POST_BASE_DIR="postProcessing/lagrangian"

if [ -z "$SOLVER" ] || [ ! -x "$SOLVER" ]; then
    echo "[particle] no particle solver found in PATH. Prepare aerosolDynamicsFoam or set AJP_PARTICLE_SOLVER before submission." >&2
    exit 127
fi

echo "[particle] solver=$SOLVER"
echo "[particle] log_tail_lines=$LOG_TAIL_LINES keep_full_log=$KEEP_FULL_LOG"

if [ "$PARALLEL_LAUNCHER" = "mpirun" ]; then
    if command -v mpirun >/dev/null 2>&1; then
        RUN_CMD=(mpirun -np "$NPROCS")
    elif command -v srun >/dev/null 2>&1; then
        RUN_CMD=(srun -n "$NPROCS")
    else
        echo "Neither mpirun nor srun was found."
        exit 127
    fi
elif [ "$PARALLEL_LAUNCHER" = "srun" ]; then
    if ! command -v srun >/dev/null 2>&1; then
        echo "[particle] requested launcher unavailable: srun" >&2
        exit 127
    fi
    RUN_CMD=(srun -n "$NPROCS")
else
    echo "Unsupported AJP_PARALLEL_LAUNCHER=$PARALLEL_LAUNCHER"
    exit 2
fi

echo "[particle] launcher=${RUN_CMD[*]}"

HORIZON_TOOL=${AJP_PARTICLE_HORIZON_TOOL:-$CASE_DIR/particle_horizon.py}
HORIZON_OUTPUT=$(
    "$PYTHON_BIN" "$HORIZON_TOOL" ../params.dat \
        --factor "$MAX_TIME_FACTOR" \
        --min "$MAX_TIME_MIN" \
        --max "$MAX_TIME_MAX"
)
read -r AUTO_MAX_TIME INLET_VELOCITY_MPS AXIAL_LENGTH_M NOMINAL_TRANSIT_S \
    <<< "$HORIZON_OUTPUT"
if [ "$MAX_TIME_SETTING" = "auto" ]; then
    MAX_TIME_MODE=auto
    MAX_TIME=$AUTO_MAX_TIME
else
    if ! awk -v value="$MAX_TIME_SETTING" \
        'BEGIN{exit !((value + 0) > 0 && value ~ /^[0-9.eE+-]+$/)}'; then
        echo "[particle] invalid AJP_MAX_TIME=$MAX_TIME_SETTING"
        exit 2
    fi
    MAX_TIME_MODE=fixed
    MAX_TIME=$MAX_TIME_SETTING
fi
echo "[particle] horizon mode=$MAX_TIME_MODE max_time=$MAX_TIME"
echo "[particle] nominal inlet velocity=$INLET_VELOCITY_MPS m/s axial_length=$AXIAL_LENGTH_M m transit=$NOMINAL_TRANSIT_S s"

CFD_TIME=$("$PYTHON_BIN" "$CASE_DIR/cfd_fields.py" ..)
echo "[particle] carrier CFD time=$CFD_TIME"

# =========================================================
# prepare initial particle case
# =========================================================

rm -rf processor*
echo "[particle] cleared old processor dirs"
find . -maxdepth 1 -type d \
    | sed 's#^\./##' \
    | grep -E '^[0-9]+(\.[0-9]+)?$' \
    | grep -vx '0' \
    | while read -r time_dir; do
        rm -rf "$time_dir"
        echo "[particle] removed stale time directory: $time_dir"
    done || true
rm -rf 0
cp -r "../$CFD_TIME" 0 || {
    echo "Failed to copy ../$CFD_TIME to 0"
    exit 1
}
echo "[particle] copied $CFD_TIME -> 0"
rm -f 0/uniform/time

rm -rf constant/polyMesh
cp -r ../constant/polyMesh constant/ || {
    echo "Failed to copy polyMesh"
    exit 1
}
echo "[particle] copied polyMesh"

sed -i 's/writeFormat[[:space:]]\+.*;/writeFormat     ascii;/' system/controlDict
sed -i 's/writeCompression[[:space:]]\+.*;/writeCompression off;/' system/controlDict
if ! foamFormatConvert -time 0 -noConstant > log.foamFormatConvert 2>&1; then
    echo "[particle] foamFormatConvert failed"
    cat log.foamFormatConvert
    exit 1
fi
find 0 -type f -name '*.gz' -exec gunzip -f {} +
echo "[particle] converted time 0 fields to ascii"

if ! checkMesh -constant > log.checkMesh.particle 2>&1; then
    echo "[particle] checkMesh command failed"
    cat log.checkMesh.particle
    exit 1
fi
if ! grep -q "Mesh has 2 geometric (non-empty/wedge) directions" \
    log.checkMesh.particle; then
    echo "[particle] mesh is not recognized as a reduced-dimensional wedge"
    cat log.checkMesh.particle
    exit 3
fi
echo "[particle] retained wedge patches; reduced-dimensional mesh check OK"

touch "p_${CASE_NUM}.foam"
echo "[particle] touch foam marker"

rm -f "$LOG"
rm -f PARTICLE_DONE PARTICLE_FAILED
rm -f PARTICLE_STATUS.txt
echo "patch,time,currentProc,coord0,coord1,coord2,coord3,x,y,z,celli,tetFacei,tetPti,facei,stepFraction,origProc,origId,active,typeId,nParticle,d,dTarget,Ux,Uy,Uz,rho,age,tTurb,UTurbx,UTurby,UTurbz,UCorrectx,UCorrecty,UCorrectz,fx,fy,fz,angularMomentumx,angularMomentumy,angularMomentumz,torquex,torquey,torquez" > particle_fates_all.csv
rm -rf "$POST_BASE_DIR"
rm -rf processor*
echo "[particle] cleared old outputs"

# =========================================================
# controlDict and decomposition
# =========================================================

sed -i 's/startFrom[[:space:]]\+.*;/startFrom       latestTime;/' system/controlDict
sed -i 's/writeControl[[:space:]]\+.*;/writeControl    timeStep;/' system/controlDict
sed -i "s/writeInterval[[:space:]]\+.*;/writeInterval   $WRITE_INTERVAL;/" system/controlDict
sed -i 's/writeAtEnd[[:space:]]\+.*;/writeAtEnd      yes;/' system/controlDict
sed -i 's/purgeWrite[[:space:]]\+.*;/purgeWrite      2;/' system/controlDict
echo "[particle] controlDict prepared"

make_positions_file()
{
    local positions_file="constant/kinematicCloudPositions"
    local n_positions="$INJECTION_POINTS"

    "$PYTHON_BIN" - "$positions_file" "$n_positions" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path


def load_kv(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


positions_path = Path(sys.argv[1])
n_positions = max(int(sys.argv[2]), 1)
p = load_kv("../params.dat")

rin_m = float(p["Rin_mm"]) * 1e-3
t_m = float(p["t_mm"]) * 1e-3
l0_m = float(p["L0_mm"]) * 1e-3
l1_m = float(p["L1_mm"]) * 1e-3
l2_m = float(p["L2_mm"]) * 1e-3
l4_m = float(p["L4_mm"]) * 1e-3

# inletAerosol is the top inlet plane at y = t + L0 + L1 + L2 + L4.
# Place parcels just inside that plane and distribute them over the radius.
y = t_m + l0_m + l1_m + l2_m + l4_m - 1.0e-6
z = 0.0

positions_path.parent.mkdir(parents=True, exist_ok=True)
with positions_path.open("w") as f:
    f.write("FoamFile\n")
    f.write("{\n")
    f.write("    version     2.0;\n")
    f.write("    format      ascii;\n")
    f.write("    class       vectorField;\n")
    f.write('    object      kinematicCloudPositions;\n')
    f.write("}\n")
    f.write(f"{n_positions}\n")
    f.write("(\n")
    for i in range(n_positions):
        frac = (float(i) + 0.5) / float(n_positions)
        x = 0.98 * rin_m * frac**0.5
        f.write(f"({x:.12e} {y:.12e} {z:.12e})\n")
    f.write(")\n")
PY
    echo "[particle] wrote ${positions_file} with ${n_positions} positions"
}

make_positions_file
{
    echo "injection_points=$INJECTION_POINTS"
    echo "total_particles=$TOTAL_PARTICLES"
    echo "target_ratio=$TARGET_RATIO"
    echo "chunk=$CHUNK"
    echo "max_time_mode=$MAX_TIME_MODE"
    echo "max_time=$MAX_TIME"
    echo "max_time_factor=$MAX_TIME_FACTOR"
    echo "max_time_min=$MAX_TIME_MIN"
    echo "max_time_max=$MAX_TIME_MAX"
    echo "inlet_velocity_mps=$INLET_VELOCITY_MPS"
    echo "axial_length_m=$AXIAL_LENGTH_M"
    echo "nominal_transit_s=$NOMINAL_TRANSIT_S"
    echo "delta_t=$DELTA_T"
    echo "analytic_position_tracking=true"
} > particle_run_config.txt

check_velocity_field()
{
    local check_log="log.fieldMinMax.U"
    if ! postProcess -time 0 -func "fieldMinMax(U)" -noFunctionObjects > "$check_log" 2>&1; then
        echo "[particle] failed to inspect U field"
        cat "$check_log"
        exit 1
    fi

    local max_u
    max_u=$(awk '/max\(mag\(U\)\)/ {print $3; exit}' "$check_log")
    if [ -z "$max_u" ]; then
        echo "[particle] failed to parse max(mag(U))"
        echo "invalid U field max=parse_failed" > PARTICLE_STATUS.txt
        cat "$check_log"
        exit 3
    fi
    if ! awk -v u="$max_u" -v limit="$MAX_U_MAG" 'BEGIN{exit !((u + 0) >= 0 && (u + 0) <= limit)}'; then
        echo "[particle] invalid U field: max(mag(U))=$max_u exceeds limit=$MAX_U_MAG"
        echo "invalid U field max=$max_u limit=$MAX_U_MAG" > PARTICLE_STATUS.txt
        cat "$check_log"
        exit 3
    fi
    echo "[particle] U field sanity OK: max(mag(U))=$max_u"
}

check_velocity_field

# =========================================================
# functions
# =========================================================

latest_numeric_dir()
{
    local root="$1"
    [ -d "$root" ] || return
    find "$root" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1
}

cleanup_old_time_dirs_in()
{
    local root="$1"
    [ -d "$root" ] || return

    times=$(find "$root" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g)

    keep=$(echo "$times" | tail -2)

    for t in $times; do
        if [ "$t" = "0" ]; then
            continue
        fi

        echo "$keep" | grep -qx "$t" && continue

        rm -rf "$root/$t"
        echo "Removed old time directory: $root/$t"
    done
}

cleanup_old_time_dirs()
{
    cleanup_old_time_dirs_in "."
}

copy_carrier_fields_to_time()
{
    local time_dir="$1"
    [ -n "$time_dir" ] || return
    [ "$time_dir" = "0" ] && return
    [ -d "$time_dir" ] || return

    for field in 0/*; do
        [ -e "$field" ] || continue
        local name
        name=$(basename "$field")
        if [ "$name" = "uniform" ]; then
            continue
        fi
        cp -a "$field" "$time_dir/"
    done
    echo "[particle] copied carrier fields from 0 to $time_dir"
}

cleanup_old_postprocessing_dirs_in()
{
    local root="$1"
    local base="$root"
    [ -d "$base" ] || return

    for func in outletParticles wallSubstrateParticles wallUpper wallDown wallCavity finiteRadiusWall; do
        func_dir="$base/$func"
        [ -d "$func_dir" ] || continue

        times=$(find "$func_dir" -maxdepth 1 -type d \
            | sed 's#.*/##' \
            | grep -E '^[0-9]+(\.[0-9]+)?$' \
            | sort -g)

        keep=$(echo "$times" | tail -2)

        for t in $times; do
            echo "$keep" | grep -qx "$t" && continue

            rm -rf "$func_dir/$t"
            echo "Removed old postProcessing directory: $func_dir/$t"
        done
    done
}

cleanup_old_postprocessing_dirs()
{
    for shard_dir in "$POST_BASE_DIR"/kinematicCloud_shard*; do
        [ -d "$shard_dir" ] || continue
        cleanup_old_postprocessing_dirs_in "$shard_dir"
    done
}

append_patch_to_all_csv()
{
    local func_dir="$1"
    local dat_name="$2"
    local patch_name="$3"
    local out_csv="particle_fates_all.csv"

    if [ ! -d "$func_dir" ]; then
        return
    fi

    local latest_dir
    latest_dir=$(latest_numeric_dir "$func_dir")

    if [ -z "$latest_dir" ]; then
        return
    fi

    local file="$func_dir/$latest_dir/$dat_name"

    if [ ! -f "$file" ]; then
        return
    fi

    if [ ! -f "$out_csv" ]; then
        echo "patch,time,currentProc,coord0,coord1,coord2,coord3,x,y,z,celli,tetFacei,tetPti,facei,stepFraction,origProc,origId,active,typeId,nParticle,d,dTarget,Ux,Uy,Uz,rho,age,tTurb,UTurbx,UTurby,UTurbz,UCorrectx,UCorrecty,UCorrectz,fx,fy,fz,angularMomentumx,angularMomentumy,angularMomentumz,torquex,torquey,torquez" > "$out_csv"
    fi

    tail -n +2 "$file" | awk -v p="$patch_name" '
    NF > 0 {
        for (i = 1; i <= NF; i++) {
            gsub(/\(/, "", $i)
            gsub(/\)/, "", $i)
            gsub(/"/, "", $i)
        }

        if (NF >= 33) {
            print p "," \
                  $1 "," $2 "," \
                  $3 "," $4 "," $5 "," $6 "," \
                  $7 "," $8 "," $9 "," \
                  $10 "," $11 "," $12 "," $13 "," $14 "," \
                  $15 "," $16 "," $17 "," $18 "," $19 "," \
                  $20 "," $21 "," \
                  $22 "," $23 "," $24 "," \
                  $25 "," $26 "," $27 "," \
                  $28 "," $29 "," $30 "," \
                  $31 "," $32 "," $33 ",,,,,,,,,"
        }
    }' >> "$out_csv"

    {
        head -n 1 "$out_csv"
        tail -n +2 "$out_csv" | sort -u
    } > "${out_csv}.tmp"

    mv "${out_csv}.tmp" "$out_csv"
}

append_patch_from_all_sources()
{
    local rel_dir="$1"
    local dat_name="$2"
    local patch_name="$3"

    for shard_dir in "$POST_BASE_DIR"/kinematicCloud_shard*; do
        [ -d "$shard_dir" ] || continue
        append_patch_to_all_csv "$shard_dir/$rel_dir" "$dat_name" "$patch_name"
    done
}

append_finite_radius_to_all_csv()
{
    local func_dir="$1"
    local out_csv="particle_fates_all.csv"

    [ -d "$func_dir" ] || return

    local latest_dir
    latest_dir=$(find "$func_dir" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1)
    [ -n "$latest_dir" ] || return

    if [ ! -f "$out_csv" ]; then
        echo "patch,time,currentProc,coord0,coord1,coord2,coord3,x,y,z,celli,tetFacei,tetPti,facei,stepFraction,origProc,origId,active,typeId,nParticle,d,dTarget,Ux,Uy,Uz,rho,age,tTurb,UTurbx,UTurby,UTurbz,UCorrectx,UCorrecty,UCorrectz,fx,fy,fz,angularMomentumx,angularMomentumy,angularMomentumz,torquex,torquey,torquez" > "$out_csv"
    fi

    local file
    for file in "$func_dir/$latest_dir"/finiteRadiusDeposition*.dat; do
        [ -f "$file" ] || continue
        awk '
        !/^#/ && NF >= 16 {
            print $3 "," $1 "," $2 ",,,,," \
                  $11 "," $12 "," $13 ",,,," $4 ",," \
                  $5 "," $6 ",0," $7 "," $8 "," $9 "," $9 \
                  ",,,,,,,,,,,,,,,,,,,,,"
        }' "$file" >> "$out_csv"
    done

    {
        head -n 1 "$out_csv"
        tail -n +2 "$out_csv" | sort -u
    } > "${out_csv}.tmp"
    mv "${out_csv}.tmp" "$out_csv"
}

append_finite_radius_from_all_sources()
{
    for shard_dir in "$POST_BASE_DIR"/kinematicCloud_shard*; do
        [ -d "$shard_dir" ] || continue
        append_finite_radius_to_all_csv "$shard_dir/finiteRadiusWall"
    done
}

# =========================================================
# loop
# =========================================================

while true
do
    echo "[particle] loop begin"
    latest_time=$(latest_numeric_dir "." || true)
    if [ -z "$latest_time" ]; then
        latest_time=0
    fi
echo "[particle] latest_time=$latest_time"

    next_time=$(awk -v t="$latest_time" -v c="$CHUNK" 'BEGIN{printf "%.6f", t+c}')

    over_max=$(awk -v n="$next_time" -v m="$MAX_TIME" 'BEGIN{print (n > m) ? 1 : 0}')
    if [ "$over_max" -eq 1 ]; then
        next_time="$MAX_TIME"
    fi

    echo "========================================"
    echo "Running $SOLVER in parallel: $latest_time -> $next_time"
    echo "nProcs: $NPROCS"
    echo "Launcher: ${RUN_CMD[*]}"
    echo "========================================"

    sed -i "s/endTime[[:space:]]\+.*;/endTime         $next_time;/" system/controlDict

    chunk_log="${LOG}.chunk"
    set +e
    if [ "$KEEP_FULL_LOG" = "1" ]; then
        "${RUN_CMD[@]}" "$SOLVER" -particleParallel -nParticleShards "$NPROCS" >> "$LOG" 2>&1
        solver_rc=$?
    else
        "${RUN_CMD[@]}" "$SOLVER" -particleParallel -nParticleShards "$NPROCS" > "$chunk_log" 2>&1
        solver_rc=$?
        {
            echo
            echo "===== solver output tail for $latest_time -> $next_time rc=$solver_rc ====="
            tail -n "$LOG_TAIL_LINES" "$chunk_log"
        } >> "$LOG"
        rm -f "$chunk_log"
    fi
    set -e

    if [ "$solver_rc" -ne 0 ]; then
        echo "$SOLVER failed at endTime=$next_time"
        echo "failed at $next_time" > PARTICLE_STATUS.txt
        exit 1
    fi

    written_time=$(latest_numeric_dir "." || true)
    copy_carrier_fields_to_time "$written_time"

    set +e
    append_patch_from_all_sources "outletParticles" "outlet.dat" "outlet"
    append_patch_from_all_sources "wallSubstrateParticles" "wallSubstrate.dat" "wallSubstrate"
    append_patch_from_all_sources "wallUpper" "wallUpper.dat" "wallUpper"
    append_patch_from_all_sources "wallDown" "wallDown.dat" "wallDown"
    append_patch_from_all_sources "wallCavity" "wallCavity.dat" "wallCavity"
    append_finite_radius_from_all_sources

    if [ -f particle_fates_all.csv ]; then
        N_OUTLET=$(awk -F, 'NR>1 && $1=="outlet"{n++} END{print n+0}' particle_fates_all.csv)
        N_SUBSTRATE=$(awk -F, 'NR>1 && $1=="wallSubstrate"{n++} END{print n+0}' particle_fates_all.csv)
        N_UPPER=$(awk -F, 'NR>1 && $1=="wallUpper"{n++} END{print n+0}' particle_fates_all.csv)
        N_DOWN=$(awk -F, 'NR>1 && $1=="wallDown"{n++} END{print n+0}' particle_fates_all.csv)
        N_CAVITY=$(awk -F, 'NR>1 && $1=="wallCavity"{n++} END{print n+0}' particle_fates_all.csv)
    else
        N_OUTLET=0
        N_SUBSTRATE=0
        N_UPPER=0
        N_DOWN=0
        N_CAVITY=0
    fi

    N_RESOLVED=$((N_OUTLET + N_SUBSTRATE + N_UPPER + N_DOWN + N_CAVITY))

    resolved_ratio=$(awk -v n="$N_RESOLVED" -v total="$TOTAL_PARTICLES" \
        'BEGIN{printf "%.6f", n / total}')

    echo "Outlet        : $N_OUTLET"
    echo "wallSubstrate : $N_SUBSTRATE"
    echo "wallUpper     : $N_UPPER"
    echo "wallDown      : $N_DOWN"
    echo "wallCavity    : $N_CAVITY"
    echo "Resolved      : $N_RESOLVED / $TOTAL_PARTICLES"
    echo "Resolved ratio: $resolved_ratio"

    echo "$next_time outlet=$N_OUTLET substrate=$N_SUBSTRATE upper=$N_UPPER down=$N_DOWN cavity=$N_CAVITY resolved=$N_RESOLVED ratio=$resolved_ratio" >> PARTICLE_STATUS.txt

    reached=$(awk -v r="$resolved_ratio" -v target="$TARGET_RATIO" \
        'BEGIN{print (r >= target) ? 1 : 0}')

    if [ "$reached" -eq 1 ]; then
        echo "Target reached: resolved ratio >= $TARGET_RATIO"
        echo "DONE target reached at $next_time" >> PARTICLE_STATUS.txt
        touch PARTICLE_DONE
        exit 0
    fi

    cleanup_old_time_dirs
    cleanup_old_postprocessing_dirs

    reached_max=$(awk -v n="$next_time" -v m="$MAX_TIME" \
        'BEGIN{print (n >= m) ? 1 : 0}')

    set -e

    if [ "$reached_max" -eq 1 ]; then
        echo "Reached MAX_TIME=$MAX_TIME"
        echo "DONE max time reached" >> PARTICLE_STATUS.txt
        touch PARTICLE_DONE
        exit 0
    fi
done
