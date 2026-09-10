#!/usr/bin/env python3
"""Plot the current meshGen2.py profile with point and line numbers."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-ajp")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import bo_loop


def load_params_dat(path: Path) -> dict[str, float]:
    data: dict[str, float] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = float(value)
    return data


def midpoint_params(config_path: Path) -> dict[str, float]:
    with config_path.open() as f:
        config = json.load(f)
    raw = {
        key: 0.5 * (float(bounds[0]) + float(bounds[1]))
        for key, bounds in config["parameters"].items()
    }
    params = bo_loop.convert_params(raw)
    if params is None:
        raise RuntimeError("midpoint parameter set is infeasible")
    return params


def profile_points(params: dict[str, float]) -> dict[int, tuple[float, float]]:
    L0 = params["L0_mm"]
    L1 = params["L1_mm"]
    L2 = params["L2_mm"]
    L4 = params["L4_mm"]
    R = params["R_mm"]
    Rin = params["Rin_mm"]
    t = params["t_mm"]
    R1 = params["R1_mm"]
    R2 = params["R2_mm"]
    R3 = params["R3_mm"]
    L3 = params["L3_mm"]
    l1y = params["l1y_mm"]
    l2y = params["l2y_mm"]
    R4 = R + 10.0
    R5 = 50.0
    t1 = t + L0

    return {
        1: (0.0, t + L0 + L1 + L2 + L4),
        2: (Rin, t + L0 + L1 + L2 + L4),
        3: (Rin, t + L0 + L1 + L2),
        4: (R1 - L3, t + L0 + L1 + L2),
        5: (R2, t + L0 + L1 + L2 + l2y),
        6: (R3, t + L0 + L1 + L2 + l2y),
        7: (R3, t + L0 + L1 + L2 + l1y),
        8: (R2, t + L0 + L1 + L2 + l1y),
        9: (R1, t + L0 + L1 + L2),
        10: (R1, t + L0 + L1),
        11: (R, t + L0),
        12: (R, t),
        13: (R4, t),
        14: (R4, t1),
        15: (R5, t1),
        16: (R5, 0.0),
        17: (0.0, 0.0),
    }


def add_structured_axis_points(
    points: dict[int, tuple[float, float]],
    substrate_layer_height_mm: float,
) -> dict[int, tuple[float, float]]:
    structured = dict(points)
    h_bl = substrate_layer_height_mm
    structured[18] = (0.0, points[12][1])
    structured[19] = (0.0, points[11][1])
    structured[20] = (0.0, points[10][1])
    structured[21] = (0.0, points[3][1])
    structured[22] = (points[12][0], 0.0)
    structured[23] = (points[13][0], 0.0)
    structured[31] = (0.0, h_bl)
    structured[32] = (points[12][0], h_bl)
    structured[33] = (points[13][0], h_bl)
    structured[34] = (points[16][0], h_bl)
    structured[35] = (points[16][0], points[13][1])
    structured[40] = (points[3][0], points[10][1])
    structured[41] = (points[4][0], points[10][1])
    return structured


def profile_lines(structured_axis: bool) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    if structured_axis:
        boundary = [(idx, idx, idx + 1) for idx in range(1, 15)] + [
            (15, 15, 35),
            (39, 35, 34),
            (34, 34, 16),
            (16, 16, 23),
            (22, 23, 22),
            (23, 22, 17),
            (17, 17, 31),
            (31, 31, 18),
            (18, 18, 19),
            (19, 19, 20),
            (20, 20, 21),
            (21, 21, 1),
        ]
        construction = [
            (24, 3, 21),
            (25, 11, 19),
            (26, 12, 18),
            (27, 12, 32),
            (28, 13, 33),
            (29, 10, 41),
            (30, 4, 9),
            (32, 32, 22),
            (33, 33, 23),
            (35, 31, 32),
            (36, 32, 33),
            (37, 33, 34),
            (38, 13, 35),
            (40, 41, 40),
            (41, 40, 20),
            (42, 3, 40),
            (43, 4, 41),
        ]
        return boundary, construction
    return [(idx, idx, idx + 1) for idx in range(1, 17)] + [(17, 17, 1)], []


def write_points_csv(path: Path, points: dict[int, tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["point", "radius_mm", "axial_mm"])
        for idx, (radius, axial) in points.items():
            writer.writerow([idx, f"{radius:.8f}", f"{axial:.8f}"])


def plot_profile(
    points: dict[int, tuple[float, float]],
    boundary_lines: list[tuple[int, int, int]],
    construction_lines: list[tuple[int, int, int]],
    output: Path,
    title: str,
    label_lines: bool,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    xs = [coord[0] for coord in points.values()]
    ys = [coord[1] for coord in points.values()]
    x_center = 0.5 * (min(xs) + max(xs))
    y_center = 0.5 * (min(ys) + max(ys))

    fig, ax = plt.subplots(figsize=(14, 10), constrained_layout=True)
    for _, p1, p2 in boundary_lines:
        ax.plot(
            [points[p1][0], points[p2][0]],
            [points[p1][1], points[p2][1]],
            color="#1f2937",
            linewidth=1.8,
        )
    for _, p1, p2 in construction_lines:
        ax.plot(
            [points[p1][0], points[p2][0]],
            [points[p1][1], points[p2][1]],
            color="#7c3aed",
            linewidth=1.2,
            linestyle="--",
        )
    ax.scatter(xs, ys, s=30, color="#2563eb", zorder=3)

    point_offsets = {
        17: (-14, -10),
        18: (-18, 2),
        19: (-18, 8),
        20: (-18, -9),
        21: (-18, 9),
        22: (10, -12),
        23: (12, -12),
        31: (-18, 8),
        32: (12, 9),
        33: (12, 9),
        34: (12, 9),
        35: (12, -11),
        40: (-14, -13),
        41: (14, -13),
    }

    for idx, (x, y) in points.items():
        if idx in point_offsets:
            xytext = point_offsets[idx]
        else:
            dx = 8 if x >= x_center else -14
            dy = 8 if y >= y_center else -12
            if idx % 3 == 0:
                dy = -dy
            xytext = (dx, dy)
        ax.annotate(
            str(idx),
            (x, y),
            xytext=xytext,
            textcoords="offset points",
            fontsize=7.5,
            color="#111827",
            arrowprops={"arrowstyle": "-", "color": "#9ca3af", "lw": 0.4, "shrinkA": 0, "shrinkB": 3},
            bbox={"boxstyle": "round,pad=0.14", "fc": "white", "ec": "#9ca3af", "lw": 0.45},
        )

    if label_lines:
        for line_idx, p1, p2 in boundary_lines + construction_lines:
            x1, y1 = points[p1]
            x2, y2 = points[p2]
            x = 0.5 * (x1 + x2)
            y = 0.5 * (y1 + y2)
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length > 0.0:
                nx = -dy / length
                ny = dx / length
            else:
                nx = 0.0
                ny = 1.0
            side = -1 if line_idx % 2 else 1
            angle = math.degrees(math.atan2(dy, dx))
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180
            ax.annotate(
                f"L{line_idx}",
                (x, y),
                xytext=(side * nx * 10, side * ny * 10),
                textcoords="offset points",
                fontsize=8,
                color="#7c3aed" if (line_idx >= 24) else "#b91c1c",
                ha="center",
                va="center",
                rotation=angle,
                rotation_mode="anchor",
                bbox={"boxstyle": "round,pad=0.12", "fc": "#fff7ed", "ec": "#fed7aa", "lw": 0.5},
            )

    ax.set_title(title)
    ax.set_xlabel("radius r [mm]")
    ax.set_ylabel("axial y [mm]")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, color="#d1d5db", linewidth=0.6, alpha=0.8)
    if xlim is not None:
        ax.set_xlim(*xlim)
    if ylim is not None:
        ax.set_ylim(*ylim)
    if xlim is None and ylim is None:
        ax.margins(0.08)
    fig.savefig(output, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", type=Path, help="params.dat to plot")
    parser.add_argument("--config", type=Path, default=Path("bo_config.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/mesh_profile_points.png"))
    parser.add_argument("--csv", type=Path, default=Path("reports/mesh_profile_points.csv"))
    parser.add_argument("--svg", type=Path, default=Path("reports/mesh_profile_points.svg"))
    parser.add_argument("--structured-axis", action="store_true")
    parser.add_argument("--no-line-labels", action="store_true")
    args = parser.parse_args()

    if args.params:
        params = load_params_dat(args.params)
        title = f"meshGen2 profile: {args.params}"
    else:
        params = midpoint_params(args.config)
        title = "meshGen2 profile: bo_config midpoint"

    points = profile_points(params)
    if args.structured_axis:
        points = add_structured_axis_points(points, params.get("substrate_layer_height_mm", 0.2))
        title += " with structured axis points"
    boundary_lines, construction_lines = profile_lines(args.structured_axis)
    write_points_csv(args.csv, points)
    plot_profile(points, boundary_lines, construction_lines, args.output, title, not args.no_line_labels)
    if args.svg:
        plot_profile(points, boundary_lines, construction_lines, args.svg, title, not args.no_line_labels)
    if args.structured_axis:
        substrate_output = args.output.with_name(f"{args.output.stem}_substrate_zoom{args.output.suffix}")
        shoulder_output = args.output.with_name(f"{args.output.stem}_shoulder_zoom{args.output.suffix}")
        plot_profile(
            points,
            boundary_lines,
            construction_lines,
            substrate_output,
            f"{title}: substrate zoom",
            not args.no_line_labels,
            xlim=(-1.5, 14.0),
            ylim=(-1.5, 9.0),
        )
        plot_profile(
            points,
            boundary_lines,
            construction_lines,
            shoulder_output,
            f"{title}: shoulder zoom",
            not args.no_line_labels,
            xlim=(-1.5, 13.0),
            ylim=(15.0, 43.5),
        )


if __name__ == "__main__":
    main()
