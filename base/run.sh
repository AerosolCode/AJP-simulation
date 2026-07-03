#!/bin/bash
#SBATCH --output=output.txt
#SBATCH --error=error.txt
#SBATCH --ntasks=1
#SBATCH --mem=5000

python3 meshGen2.py

gmshToFoam meshData.msh > log.gmshToFoam 2>&1

python3 changeBCType.py
python3 BC_omega.py
python3 BC_U.py

touch log.potentialFoam
potentialFoam -writep > log.potentialFoam 2>&1
potentialFoam -writep > log.potentialFoam 2>&1

CASE_NAME=$(basename "$PWD")
scontrol update JobId=$SLURM_JOB_ID JobName=$CASE_NAME
touch "${CASE_NAME}.foam"

echo "Running simpleFoam for $CASE_NAME"

touch log.simpleFoam

simpleFoam > log.simpleFoam 2>&1

#PID=$!

#tail -f log.simpleFoam &
#AILPID=$!
#
#LAST_TIME_LINE=""
#LAST_CHANGE=$(date +%s)

#while kill -0 $PID 2>/dev/null
#do
#
#    CURRENT_TIME_LINE=$(grep "^Time =" log.simpleFoam | tail -n 1)
#
#   if [ "$CURRENT_TIME_LINE" != "$LAST_TIME_LINE" ]; then
#
#       LAST_TIME_LINE="$CURRENT_TIME_LINE"
#       LAST_CHANGE=$(date +%s)
#
#       echo "Advanced to: $CURRENT_TIME_LINE"
#
#   else
#
#      NOW=$(date +%s)
#       DT=$((NOW - LAST_CHANGE))
#
#        echo "No timestep progress for $DT sec"
#
#        if [ $DT -gt 60 ]; then
#
#            echo "$CASE_NAME : STEP TOO SLOW -> killing"
#
#            kill -9 $PID
#            break
#        fi
#    fi
#
#    sleep 5
#done

#kill $TAILPID 2>/dev/null

echo "$CASE_NAME finished"