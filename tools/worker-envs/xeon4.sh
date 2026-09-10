#!/bin/bash

export AJP_OPENFOAM_BASHRC=/usr/lib/openfoam/openfoam2406/etc/bashrc
export AJP_WORKER_ROOT=${AJP_WORKER_ROOT:-"$HOME/AJP-worker"}
export AJP_PYTHON_BIN=/usr/bin/python3
export PYTHONPATH="$AJP_WORKER_ROOT/python-packages${PYTHONPATH:+:$PYTHONPATH}"
export AJP_PARTICLE_SOLVER="$AJP_WORKER_ROOT/OpenFOAM-user/platforms/linux64GccDPInt32Opt/bin/aerosolDynamicsFoam"
export LD_LIBRARY_PATH="$AJP_WORKER_ROOT/OpenFOAM-user/platforms/linux64GccDPInt32Opt/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
