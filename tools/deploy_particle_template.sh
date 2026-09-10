#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 PARTICLE_TEMPLATE CAMPAIGN_DIR" >&2
    exit 2
fi

PARTICLE_TEMPLATE=$1
CAMPAIGN_DIR=$2

find "$CAMPAIGN_DIR" \
    -mindepth 2 -maxdepth 2 \
    -type d -name baseparticle \
    -exec cp "$PARTICLE_TEMPLATE/loopaerosolDynamics.sh" {} \;
find "$CAMPAIGN_DIR" \
    -mindepth 2 -maxdepth 2 \
    -type d -name baseparticle \
    -exec cp "$PARTICLE_TEMPLATE/particle_horizon.py" {} \;
find "$CAMPAIGN_DIR" \
    -mindepth 3 -maxdepth 3 \
    -type d -path "*/baseparticle/constant" \
    -exec cp "$PARTICLE_TEMPLATE/constant/kinematicCloudProperties" {} \;
