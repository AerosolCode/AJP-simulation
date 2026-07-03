#!/bin/bash
#SBATCH --output=output_restart.txt
#SBATCH --error=error_restart.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000

CASE_NAME=$(basename "$PWD")
scontrol update JobId=$SLURM_JOB_ID JobName=$CASE_NAME

echo "Restarting simpleFoam for $CASE_NAME"
echo "Case directory: $PWD"

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

simpleFoam > log.simpleFoam.restart 2>&1

echo "$CASE_NAME restart finished"