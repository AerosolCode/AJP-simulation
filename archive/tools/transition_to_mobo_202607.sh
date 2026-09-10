#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${AJP_MASTER_PYTHON:-/home/tamadate/.conda/envs/gmshpy/bin/python}
OLD_CONFIG="$ROOT/configs/bo_multihost_target10um_v2.json"
OLD_WORKDIR="$ROOT/campaigns/bo_target10um_v2"
NEW_WORKDIR="$ROOT/campaigns/mobo_target10um_v1"

export PATH="$(dirname "$PYTHON_BIN"):$PATH"

"$PYTHON_BIN" "$ROOT/tools/bo_multihost.py" \
    --config "$OLD_CONFIG" drain --sleep 60

"$PYTHON_BIN" "$ROOT/tools/rescore_mobo_campaign.py" \
    --config "$ROOT/bo_config.json" \
    --source-candidates "$OLD_WORKDIR/bo_candidates.csv" \
    --source-observations "$OLD_WORKDIR/bo_observations.csv" \
    --source-workdir "$OLD_WORKDIR" \
    --output "$NEW_WORKDIR" \
    --append

"$ROOT/tools/start_bo_multihost.sh"
