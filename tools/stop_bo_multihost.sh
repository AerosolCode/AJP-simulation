#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SITE_ENV=${AJP_SITE_ENV:-"$ROOT/site.env"}
if [ -r "$SITE_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SITE_ENV"
    set +a
fi
PYTHON_BIN=${AJP_MASTER_PYTHON:-python3}
CONFIG=${AJP_MULTIHOST_CONFIG:-"$ROOT/bo_multihost_config.json"}
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

if [ ! -s "$PID_FILE" ]; then
    echo "dispatcher pid file not found"
    exit 0
fi

pid=$(cat "$PID_FILE")
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "dispatcher stopped pid=$pid"
else
    echo "dispatcher is not running pid=$pid"
fi
rm -f "$PID_FILE"
