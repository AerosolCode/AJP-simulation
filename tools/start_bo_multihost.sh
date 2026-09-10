#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SITE_ENV=${AJP_SITE_ENV:-"$ROOT/site.env"}
if [ ! -r "$SITE_ENV" ]; then
    echo "site configuration not found: $SITE_ENV" >&2
    echo "copy $ROOT/site.env.example to $ROOT/site.env and edit it first" >&2
    exit 2
fi
set -a
# shellcheck disable=SC1090
source "$SITE_ENV"
set +a
PYTHON_BIN=${AJP_MASTER_PYTHON:-python3}
CONFIG=${AJP_MULTIHOST_CONFIG:-"$ROOT/bo_multihost_config.json"}
"$PYTHON_BIN" "$ROOT/tools/check_site_config.py" --config "$CONFIG" >/dev/null
if [ -n "${AJP_CAMPAIGN_WORKDIR:-}" ]; then
    WORKDIR=$AJP_CAMPAIGN_WORKDIR
else
    config_workdir=$("$PYTHON_BIN" -c \
        'import json, sys; print(json.load(open(sys.argv[1]))["workdir"])' \
        "$CONFIG")
    case "$config_workdir" in
        /*) WORKDIR=$config_workdir ;;
        *) WORKDIR="$ROOT/$config_workdir" ;;
    esac
fi
PID_FILE="$WORKDIR/dispatcher.pid"
LOG_FILE="$WORKDIR/dispatcher.log"
export PATH="$(dirname "$PYTHON_BIN"):$PATH"

mkdir -p "$WORKDIR"

if [ -s "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE")
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "dispatcher already running pid=$old_pid"
        exit 0
    fi
fi

nohup "$PYTHON_BIN" -u "$ROOT/tools/bo_multihost.py" \
    --config "$CONFIG" loop >> "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
echo "dispatcher started pid=$pid log=$LOG_FILE"
