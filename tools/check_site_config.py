#!/usr/bin/env python3
"""Check local manual-BO settings without submitting a job or connecting by SSH."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from site_config import load_site_env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-tools", action="store_true", help="check Python modules, OpenFOAM path and Slurm")
    args = parser.parse_args(argv)
    try:
        site_path = load_site_env()
    except ValueError as error:
        print("ERROR:", error)
        return 1
    errors = []
    if not site_path.is_file():
        errors.append("copy site.env.example to site.env and edit it first")
    python = os.environ.get("AJP_PYTHON_BIN", "python3")
    foam = os.environ.get("AJP_OPENFOAM_BASHRC", "/usr/lib/openfoam/openfoam2406/etc/bashrc")
    print("site_env:", site_path)
    print("python:", python)
    print("OpenFOAM bashrc:", foam)
    print("particle solver:", os.environ.get("AJP_PARTICLE_SOLVER") or "aerosolDynamicsFoam from OpenFOAM PATH")
    print("Slurm nodelist:", os.environ.get("AJP_SLURM_NODELIST") or "scheduler selection")
    if args.local_tools:
        if not Path(foam).is_file():
            errors.append("OpenFOAM bashrc not found: " + foam)
        for command in (python, "squeue", "sbatch"):
            if not shutil.which(command):
                errors.append("command not found: " + command)
        if shutil.which(python):
            result = subprocess.run([python, "-c", "import numpy, gmsh"], capture_output=True, text=True)
            if result.returncode:
                errors.append("Python numpy/gmsh import failed: " + result.stderr.strip())
        solver = os.environ.get("AJP_PARTICLE_SOLVER")
        if solver and not (shutil.which(solver) or (Path(solver).is_file() and os.access(solver, os.X_OK))):
            errors.append("configured particle solver is not executable: " + solver)
        library = Path(__file__).resolve().parents[1] / "baseparticle/custom/finiteRadiusDeposition/lib/libfiniteRadiusDeposition.so"
        if not library.is_file():
            errors.append("finite-radius library missing; run tools/build_solver.sh under the execution OpenFOAM environment")
    for error in errors:
        print("ERROR:", error)
    print("This checks local configuration only; solver/MPI execution must be validated on the target host.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
