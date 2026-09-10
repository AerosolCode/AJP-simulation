#未完了ケースを探してrun.sh
#potentialFoam -writepへ修正版

#!/bin/bash

#BASE_DIR="$HOME/initialTrial_82/initialTrial"
#MASTER_RUN="$BASE_DIR/base/run.sh"

#for CASE_DIR in "$BASE_DIR"/case_*
#do
#    [ -d "$CASE_DIR" ] || continue

#    CASE_NAME=$(basename "$CASE_DIR")

#    # 完了済みならスキップ
#    if [ -d "$CASE_DIR/10000" ]; then
#        echo "Skipping $CASE_NAME (finished)"
#        continue
#    fi

#    # 既に投入済みならスキップ
#    if squeue -u "$USER" -h -o "%j" | grep -qx "$CASE_NAME"; then
#        echo "Skipping $CASE_NAME (already queued)"
#        continue
#    fi

#    echo "Updating base and submitting $CASE_NAME"

#    # 最新run.shをコピー
#    cp "$MASTER_RUN" "$CASE_DIR/run.sh" || {
#        echo "Failed to copy run.sh to $CASE_NAME"
#        continue
#    }

#    # ジョブ投入
#    (
#        cd "$CASE_DIR" || exit 1
#        sbatch run.sh
#    )

#done

#!/bin/bash

BASE_DIR="$HOME/initialTrial_92/initialTrial"

MASTER_FULL_RUN="$BASE_DIR/base/run.sh"
MASTER_RESTART_RUN="$BASE_DIR/base/restartrun.sh"

for CASE_DIR in "$BASE_DIR"/case_*
do
    [ -d "$CASE_DIR" ] || continue

    CASE_NAME=$(basename "$CASE_DIR")

    # 完了済みならスキップ
    if [ -d "$CASE_DIR/10000" ]; then
        echo "Skipping $CASE_NAME (finished)"
        continue
    fi

    # 既に投入済みならスキップ
    if squeue -u "$USER" -h -o "%j" | grep -qx "$CASE_NAME"; then
        echo "Skipping $CASE_NAME (already queued)"
        continue
    fi

    # 最新の時刻フォルダを取得
    latest_time=$(find "$CASE_DIR" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$' \
        | sort -g \
        | tail -1)

    # 0以外の時刻フォルダがあるなら restart
    if [ -n "$latest_time" ] && [ "$latest_time" != "0" ]; then

        echo "Restart submitting $CASE_NAME from $latest_time"

        # base の最新 restartrun.sh をコピー
        cp "$MASTER_RESTART_RUN" "$CASE_DIR/restartrun.sh" || {
            echo "Failed to copy restartrun.sh to $CASE_NAME"
            continue
        }

        (
            cd "$CASE_DIR" || exit 1
            sbatch --job-name="$CASE_NAME" restartrun.sh
        )

    else

        echo "Full-run submitting $CASE_NAME from mesh generation"

        # base の最新 run.sh をコピー
        cp "$MASTER_FULL_RUN" "$CASE_DIR/run.sh" || {
            echo "Failed to copy run.sh to $CASE_NAME"
            continue
        }

        (
            cd "$CASE_DIR" || exit 1
            sbatch --job-name="$CASE_NAME" run.sh
        )

    fi

done