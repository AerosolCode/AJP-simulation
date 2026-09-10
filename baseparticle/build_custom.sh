#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/custom/finiteRadiusDeposition"

export FOAM_USER_LIBBIN="$SOURCE_DIR/lib"
mkdir -p "$FOAM_USER_LIBBIN"

cd "$SOURCE_DIR"
wclean libso
wmake libso

test -s "$FOAM_USER_LIBBIN/libfiniteRadiusDeposition.so"
echo "Built $FOAM_USER_LIBBIN/libfiniteRadiusDeposition.so"
