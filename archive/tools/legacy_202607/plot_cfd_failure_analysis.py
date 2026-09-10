#!/usr/bin/env python3
"""Plot CFD failure regions and pressure-relaxation A/B diagnostics."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
TIME_RE = re.compile(r"^Time = (" + FLOAT + r")$")
CONTINUITY_RE = re.compile(r"sum local = (" + FLOAT + r")")


def read_observations(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def read_continuity(path: Path) -> tuple[list[float], list[float], bool]:
    iterations: list[float] = []
    continuity: list[float] = []
    current_time: float | None = None
    clean_end = False
    with path.open(errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            time_match = TIME_RE.match(line)
            if time_match:
                current_time = float(time_match.group(1))
                continue
            continuity_match = CONTINUITY_RE.search(line)
            if continuity_match and current_time is not None:
                value = abs(float(continuity_match.group(1)))
                if math.isfinite(value):
                    iterations.append(current_time)
                    continuity.append(max(value, 1.0e-16))
            if line == "End":
                clean_end = True
    return iterations, continuity, clean_end


def value_at_iteration(
    iterations: list[float], values: list[float], target: float
) -> float | None:
    for iteration, value in zip(iterations, values):
        if iteration == target:
            return value
    return None


def first_above(
    iterations: list[float], values: list[float], threshold: float
) -> float | None:
    for iteration, value in zip(iterations, values):
        if value > threshold:
            return iteration
    return None


def plot_failure_map(rows: list[dict[str, str]], output: Path) -> None:
    complete = [row for row in rows if row["failed"] == "False"]
    failed = [row for row in rows if row["failed"] == "True"]

    fig, axis = plt.subplots(figsize=(8.2, 5.2), constrained_layout=True)
    axis.scatter(
        [float(row["theta0_deg"]) for row in complete],
        [float(row["L1_mm"]) for row in complete],
        s=25,
        color="#247BA0",
        alpha=0.65,
        edgecolors="none",
        label=f"Completed ({len(complete)})",
    )
    axis.scatter(
        [float(row["theta0_deg"]) for row in failed],
        [float(row["L1_mm"]) for row in failed],
        s=42,
        color="#D1495B",
        alpha=0.9,
        edgecolors="#7A1F2B",
        linewidths=0.4,
        label=f"CFD failed ({len(failed)})",
    )

    theta_split = 56.9345
    upper_theta_split = 58.3839
    l1_split = 4.5373
    axis.axvline(theta_split, color="#444444", linestyle="--", linewidth=1.1)
    axis.vlines(
        upper_theta_split,
        ymin=0.5,
        ymax=l1_split,
        color="#444444",
        linestyle="--",
        linewidth=1.1,
    )
    axis.axhline(
        l1_split,
        xmin=(theta_split - 10.0) / 50.0,
        color="#444444",
        linestyle=":",
        linewidth=1.1,
    )
    axis.fill_betweenx(
        [l1_split, 20.0],
        theta_split,
        60.0,
        color="#F4A261",
        alpha=0.12,
        label="Tree-classified high-risk region",
    )
    axis.fill_betweenx(
        [0.5, l1_split],
        upper_theta_split,
        60.0,
        color="#F4A261",
        alpha=0.12,
    )
    axis.set(
        xlabel=r"Taper angle $\theta_0$ [deg]",
        ylabel=r"Taper length $L_1$ [mm]",
        xlim=(10.0, 60.3),
        ylim=(0.5, 20.5),
        title="Observed CFD failures in the MOBO campaign",
    )
    axis.grid(True, color="#D9D9D9", linewidth=0.6, alpha=0.75)
    axis.legend(loc="upper left", frameon=True, framealpha=0.95)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_ab_traces(
    trace_specs: list[tuple[str, Path, str, str]],
    output: Path,
    summary_csv: Path,
) -> None:
    grouped: dict[str, list[tuple[str, Path, str]]] = {}
    summary_rows: list[dict[str, object]] = []
    for case_id, path, label, color in trace_specs:
        grouped.setdefault(case_id, []).append((label, path, color))

    fig, axes = plt.subplots(
        len(grouped),
        1,
        figsize=(8.4, 3.4 * len(grouped)),
        sharex=False,
        constrained_layout=True,
    )
    if len(grouped) == 1:
        axes = [axes]

    for axis, (case_id, traces) in zip(axes, grouped.items()):
        plotted_values: list[float] = []
        for label, path, color in traces:
            iterations, values, clean_end = read_continuity(path)
            comparable = [
                (iteration, value)
                for iteration, value in zip(iterations, values)
                if iteration <= 800.0
            ]
            plot_iterations = [item[0] for item in comparable]
            plot_values = [item[1] for item in comparable]
            plotted_values.extend(plot_values)
            axis.plot(
                plot_iterations,
                plot_values,
                label=label,
                color=color,
                linewidth=1.35,
                alpha=0.95,
            )
            summary_rows.append(
                {
                    "case": case_id,
                    "configuration": label,
                    "log": str(path),
                    "last_iteration": iterations[-1] if iterations else None,
                    "continuity_at_800": value_at_iteration(
                        iterations, values, 800.0
                    ),
                    "first_continuity_gt_1e3": first_above(
                        iterations, values, 1.0e3
                    ),
                    "max_local_continuity": max(values) if values else None,
                    "clean_end": clean_end,
                }
            )
        axis.axhline(1.0e3, color="#6A6A6A", linestyle=":", linewidth=1.0)
        axis.set_yscale("log")
        upper_limit = max(1.0e4, max(plotted_values, default=1.0) * 10.0)
        axis.set_xlim(0.0, 800.0)
        axis.set_ylim(1.0e-6, upper_limit)
        axis.set_xlabel("SIMPLE iteration")
        axis.set_ylabel("Local continuity error")
        axis.set_title(case_id)
        axis.grid(True, which="major", color="#D9D9D9", linewidth=0.6)
        axis.legend(loc="upper left", frameon=True, framealpha=0.95)

    fig.savefig(output, dpi=180)
    plt.close(fig)

    with summary_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis-csv",
        default="reports/cfd_failure_cases_20260727.csv",
    )
    parser.add_argument(
        "--diagnostic-root",
        default="reports/cfd_failure_diagnostic",
    )
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    analysis_csv = Path(args.analysis_csv)
    diagnostic_root = Path(args.diagnostic_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_observations(analysis_csv)
    plot_failure_map(rows, output_dir / "cfd_failure_map_20260727.png")

    specs = [
        (
            "case_1317",
            diagnostic_root / "baseline/case_1317/log.simpleFoam",
            "Original: p in equations",
            "#D1495B",
        ),
        (
            "case_1317",
            diagnostic_root
            / "corrected/case_1317/simplec_standard/log.simpleFoam",
            "Corrected: p in fields",
            "#247BA0",
        ),
        (
            "case_1401",
            diagnostic_root / "baseline/case_1401/log.simpleFoam",
            "Original: p in equations",
            "#D1495B",
        ),
        (
            "case_1401",
            diagnostic_root / "corrected/case_1401/log.simpleFoam",
            "Corrected: p in fields",
            "#247BA0",
        ),
        (
            "case_1436",
            diagnostic_root / "baseline/case_1436/log.simpleFoam",
            "Original: p in equations",
            "#D1495B",
        ),
        (
            "case_1436",
            diagnostic_root / "corrected/case_1436/log.simpleFoam",
            "Corrected: p in fields",
            "#247BA0",
        ),
    ]
    plot_ab_traces(
        specs,
        output_dir / "cfd_pressure_relaxation_ab_20260727.png",
        output_dir / "cfd_pressure_relaxation_ab_20260727.csv",
    )


if __name__ == "__main__":
    main()
