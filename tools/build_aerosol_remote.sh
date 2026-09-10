#!/usr/bin/env bash

if [[ $# -ne 2 ]]; then
    echo "usage: $0 OPENFOAM_BASHRC AEROSOL_SOURCE_DIR" >&2
    exit 2
fi

OPENFOAM_BASHRC=$1
AEROSOL_SOURCE_DIR=$2
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

set --
# shellcheck disable=SC1090
source "$OPENFOAM_BASHRC"
set -eo pipefail
export WM_NCOMPPROCS=${WM_NCOMPPROCS:-1}
if [[ -n "${AJP_WM_PROJECT_USER_DIR:-}" ]]; then
    export WM_PROJECT_USER_DIR=$AJP_WM_PROJECT_USER_DIR
    export FOAM_USER_APPBIN=$WM_PROJECT_USER_DIR/platforms/$WM_OPTIONS/bin
    export FOAM_USER_LIBBIN=$WM_PROJECT_USER_DIR/platforms/$WM_OPTIONS/lib
fi
cd "$AEROSOL_SOURCE_DIR"
wmake lagrangian/intermediate
wmake

"$SCRIPT_DIR/../baseparticle/build_custom.sh"
