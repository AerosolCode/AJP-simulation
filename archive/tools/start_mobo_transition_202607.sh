#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORKDIR="$ROOT/campaigns/mobo_target10um_v1"
PID_FILE="$WORKDIR/transition.pid"
LOG_FILE="$WORKDIR/transition.log"

mkdir -p "$WORKDIR"

if [ -s "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE")
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "MOBO transition already running pid=$old_pid"
        exit 0
    fi
fi

nohup "$ROOT/tools/transition_to_mobo.sh" >> "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
echo "MOBO transition started pid=$pid log=$LOG_FILE"
