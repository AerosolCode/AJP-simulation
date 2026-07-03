#!/bin/bash
#SBATCH --output=output_particle.txt
#SBATCH --error=error_particle.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000

CASE_NAME=$(basename "$(dirname "$PWD")")
CASE_NUM=$(echo "$CASE_NAME" | sed 's/case_//')

echo "Particle tracking loop for $CASE_NAME"
echo "Directory: $PWD"

# =========================================================
# settings
# =========================================================

TOTAL_PARTICLES=10000
TARGET_RATIO=0.95
CHUNK=0.5
MAX_TIME=30.0

SOLVER="icoUncoupledKinematicParcelFoam"
LOG="log.icoUncoupledKinematicParcelFoam"

DELTA_T=1e-4
WRITE_INTERVAL=$(awk -v c="$CHUNK" -v dt="$DELTA_T" 'BEGIN{printf "%d", c/dt}')
# =========================================================
# prepare initial particle case
# =========================================================

# CFD結果を 0 として使用
rm -rf 0
cp -r ../10000 0 || {
    echo "Failed to copy ../10000 to 0"
    exit 1
}
rm -f 0/uniform/time
# meshコピー
rm -rf constant/polyMesh
cp -r ../constant/polyMesh constant/ || {
    echo "Failed to copy polyMesh"
    exit 1
}

# wedge → symmetry
sed -i 's/type[[:space:]]*wedge/type            symmetry/g' constant/polyMesh/boundary
sed -i 's/type[[:space:]]*symmetryPlane/type            symmetry/g' constant/polyMesh/boundary

for f in \
    0/U \
    0/p \
    0/k \
    0/omega \
    0/nut \
    0/phi
do
    if [ -f "$f" ]; then
        sed -i 's/type[[:space:]]*wedge/type            symmetry/g' "$f"
        sed -i 's/type[[:space:]]*symmetryPlane/type            symmetry/g' "$f"
    fi
done

touch "p_${CASE_NUM}.foam"

# 既存ログ初期化
rm -f "$LOG"
rm -f PARTICLE_DONE
rm -f PARTICLE_STATUS.txt
rm -f particle_fates_all.csv
# =========================================================
# controlDict basic settings
# =========================================================

# latestTimeから再開
sed -i 's/startFrom[[:space:]]\+.*;/startFrom       latestTime;/' system/controlDict

# 書き出し各チャンク終了時
sed -i 's/writeControl[[:space:]]\+.*;/writeControl    timeStep;/' system/controlDict
sed -i "s/writeInterval[[:space:]]\+.*;/writeInterval   $WRITE_INTERVAL;/" system/controlDict
sed -i 's/writeAtEnd[[:space:]]\+.*;/writeAtEnd      yes;/' system/controlDict
sed -i 's/purgeWrite[[:space:]]\+.*;/purgeWrite      2;/' system/controlDict



# =========================================================
# functions for particle counting
# =========================================================

count_latest_patch_particles()
{
    local func_dir="$1"
    local dat_name="$2"

    if [ ! -d "$func_dir" ]; then
        echo 0
        return
    fi

    local latest_dir
    latest_dir=$(find "$func_dir" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1)

    if [ -z "$latest_dir" ]; then
        echo 0
        return
    fi

    local file="$func_dir/$latest_dir/$dat_name"

    if [ ! -f "$file" ]; then
        echo 0
        return
    fi

    # headerを除いてデータ行だけ数える
    tail -n +2 "$file" | awk 'NF > 0' | wc -l
}

