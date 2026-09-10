#!/bin/bash

export AJP_OPENFOAM_BASHRC=/usr/lib/openfoam/openfoam2406/etc/bashrc
export AJP_WORKER_ROOT=${AJP_WORKER_ROOT:-"$HOME/AJP-worker"}
export AJP_PYTHON_BIN="$HOME/.conda/envs/gmshpy/bin/python"
export AJP_PARTICLE_SOLVER="$HOME/OpenFOAM/${USER}-v2406/platforms/linux64GccDPInt32Opt/bin/aerosolDynamicsFoam"
