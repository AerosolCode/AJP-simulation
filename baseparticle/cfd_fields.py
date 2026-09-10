"""Locate the latest completed positive CFD time, including early convergence."""

import math
import sys
from pathlib import Path


def latest_cfd_time(case_dir):
    case_dir = Path(case_dir)
    if not (case_dir / "CFD_DONE").is_file() or (case_dir / "CFD_FAILED").exists():
        raise ValueError("CFD_DONE is required and CFD_FAILED must be absent")
    times = []
    for child in case_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            value = float(child.name)
        except ValueError:
            continue
        if math.isfinite(value) and value > 0:
            times.append((value, child))
    if not times:
        raise ValueError("no positive CFD time exists")
    latest = max(times)[1]
    if not ((latest / "U").is_file() or (latest / "U.gz").is_file()):
        raise ValueError("latest CFD time has no U field: " + str(latest))
    return latest.name


if __name__ == "__main__":
    try:
        print(latest_cfd_time(sys.argv[1]))
    except (ValueError, OSError) as error:
        sys.exit(str(error))