cleanup_old_time_dirs()
{
    # baseparticle直下の時刻フォルダを最新2つだけ残す
    times=$(find . -maxdepth 1 -type d \
        | sed 's#^\./##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g)

    keep=$(echo "$times" | tail -2)

    for t in $times; do
        if [ "$t" = "0" ]; then
            continue
        fi

        echo "$keep" | grep -qx "$t" && continue

        rm -rf "$t"
        echo "Removed old time directory: $t"
    done
}
cleanup_old_postprocessing_dirs()
{
    POST_DIR="postProcessing/lagrangian/kinematicCloud"

    for func in outletParticles wallSubstrateParticles wallUpper wallDown wallCavity; do
        func_dir="$POST_DIR/$func"

        [ -d "$func_dir" ] || continue

        times=$(find "$func_dir" -maxdepth 1 -type d \
            | sed 's#.*/##' \
            | grep -E '^[0-9]+(\.[0-9]+)?$' \
            | sort -g)

        keep=$(echo "$times" | tail -2)

        for t in $times; do
            echo "$keep" | grep -qx "$t" && continue

            rm -rf "$func_dir/$t"
            echo "Removed old postProcessing directory: $func/$t"
        done
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
    latest_dir=$(find "$func_dir" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1)

    if [ -z "$latest_dir" ]; then
        return
    fi

    local file="$func_dir/$latest_dir/$dat_name"

    if [ ! -f "$file" ]; then
        return
    fi

    # headerがなければ作成
    if [ ! -f "$out_csv" ]; then
        echo "patch,time,currentProc,coord0,coord1,coord2,coord3,x,y,z,celli,tetFacei,tetPti,facei,stepFraction,origProc,origId,active,typeId,nParticle,d,dTarget,Ux,Uy,Uz,rho,age,tTurb,UTurbx,UTurby,UTurbz,UCorrectx,UCorrecty,UCorrectz,fx,fy,fz,angularMomentumx,angularMomentumy,angularMomentumz,torquex,torquey,torquez" > "$out_csv"
    fi

    # wallSubstrate.dat などのOpenFOAM parcel出力をCSV列に分解
    tail -n +2 "$file" | awk -v p="$patch_name" '
    NF > 0 {
        for (i = 1; i <= NF; i++) {
            gsub(/\(/, "", $i)
            gsub(/\)/, "", $i)
            gsub(/"/, "", $i)
        }

        # OpenFOAM parcel data format:
        # 1: Time
        # 2: currentProc
        # 3-6: coordinates0-3
        # 7-9: position0-2
        # 10-21: scalar data up to dTarget
        # 22-24: U
        # 25: rho
        # 26: age
        # 27: tTurb
        # 28-30: UTurb
        # 31-33: UCorrect
        # 34-36: f
        # 37-39: angularMomentum
        # 40-42: torque

        if (NF >= 42) {
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
                  $31 "," $32 "," $33 "," \
                  $34 "," $35 "," $36 "," \
                  $37 "," $38 "," $39 "," \
                  $40 "," $41 "," $42
        }
    }' >> "$out_csv"

    # 重複除去
    {
        head -n 1 "$out_csv"
        tail -n +2 "$out_csv" | sort -u
    } > "${out_csv}.tmp"

    mv "${out_csv}.tmp" "$out_csv"
}
# =========================================================
# loop
# =========================================================

while true
do
    latest_time=$(find . -maxdepth 1 -type d \
        | sed 's#^\./##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1)

    if [ -z "$latest_time" ]; then
        latest_time=0
    fi

    next_time=$(awk -v t="$latest_time" -v c="$CHUNK" 'BEGIN{printf "%.6f", t+c}')

    over_max=$(awk -v n="$next_time" -v m="$MAX_TIME" 'BEGIN{print (n > m) ? 1 : 0}')
    if [ "$over_max" -eq 1 ]; then
        next_time="$MAX_TIME"
    fi

    echo "========================================"
    echo "Running particle solver: $latest_time -> $next_time"
    echo "========================================"

    sed -i "s/endTime[[:space:]]\+.*;/endTime         $next_time;/" system/controlDict

    $SOLVER >> "$LOG" 2>&1

    if [ $? -ne 0 ]; then
        echo "Particle solver failed at endTime=$next_time"
        echo "failed at $next_time" > PARTICLE_STATUS.txt
        exit 1
    fi

    POST_DIR="postProcessing/lagrangian/kinematicCloud"

    append_patch_to_all_csv "$POST_DIR/outletParticles" "outlet.dat" "outlet"
    append_patch_to_all_csv "$POST_DIR/wallSubstrateParticles" "wallSubstrate.dat" "wallSubstrate"
    append_patch_to_all_csv "$POST_DIR/wallUpper" "wallUpper.dat" "wallUpper"
    append_patch_to_all_csv "$POST_DIR/wallDown" "wallDown.dat" "wallDown"
    append_patch_to_all_csv "$POST_DIR/wallCavity" "wallCavity.dat" "wallCavity"
    # =========================================================
    # count processed particles from postProcessing
    # =========================================================

    POST_DIR="postProcessing/lagrangian/kinematicCloud"

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

    # ここに追加
    cleanup_old_time_dirs
    cleanup_old_postprocessing_dirs

    reached_max=$(awk -v n="$next_time" -v m="$MAX_TIME" \
        'BEGIN{print (n >= m) ? 1 : 0}')

    if [ "$reached_max" -eq 1 ]; then
        echo "Reached MAX_TIME=$MAX_TIME"
        echo "DONE max time reached" >> PARTICLE_STATUS.txt
        touch PARTICLE_DONE
        exit 0
    fi
done