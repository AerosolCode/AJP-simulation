#未完了ケースを探してparticlerun.sh
#!/bin/bash

BASE_DIR="$HOME/initialTrial_92/initialTrial"

for CASE_DIR in "$BASE_DIR"/case_*
do
    [ -d "$CASE_DIR" ] || continue

    CASE_NAME=$(basename "$CASE_DIR")

    # CFD未完了ならスキップ
    [ -d "$CASE_DIR/10000" ] || continue

    # 粒子追跡完了済みならスキップ
    #[ ! -d "$CASE_DIR/baseparticle/1" ] || continue
    [ ! -f "$CASE_DIR/baseparticle/PARTICLE_DONE" ] || continue

    # 投入済みならスキップ
    if squeue -u "$USER" -h -o "%j" | grep -qx "P_${CASE_NAME}"
    then
        continue
    fi

    echo "Submitting particle tracking : $CASE_NAME"

    # 古いbaseparticle削除
    rm -rf "$CASE_DIR/baseparticle"

    # 最新baseparticleコピー
    cp -r "$BASE_DIR/baseparticle" "$CASE_DIR/" || {
        echo "Failed to copy baseparticle to $CASE_NAME"
        continue
    }

    (
        cd "$CASE_DIR/baseparticle" || exit 1
        #sbatch --job-name="P_${CASE_NAME}" particlerun.sh
        sbatch --job-name="P_${CASE_NAME}" loopparticle.sh
    )

done