#!/usr/bin/env python3
"""Estimate a conservative particle-tracking horizon from case parameters."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


AXIAL_KEYS = ("t_mm", "L0_mm", "L1_mm", "L2_mm", "L4_mm")


def load_params(path: Path) -> dict[str, float]:
    params: dict[str, float] = {}
    with path.open() as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            params[key.strip()] = float(value.strip())
    return params


def estimate_horizon(
    params: dict[str, float],
    factor: float = 3.0,
    minimum: float = 0.5,
    maximum: float = 5.0,
) -> tuple[float, float, float, float]:
    if factor <= 0.0:
        raise ValueError("horizon factor must be positive")
    if minimum <= 0.0 or maximum < minimum:
        raise ValueError("invalid horizon bounds")

    radius_m = params["Rin_mm"] * 1.0e-3
    flow_m3_s = params["Qaerosol_lpm"] * 1.0e-3 / 60.0
    axial_length_m = sum(params[key] for key in AXIAL_KEYS) * 1.0e-3
    if radius_m <= 0.0 or flow_m3_s <= 0.0 or axial_length_m <= 0.0:
        raise ValueError("radius, aerosol flow, and axial length must be positive")

    inlet_velocity_mps = flow_m3_s / (math.pi * radius_m**2)
    nominal_transit_s = axial_length_m / inlet_velocity_mps
    horizon_s = min(max(factor * nominal_transit_s, minimum), maximum)
    return horizon_s, inlet_velocity_mps, axial_length_m, nominal_transit_s


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("params", type=Path)
    parser.add_argument("--factor", type=float, default=3.0)
    parser.add_argument("--min", dest="minimum", type=float, default=0.5)
    parser.add_argument("--max", dest="maximum", type=float, default=5.0)
    args = parser.parse_args()

    values = estimate_horizon(
        load_params(args.params),
        factor=args.factor,
        minimum=args.minimum,
        maximum=args.maximum,
    )
    print(" ".join(f"{value:.12g}" for value in values))


if __name__ == "__main__":
    main()
