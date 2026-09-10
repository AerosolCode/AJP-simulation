#!/usr/bin/env python3
"""Plot a diameter-resolved substrate collection curve from particle fates."""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


DIAMETER_RE = re.compile(
    r"fixedValueDistribution\s*\{\s*value\s+([0-9.eE+-]+)\s*;",
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fates", required=True, type=Path)
    parser.add_argument("--cloud-properties", required=True, type=Path)
    parser.add_argument("--run-config", required=True, type=Path)
    parser.add_argument("--output-prefix", required=True, type=Path)
    parser.add_argument("--title", default="Particle cutoff curve")
    parser.add_argument("--label", default="Particle tracking result")
    return parser.parse_args()


def read_diameters(path: Path) -> list[float]:
    values = [float(value) for value in DIAMETER_RE.findall(path.read_text())]
    if not values:
        raise ValueError(f"No fixed particle diameters found in {path}")
    return sorted(set(values))


def read_injection_points(path: Path) -> int:
    match = re.search(r"^\s*injection_points\s*=\s*(\d+)\s*$", path.read_text(), re.MULTILINE)
    if not match:
        raise ValueError(f"No injection_points entry found in {path}")
    return int(match.group(1))


def nearest_diameter(value: float, diameters: list[float]) -> float:
    result = min(diameters, key=lambda diameter: abs(diameter - value))
    if not math.isclose(value, result, rel_tol=1e-6, abs_tol=1e-15):
        raise ValueError(f"Particle diameter {value:g} does not match an injection bin")
    return result


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials <= 0:
        return math.nan, math.nan
    z = 1.959963984540054
    probability = successes / trials
    denominator = 1.0 + z * z / trials
    center = (probability + z * z / (2.0 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return center - half_width, center + half_width


def read_fates(path: Path, diameters: list[float]) -> dict[float, Counter[str]]:
    counts = {diameter: Counter() for diameter in diameters}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            diameter = nearest_diameter(float(row["d"]), diameters)
            counts[diameter][row["patch"]] += 1
    return counts


def estimate_d50(diameters_um: np.ndarray, efficiency: np.ndarray) -> tuple[str, float | None]:
    if np.all(efficiency > 0.5):
        return f"D50 < {diameters_um.min():.2f} um (outside tested range)", None
    if np.all(efficiency < 0.5):
        return f"D50 > {diameters_um.max():.2f} um (outside tested range)", None

    for index in range(len(efficiency) - 1):
        y0, y1 = efficiency[index : index + 2]
        if (y0 - 0.5) * (y1 - 0.5) <= 0.0 and not math.isclose(y0, y1):
            x0, x1 = np.log10(diameters_um[index : index + 2])
            fraction = (0.5 - y0) / (y1 - y0)
            d50 = 10.0 ** (x0 + fraction * (x1 - x0))
            return f"D50 = {d50:.3g} um (log-linear interpolation)", d50
    return "D50 not resolved", None


def make_rows(
    diameters: list[float],
    counts: dict[float, Counter[str]],
    injected: int,
) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for diameter in diameters:
        bin_counts = counts[diameter]
        substrate = bin_counts["wallSubstrate"]
        resolved = sum(bin_counts.values())
        ci_low, ci_high = wilson_interval(substrate, injected)
        rows.append(
            {
                "diameter_um": round(diameter * 1e6, 12),
                "injected": injected,
                "n_substrate": substrate,
                "n_outlet": bin_counts["outlet"],
                "n_wall_upper": bin_counts["wallUpper"],
                "n_wall_down": bin_counts["wallDown"],
                "n_wall_cavity": bin_counts["wallCavity"],
                "n_resolved": resolved,
                "n_unresolved": max(injected - resolved, 0),
                "substrate_efficiency": substrate / injected,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "outlet_fraction": bin_counts["outlet"] / injected,
                "unresolved_fraction": max(injected - resolved, 0) / injected,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, float | int]]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_curve(
    output_prefix: Path,
    rows: list[dict[str, float | int]],
    title: str,
    label: str,
) -> str:
    diameter = np.array([float(row["diameter_um"]) for row in rows])
    efficiency = np.array([float(row["substrate_efficiency"]) for row in rows])
    ci_low = np.array([float(row["ci95_low"]) for row in rows])
    ci_high = np.array([float(row["ci95_high"]) for row in rows])
    outlet = np.array([float(row["outlet_fraction"]) for row in rows])
    unresolved = np.array([float(row["unresolved_fraction"]) for row in rows])
    d50_text, d50 = estimate_d50(diameter, efficiency)

    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "axes.edgecolor": "#333333",
            "axes.linewidth": 0.8,
            "legend.frameon": False,
        }
    )
    figure, axis = plt.subplots(figsize=(7.2, 4.8), constrained_layout=True)
    lower_error = efficiency - ci_low
    upper_error = ci_high - efficiency
    axis.errorbar(
        diameter,
        efficiency,
        yerr=np.vstack([lower_error, upper_error]),
        color="#1769aa",
        marker="o",
        markersize=5,
        linewidth=2,
        capsize=3,
        label="Substrate collection (95% CI)",
        zorder=3,
    )
    axis.plot(
        diameter,
        outlet,
        color="#4f5b62",
        marker="s",
        markersize=4,
        linestyle="--",
        linewidth=1.4,
        label="Outlet",
    )
    axis.plot(
        diameter,
        unresolved,
        color="#d1495b",
        marker="^",
        markersize=4,
        linestyle=":",
        linewidth=1.6,
        label="Unresolved at end time",
    )
    axis.axhline(0.5, color="#777777", linewidth=1, linestyle="--", zorder=0)
    if d50 is not None:
        axis.axvline(d50, color="#777777", linewidth=1, linestyle=":", zorder=0)

    axis.set_xscale("log")
    axis.set_xlim(diameter.min() / 1.25, diameter.max() * 1.25)
    axis.set_ylim(-0.025, 1.05)
    axis.set_xlabel("Particle diameter [um]")
    axis.set_ylabel("Fraction of injected parcels")
    axis.set_title(title, loc="left", pad=18)
    axis.text(
        0.0,
        1.015,
        label,
        transform=axis.transAxes,
        color="#555555",
        fontsize=9,
        va="bottom",
    )
    axis.text(
        0.025,
        0.08,
        d50_text,
        transform=axis.transAxes,
        fontsize=10,
        color="#222222",
        bbox={"facecolor": "white", "edgecolor": "#cccccc", "boxstyle": "square,pad=0.35"},
    )
    axis.grid(which="major", color="#dddddd", linewidth=0.8)
    axis.grid(which="minor", axis="x", color="#eeeeee", linewidth=0.5)
    axis.legend(loc="lower right")

    figure.savefig(output_prefix.with_suffix(".png"), dpi=220)
    figure.savefig(output_prefix.with_suffix(".svg"))
    plt.close(figure)
    return d50_text


def main() -> None:
    args = parse_args()
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    diameters = read_diameters(args.cloud_properties)
    injected = read_injection_points(args.run_config)
    rows = make_rows(diameters, read_fates(args.fates, diameters), injected)
    write_csv(args.output_prefix.with_suffix(".csv"), rows)
    d50_text = plot_curve(args.output_prefix, rows, args.title, args.label)
    print(f"Wrote {args.output_prefix.with_suffix('.csv')}")
    print(f"Wrote {args.output_prefix.with_suffix('.png')}")
    print(f"Wrote {args.output_prefix.with_suffix('.svg')}")
    print(d50_text)


if __name__ == "__main__":
    main()
