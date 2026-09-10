#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 || "$1" != /* ]]; then
    echo "usage: $0 /absolute/path/to/aerosolDynamicsFoam-source" >&2
    echo "Prepare the matching OpenFOAM environment and build the external solver first." >&2
    exit 2
fi
export AJP_AEROSOL_SOURCE_DIR=$1
INCLUDE_DIR="$AJP_AEROSOL_SOURCE_DIR/lagrangian/intermediate/lnInclude"
for header in basicKinematicCloud.H CloudFunctionObject.H cloudFunctionObjectTools.H; do
    if [[ ! -r "$INCLUDE_DIR/$header" ]]; then
        echo "Missing solver header: $INCLUDE_DIR/$header" >&2
        echo "Build the external solver's lagrangian/intermediate library with wmake to generate lnInclude first." >&2
        exit 2
    fi
done
for required_command in wclean wmake; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Required command unavailable: $required_command. Prepare the matching OpenFOAM build environment first." >&2
        exit 127
    fi
done
# Preserve the external solver library location before choosing the plugin output.
export AJP_AEROSOL_LIBBIN=${AJP_AEROSOL_LIBBIN:-${FOAM_USER_LIBBIN:-}}
if [[ -z "$AJP_AEROSOL_LIBBIN" || ! -r "$AJP_AEROSOL_LIBBIN/liboneWayIntermediate.so" ]]; then
    echo "liboneWayIntermediate.so is required in FOAM_USER_LIBBIN (or AJP_AEROSOL_LIBBIN). Build the external solver first." >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/custom/finiteRadiusDeposition"

export FOAM_USER_LIBBIN="$SOURCE_DIR/lib"
mkdir -p "$FOAM_USER_LIBBIN"

cd "$SOURCE_DIR"
wclean libso
wmake libso

test -s "$FOAM_USER_LIBBIN/libfiniteRadiusDeposition.so"
echo "Built $FOAM_USER_LIBBIN/libfiniteRadiusDeposition.so"
