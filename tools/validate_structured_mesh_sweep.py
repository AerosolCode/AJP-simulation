#!/usr/bin/env python3
"""Validate the structured mesh generator over representative BO conditions."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import bo_loop


CHECK_PATTERNS = {
    "points": re.compile(r"^\s*points:\s+(\d+)"),
    "cells": re.compile(r"^\s*cells:\s+(\d+)"),
    "hex": re.compile(r"^\s*hexahedra:\s+(\d+)"),
    "prism": re.compile(r"^\s*prisms:\s+(\d+)"),
    "max_aspect": re.compile(r"Max aspect ratio = ([0-9.eE+-]+)"),
    "max_nonortho": re.compile(r"Mesh non-orthogonality Max: ([0-9.eE+-]+) average: ([0-9.eE+-]+)"),
    "max_skew": re.compile(r"Max skewness = ([0-9.eE+-]+)"),
    "wall_substrate": re.compile(r"wallSubstrate\s+(\d+)\s+(\d+)"),
}

SIMPLEFOAM_PATTERNS = {
    "time": re.compile(r"^Time = ([0-9.eE+-]+)"),
    "continuity": re.compile(
        r"time step continuity errors : sum local = ([0-9.eE+-]+), "
        r"global = ([0-9.eE+-]+), cumulative = ([0-9.eE+-]+)"
    ),
}


def run_command(command: str, cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def write_text(path: Path, content: str) -> None:
    path.write_text(content)


def write_params(path: Path, params: dict[str, float], output_keys: list[str], wedge_deg: float) -> None:
    with path.open("w") as f:
        for key in output_keys:
            f.write(f"{key}={params[key]:.8f}\n")
        f.write(f"wedge_deg={wedge_deg:.8f}\n")
        f.write("substrate_layer_height_mm=0.2\n")


def prepare_case(case_dir: Path, params: dict[str, float], output_keys: list[str], wedge_deg: float) -> None:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    shutil.copytree(REPO_ROOT / "base", case_dir)
    write_params(case_dir / "params.dat", params, output_keys, wedge_deg)


def parse_check_mesh(path: Path) -> dict[str, str]:
    metrics: dict[str, str] = {
        "mesh_ok": "no",
        "points": "",
        "cells": "",
        "hex": "",
        "prism": "",
        "max_aspect": "",
        "max_nonortho": "",
        "avg_nonortho": "",
        "max_skew": "",
        "wall_substrate_faces": "",
        "failed_checks": "",
        "default_faces": "no",
        "invalid_faces": "no",
    }
    if not path.exists():
        return metrics
    text = path.read_text(errors="replace")
    metrics["mesh_ok"] = "yes" if "Mesh OK." in text else "no"
    metrics["default_faces"] = "yes" if "defaultFaces" in text else "no"
    metrics["invalid_faces"] = "yes" if "invalid vertex labels" in text else "no"
    failed = re.search(r"Failed (\d+) mesh checks", text)
    if failed:
        metrics["failed_checks"] = failed.group(1)
    for line in text.splitlines():
        for key, pattern in CHECK_PATTERNS.items():
            match = pattern.search(line)
            if not match:
                continue
            if key == "max_nonortho":
                metrics["max_nonortho"] = match.group(1)
                metrics["avg_nonortho"] = match.group(2)
            elif key == "wall_substrate":
                metrics["wall_substrate_faces"] = match.group(1)
            else:
                metrics[key] = match.group(1)
    return metrics


def midpoint_unit(config: dict) -> np.ndarray:
    return np.full(len(bo_loop.parameter_keys(config)), 0.5, dtype=float)


def select_representatives(config: dict, count: int, seed: int) -> list[tuple[str, np.ndarray]]:
    rng = np.random.RandomState(seed)
    pool = bo_loop.generate_feasible_pool(config, rng, max(512, count * 128))
    rows = []
    for idx, unit in enumerate(pool):
        raw = bo_loop.scale_unit_to_raw(unit, config)
        params = bo_loop.convert_params(raw)
        if params is None:
            continue
        values = bo_loop.derived_values(raw, params)
        rows.append((idx, unit, raw, params, values))

    selected: list[tuple[str, np.ndarray]] = [("midpoint", midpoint_unit(config))]
    pick_specs = [
        ("min_R", "R_mm", min),
        ("max_R", "R_mm", max),
        ("min_t", "t_mm", min),
        ("max_t", "t_mm", max),
        ("max_axial", "axial_mm", max),
        ("max_R3", "R3_mm", max),
        ("max_l2y", "l2y_mm", max),
        ("min_theta0", "theta0_deg", min),
        ("max_theta0", "theta0_deg", max),
    ]
    used: set[tuple[float, ...]] = {tuple(np.round(selected[0][1], 10))}
    for label, key, reducer in pick_specs:
        if len(selected) >= count:
            break
        row = reducer(rows, key=lambda item: item[4][key])
        token = tuple(np.round(row[1], 10))
        if token in used:
            continue
        selected.append((label, row[1]))
        used.add(token)

    order = rng.permutation(len(pool))
    for idx in order:
        if len(selected) >= count:
            break
        unit = pool[int(idx)]
        token = tuple(np.round(unit, 10))
        if token in used:
            continue
        selected.append((f"random_{len(selected):02d}", unit))
        used.add(token)
    return selected[:count]


def select_random(config: dict, count: int, seed: int) -> list[tuple[str, np.ndarray]]:
    rng = np.random.RandomState(seed)
    pool = bo_loop.generate_feasible_pool(config, rng, max(512, count * 128))
    order = rng.permutation(len(pool))
    selected: list[tuple[str, np.ndarray]] = []
    used: set[tuple[float, ...]] = set()
    for idx in order:
        unit = pool[int(idx)]
        token = tuple(np.round(unit, 10))
        if token in used:
            continue
        selected.append((f"random_{len(selected):02d}", unit))
        used.add(token)
        if len(selected) >= count:
            break
    return selected


def parse_simplefoam(path: Path) -> dict[str, str]:
    metrics = {
        "simplefoam_ok": "no",
        "simplefoam_end_time": "",
        "simplefoam_local_cont": "",
        "simplefoam_global_cont": "",
        "simplefoam_cumulative_cont": "",
    }
    if not path.exists():
        return metrics
    text = path.read_text(errors="replace")
    metrics["simplefoam_ok"] = "yes" if re.search(r"(?m)^End$", text) else "no"
    for line in text.splitlines():
        time_match = SIMPLEFOAM_PATTERNS["time"].search(line)
        if time_match:
            metrics["simplefoam_end_time"] = time_match.group(1)
            continue
        cont_match = SIMPLEFOAM_PATTERNS["continuity"].search(line)
        if cont_match:
            metrics["simplefoam_local_cont"] = cont_match.group(1)
            metrics["simplefoam_global_cont"] = cont_match.group(2)
            metrics["simplefoam_cumulative_cont"] = cont_match.group(3)
    return metrics


def validate_case(
    case_dir: Path,
    openfoam_bashrc: Path,
    run_simplefoam: bool,
    cfd_end_time: float,
) -> tuple[str, dict[str, str]]:
    commands = [
        ("mesh", "python3 meshGen2.py > log.meshGen 2>&1"),
        ("gmshToFoam", f"source {openfoam_bashrc}; gmshToFoam meshData.msh > log.gmshToFoam 2>&1"),
        ("changeBCType", f"source {openfoam_bashrc}; python3 changeBCType.py > log.changeBCType 2>&1"),
        ("checkMesh", f"source {openfoam_bashrc}; checkMesh > log.checkMesh 2>&1"),
    ]
    for stage, command in commands:
        code, output = run_command(command, case_dir)
        if code != 0:
            write_text(case_dir / f"log.{stage}.driver", output)
            metrics = parse_check_mesh(case_dir / "log.checkMesh")
            metrics["status"] = f"failed:{stage}"
            return stage, metrics
    metrics = parse_check_mesh(case_dir / "log.checkMesh")
    metrics["status"] = "ok" if metrics["mesh_ok"] == "yes" else "checkMesh_failed"
    if metrics["status"] != "ok" or not run_simplefoam:
        return "done", metrics

    cfd_commands = [
        (
            "setEndTime",
            f"source {openfoam_bashrc}; foamDictionary -entry endTime -set {cfd_end_time:g} system/controlDict",
        ),
        ("BC_omega", f"source {openfoam_bashrc}; python3 BC_omega.py > log.BC_omega 2>&1"),
        ("BC_U", f"source {openfoam_bashrc}; python3 BC_U.py > log.BC_U 2>&1"),
        ("simpleFoam", f"source {openfoam_bashrc}; simpleFoam > log.simpleFoam 2>&1"),
    ]
    for stage, command in cfd_commands:
        code, output = run_command(command, case_dir)
        if code != 0:
            write_text(case_dir / f"log.{stage}.driver", output)
            metrics.update(parse_simplefoam(case_dir / "log.simpleFoam"))
            metrics["status"] = f"failed:{stage}"
            return stage, metrics
    metrics.update(parse_simplefoam(case_dir / "log.simpleFoam"))
    if metrics["simplefoam_ok"] != "yes":
        metrics["status"] = "simpleFoam_failed"
    return "done", metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "bo_config.json")
    parser.add_argument("--outdir", type=Path, default=REPO_ROOT / "test_cases" / "structured_mesh_sweep")
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--wedge-deg", type=float, default=1.0)
    parser.add_argument("--selection", choices=("representative", "random"), default="representative")
    parser.add_argument("--run-simplefoam", action="store_true")
    parser.add_argument("--cfd-end-time", type=float, default=20.0)
    parser.add_argument(
        "--openfoam-bashrc",
        type=Path,
        default=Path("/usr/lib/openfoam/openfoam2406/etc/bashrc"),
    )
    args = parser.parse_args()

    config, _ = bo_loop.load_config(args.config)
    if args.selection == "random":
        selected = select_random(config, args.cases, args.seed)
    else:
        selected = select_representatives(config, args.cases, args.seed)
    args.outdir.mkdir(parents=True, exist_ok=True)

    rows = []
    for index, (label, unit) in enumerate(selected):
        raw = bo_loop.scale_unit_to_raw(unit, config)
        params = bo_loop.convert_params(raw)
        if params is None:
            continue
        case_name = f"{index:02d}_{label}"
        case_dir = args.outdir / case_name
        prepare_case(case_dir, params, config["output_keys"], args.wedge_deg)
        _, metrics = validate_case(case_dir, args.openfoam_bashrc, args.run_simplefoam, args.cfd_end_time)
        row = {
            "case": case_name,
            "label": label,
            "R_mm": f"{params['R_mm']:.6g}",
            "t_mm": f"{params['t_mm']:.6g}",
            "axial_mm": f"{bo_loop.derived_values(raw, params)['axial_mm']:.6g}",
            "R3_mm": f"{params['R3_mm']:.6g}",
            "l2y_mm": f"{params['l2y_mm']:.6g}",
            "wedge_deg": f"{args.wedge_deg:.6g}",
        }
        row.update(metrics)
        rows.append(row)
        print(
            f"{case_name}: {row['status']} cells={row.get('cells', '')} "
            f"nonOrtho={row.get('max_nonortho', '')} skew={row.get('max_skew', '')} "
            f"simpleFoam={row.get('simplefoam_ok', '')}"
        )

    fieldnames = [
        "case",
        "label",
        "status",
        "mesh_ok",
        "R_mm",
        "t_mm",
        "axial_mm",
        "R3_mm",
        "l2y_mm",
        "wedge_deg",
        "points",
        "cells",
        "hex",
        "prism",
        "wall_substrate_faces",
        "max_aspect",
        "max_nonortho",
        "avg_nonortho",
        "max_skew",
        "failed_checks",
        "default_faces",
        "invalid_faces",
        "simplefoam_ok",
        "simplefoam_end_time",
        "simplefoam_local_cont",
        "simplefoam_global_cont",
        "simplefoam_cumulative_cont",
    ]
    summary_csv = args.outdir / "summary.csv"
    with summary_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if row.get("status") != "ok"]
    print(f"summary: {summary_csv}")
    print(f"passed={len(rows) - len(failures)} failed={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
