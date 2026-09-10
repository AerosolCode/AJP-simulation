#!/usr/bin/env python3
"""Bayesian optimization loop driver for the AJP simulation pipeline.

The script intentionally depends only on Python's standard library and numpy so
it can run on the xeon login node without pandas/scipy/sklearn.
"""

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np


DEFAULT_CONFIG = {
    "workdir": ".",
    "template_root": ".",
    "base_template": "base",
    "particle_template": "baseparticle",
    "particle_script": "loopaerosolDynamics.sh",
    "case_prefix": "case",
    "case_width": 4,
    "seed": 20260715,
    "parameters": {
        "R_mm": [0.5, 2.0],
        "alphaRin": [0.3, 0.7],
        "alphaL0": [1.0, 5.0],
        "L1_mm": [1.0, 20.0],
        "alphaL2": [0.5, 5.0],
        "alphaL3": [0.0, 1.0],
        "theta0_deg": [10.0, 60.0],
        "theta1_deg": [10.0, 60.0],
        "alphaTheta2": [0.0, 1.0],
        "alphat": [0.5, 5.0],
        "U_mps": [1.0, 50.0],
    },
    "output_keys": [
        "R_mm",
        "Rin_mm",
        "L0_mm",
        "L1_mm",
        "L2_mm",
        "L3_mm",
        "L4_mm",
        "t_mm",
        "theta0_deg",
        "theta1_deg",
        "theta2_deg",
        "U_mps",
        "Qaerosol_lpm",
        "Qsheath_lpm",
        "R1_mm",
        "R2_mm",
        "R3_mm",
        "l1_mm",
        "l2_mm",
        "l1x_mm",
        "l1y_mm",
        "l2x_mm",
        "l2y_mm",
    ],
    "objective": {
        "total_particles": 10000,
        "version": "central_target_d10um_v2_lexicographic",
        "mode": "target_lexicographic",
        "target": {
            "center_m": [0.0, 0.0],
            "diameter_um": 10.0,
        },
        "compactness": {
            "plane_axes": ["x", "z"],
            "radius_quantile": 0.9,
            "reference_radius": "R_mm",
            "min_particles": 20,
        },
        "target_compactness": {
            "min_particles": 20,
        },
        "tie_break_particles": 0.25,
        "secondary_clip": 1.0,
        "weights": {
            "targeted_deposition_compactness": 0.3,
            "substrate_overspray_fraction": -1.0,
            "wall_deposition_fraction": -1.0,
            "outlet_fraction": -0.2,
            "unresolved_fraction": -0.5,
        },
        "failure_score": -2.0,
    },
    "bo": {
        "gp_min_points": 5,
        "candidate_pool": 4096,
        "lengthscale": 0.35,
        "noise": 1.0e-6,
        "xi": 0.01,
        "min_distance": 1.0e-3,
    },
    "constraints": {
        "max": {},
        "min": {},
    },
    "slurm": {
        "sbatch": "sbatch",
        "squeue": "squeue",
        "user": "",
        "particle_job_prefix": "P_",
    },
}

PATCHES = ("outlet", "wallSubstrate", "wallUpper", "wallDown", "wallCavity")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def deep_merge(base, override):
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path):
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path).expanduser() if path else None
    if config_path and config_path.exists():
        with config_path.open() as f:
            loaded = json.load(f)
        config = deep_merge(config, loaded)
        loaded_weights = loaded.get("objective", {}).get("weights")
        if loaded_weights is not None:
            config["objective"]["weights"] = deepcopy(loaded_weights)
        config_dir = config_path.resolve().parent
    else:
        config_dir = Path.cwd().resolve()
    return config, config_dir


def resolve_path(value, base_dir):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def get_paths(config, config_dir):
    workdir = resolve_path(config["workdir"], config_dir)
    template_root = resolve_path(config.get("template_root", "."), config_dir)
    base_template = resolve_path(config["base_template"], template_root)
    particle_template = resolve_path(config["particle_template"], template_root)
    return workdir, base_template, particle_template


def particle_script_name(config):
    return config.get("particle_script", "loopaerosolDynamics.sh")


def parameter_keys(config):
    return list(config["parameters"].keys())


def scale_unit_to_raw(unit, config):
    raw = {}
    for value, key in zip(unit, parameter_keys(config)):
        low, high = config["parameters"][key]
        raw[key] = float(low) + (float(high) - float(low)) * float(value)
    return raw


def raw_to_unit(raw, config):
    unit = []
    for key in parameter_keys(config):
        low, high = config["parameters"][key]
        unit.append((float(raw[key]) - float(low)) / (float(high) - float(low)))
    return np.asarray(unit, dtype=float)


def convert_params(raw):
    r = raw["R_mm"]
    l0 = raw["alphaL0"] * r
    r1 = r + raw["L1_mm"] * math.tan(math.radians(raw["theta0_deg"]))
    rin = raw["alphaRin"] * r1
    l3min_mm = rin + 1.0
    l3max_mm = r1 - 1.0
    if l3min_mm >= l3max_mm:
        return None

    l3 = r1 - l3min_mm - (l3max_mm - l3min_mm) * raw["alphaL3"]
    theta2 = raw["alphaTheta2"] * (raw["theta1_deg"] - 10.0) + 10.0

    u = raw["U_mps"]
    q = math.pi * r**2 * u
    denom = rin**2 + r1**2 - (r1 - l3) ** 2
    if denom <= 0.0:
        return None
    qaerosol = q * rin**2 / denom
    qsheath = q - qaerosol

    l1 = 3.0 * l3
    l1x = l1 * math.sin(math.radians(raw["theta1_deg"]))
    l1y = l1 * math.cos(math.radians(raw["theta1_deg"]))
    l2x = l1x + l3
    sin_theta2 = math.sin(math.radians(theta2))
    tan_theta2 = math.tan(math.radians(theta2))
    if abs(sin_theta2) < 1.0e-12 or abs(tan_theta2) < 1.0e-12:
        return None
    l2 = l2x / sin_theta2
    l2y = l2x / tan_theta2

    r2 = r1 + l1x
    r3 = r2 + (l2x - l1x) * 5.0

    return {
        "R_mm": r,
        "L0_mm": l0,
        "R1_mm": r1,
        "Rin_mm": rin,
        "L1_mm": raw["L1_mm"],
        "L2_mm": raw["alphaL2"] * r1,
        "L3_mm": l3,
        "L4_mm": 5.0 * rin,
        "t_mm": raw["alphat"] * r,
        "theta0_deg": raw["theta0_deg"],
        "theta1_deg": raw["theta1_deg"],
        "theta2_deg": theta2,
        "U_mps": raw["U_mps"],
        "Qaerosol_lpm": qaerosol / 1000.0 * 60.0,
        "Qsheath_lpm": qsheath / 1000.0 * 60.0,
        "R2_mm": r2,
        "R3_mm": r3,
        "l1_mm": l1,
        "l2_mm": l2,
        "l1x_mm": l1x,
        "l1y_mm": l1y,
        "l2x_mm": l2x,
        "l2y_mm": l2y,
    }


def derived_values(raw, params):
    values = dict(raw)
    values.update(params)
    values["axial_mm"] = (
        float(values.get("t_mm", 0.0))
        + float(values.get("L0_mm", 0.0))
        + float(values.get("L1_mm", 0.0))
        + float(values.get("L2_mm", 0.0))
        + float(values.get("L4_mm", 0.0))
    )
    return values


def passes_constraints(raw, params, config):
    constraints = config.get("constraints", {})
    if not constraints:
        return True
    values = derived_values(raw, params)
    for key, limit in constraints.get("min", {}).items():
        if key in values and float(values[key]) < float(limit):
            return False
    for key, limit in constraints.get("max", {}).items():
        if key in values and float(values[key]) > float(limit):
            return False
    return True


def write_params_dat(path, params, output_keys):
    with path.open("w") as f:
        for key in output_keys:
            f.write("%s=%.8f\n" % (key, params[key]))


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def append_csv_rows(path, rows, fieldnames):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
            existing_fields = reader.fieldnames or []
        if existing_fields != fieldnames:
            merged_fields = list(fieldnames)
            for field in existing_fields:
                if field not in merged_fields:
                    merged_fields.append(field)
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=merged_fields, extrasaction="ignore")
                writer.writeheader()
                for row in existing_rows:
                    writer.writerow(row)
            fieldnames = merged_fields
    write_header = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def candidate_fieldnames(config):
    raw_keys = parameter_keys(config)
    output_keys = [key for key in config["output_keys"] if key not in raw_keys]
    return ["case", "generation", "method", "created_at"] + raw_keys + output_keys


def observation_fieldnames(config):
    return candidate_fieldnames(config) + [
        "completed_at",
        "objective_version",
        "evaluation_status",
        "score",
        "n_outlet",
        "n_substrate",
        "n_target",
        "n_substrate_overspray",
        "n_wall_deposition",
        "n_wall_upper",
        "n_wall_down",
        "n_wall_cavity",
        "n_overspray",
        "n_resolved",
        "total_particles",
        "target_center_x_m",
        "target_center_z_m",
        "target_diameter_um",
        "target_radius_um",
        "target_fraction",
        "target_precision",
        "substrate_fraction",
        "substrate_resolved_fraction",
        "substrate_overspray_fraction",
        "wall_deposition_fraction",
        "overspray_fraction",
        "outlet_fraction",
        "resolved_ratio",
        "unresolved_fraction",
        "deposit_centroid_x_mm",
        "deposit_centroid_z_mm",
        "deposit_rms_radius_mm",
        "deposit_r90_radius_mm",
        "deposit_footprint_area90_mm2",
        "deposit_density_per_mm2",
        "deposition_spread_score",
        "deposition_particle_support",
        "deposition_compactness",
        "target_particle_support",
        "targeted_deposition_compactness",
        "target_rms_radius_um",
        "target_r90_radius_um",
        "target_centered_spread_score",
        "target_centered_particle_support",
        "target_centered_compactness",
        "resolved_constraint",
        "wall_constraint",
        "objective_primary_score",
        "objective_secondary_raw",
        "objective_secondary_score",
        "objective_tie_break_scale",
        "source_objective_version",
        "source_score",
    ]


def copy_template_contents(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError("template does not exist: %s" % src)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(target), dirs_exist_ok=True)
        else:
            shutil.copy2(str(item), str(target))


def prepare_case(case_dir, base_template, params, output_keys):
    existed = case_dir.exists()
    case_dir.mkdir(parents=True, exist_ok=True)
    write_params_dat(case_dir / "params.dat", params, output_keys)
    if not existed or not (case_dir / "run.sh").exists():
        copy_template_contents(base_template, case_dir)
    return not existed


def case_pattern(config):
    prefix = re.escape(config["case_prefix"])
    return re.compile(r"^%s_(\d+)$" % prefix)


def next_case_index(candidates, workdir, config):
    pattern = case_pattern(config)
    indices = []
    for row in candidates:
        match = pattern.match(row.get("case", ""))
        if match:
            indices.append(int(match.group(1)))
    if workdir.exists():
        for child in workdir.iterdir():
            if child.is_dir():
                match = pattern.match(child.name)
                if match:
                    indices.append(int(match.group(1)))
    return max(indices) + 1 if indices else 0


def generation_number(candidates):
    generations = []
    for row in candidates:
        try:
            generations.append(int(row.get("generation", "0")))
        except ValueError:
            pass
    return max(generations) + 1 if generations else 0


def generate_feasible_pool(config, rng, size):
    dim = len(parameter_keys(config))
    points = []
    attempts = 0
    max_attempts = max(size * 200, 10000)
    while len(points) < size and attempts < max_attempts:
        batch_size = min(max((size - len(points)) * 3, 64), 4096)
        batch = rng.rand(batch_size, dim)
        attempts += batch_size
        for unit in batch:
            raw = scale_unit_to_raw(unit, config)
            params = convert_params(raw)
            if params is not None and passes_constraints(raw, params, config):
                points.append(unit)
                if len(points) >= size:
                    break
    if not points:
        raise RuntimeError("could not generate any feasible design points")
    return np.asarray(points, dtype=float)


def existing_units_from_rows(rows, config):
    units = []
    for row in rows:
        try:
            raw = {key: float(row[key]) for key in parameter_keys(config)}
            units.append(raw_to_unit(raw, config))
        except (KeyError, TypeError, ValueError):
            continue
    if not units:
        return np.empty((0, len(parameter_keys(config))), dtype=float)
    return np.vstack(units)


def min_distance_to_set(pool, existing):
    if existing.size == 0:
        return np.full(pool.shape[0], np.inf)
    diff = pool[:, None, :] - existing[None, :, :]
    dist = np.sqrt(np.sum(diff * diff, axis=2))
    return np.min(dist, axis=1)


def select_maximin(pool, existing, batch_size, min_distance):
    selected = []
    selected_indices = []
    available = np.ones(pool.shape[0], dtype=bool)
    current_existing = existing
    for _ in range(batch_size):
        candidates = pool[available]
        if candidates.size == 0:
            break
        distances = min_distance_to_set(candidates, current_existing)
        if np.isfinite(distances).any():
            local_idx = int(np.argmax(distances))
            if distances[local_idx] < min_distance and selected:
                break
        else:
            local_idx = 0
        global_indices = np.flatnonzero(available)
        global_idx = int(global_indices[local_idx])
        selected.append(pool[global_idx])
        selected_indices.append(global_idx)
        available[global_idx] = False
        current_existing = np.vstack([current_existing, pool[global_idx][None, :]])
    return np.asarray(selected, dtype=float), selected_indices


def rbf_kernel(x1, x2, lengthscale):
    diff = x1[:, None, :] - x2[None, :, :]
    sqdist = np.sum(diff * diff, axis=2)
    return np.exp(-0.5 * sqdist / (lengthscale * lengthscale))


def normal_cdf(values):
    flat = values.ravel()
    out = [0.5 * (1.0 + math.erf(float(v) / math.sqrt(2.0))) for v in flat]
    return np.asarray(out, dtype=float).reshape(values.shape)


def expected_improvement(mu, sigma, best, xi):
    sigma = np.maximum(sigma, 1.0e-12)
    improvement = mu - best - xi
    z = improvement / sigma
    pdf = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cdf = normal_cdf(z)
    ei = improvement * cdf + sigma * pdf
    ei[sigma <= 1.0e-12] = 0.0
    return ei


def gp_predict(x_train, y_train, x_pool, config):
    bo_config = config["bo"]
    lengthscale = float(bo_config["lengthscale"])
    noise = float(bo_config["noise"])

    y_mean = float(np.mean(y_train))
    y_std = float(np.std(y_train))
    if y_std < 1.0e-12:
        y_std = 1.0
    y_scaled = (y_train - y_mean) / y_std

    k_train = rbf_kernel(x_train, x_train, lengthscale)
    eye = np.eye(x_train.shape[0])
    last_error = None
    for jitter in (0.0, 1.0e-10, 1.0e-8, 1.0e-6, 1.0e-4):
        try:
            chol = np.linalg.cholesky(k_train + (noise + jitter) * eye)
            break
        except np.linalg.LinAlgError as exc:
            last_error = exc
    else:
        raise RuntimeError("GP Cholesky failed: %s" % last_error)

    k_star = rbf_kernel(x_train, x_pool, lengthscale)
    alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y_scaled))
    mu_scaled = k_star.T.dot(alpha)
    v = np.linalg.solve(chol, k_star)
    var = np.maximum(1.0 - np.sum(v * v, axis=0), 1.0e-12)
    return mu_scaled * y_std + y_mean, np.sqrt(var) * y_std


def load_observation_xy(observations, config):
    x_rows = []
    y_values = []
    objective_version = str(config.get("objective", {}).get("version", "unversioned"))
    for row in observations:
        if row.get("objective_version") != objective_version:
            continue
        try:
            raw = {key: float(row[key]) for key in parameter_keys(config)}
            score = float(row["score"])
        except (KeyError, TypeError, ValueError):
            continue
        x_rows.append(raw_to_unit(raw, config))
        y_values.append(score)
    if not x_rows:
        return np.empty((0, len(parameter_keys(config))), dtype=float), np.empty(0)
    return np.vstack(x_rows), np.asarray(y_values, dtype=float)


def select_gp_ei(pool, existing, observations, batch_size, config):
    x_train, y_train = load_observation_xy(observations, config)
    if x_train.shape[0] < int(config["bo"]["gp_min_points"]):
        selected, _ = select_maximin(pool, existing, batch_size, float(config["bo"]["min_distance"]))
        return selected, "maximin_initial"

    try:
        mu, sigma = gp_predict(x_train, y_train, pool, config)
        ei = expected_improvement(
            mu,
            sigma,
            float(np.max(y_train)),
            float(config["bo"]["xi"]),
        )
    except RuntimeError:
        selected, _ = select_maximin(pool, existing, batch_size, float(config["bo"]["min_distance"]))
        return selected, "maximin_gp_fallback"

    order = list(np.argsort(-ei))
    selected = []
    min_distance = float(config["bo"]["min_distance"])
    current_existing = existing.copy()
    for idx in order:
        candidate = pool[int(idx)]
        if current_existing.size:
            distance = np.min(np.sqrt(np.sum((current_existing - candidate) ** 2, axis=1)))
            if distance < min_distance:
                continue
        selected.append(candidate)
        current_existing = np.vstack([current_existing, candidate[None, :]])
        if len(selected) >= batch_size:
            break

    if len(selected) < batch_size:
        fill, _ = select_maximin(pool, current_existing, batch_size - len(selected), min_distance)
        if fill.size:
            selected.extend(list(fill))
    return np.asarray(selected, dtype=float), "gp_ei"


def select_candidates(pool, existing, pending, observations, batch_size, config):
    strategy = str(config.get("bo", {}).get("strategy", "scalar_ei"))
    if strategy != "qlognehvi":
        return select_gp_ei(pool, existing, observations, batch_size, config)

    import mobo

    valid_rows = mobo.valid_observation_rows(observations, config)
    gp_min_points = int(config.get("bo", {}).get("gp_min_points", 32))
    if len(valid_rows) < gp_min_points:
        selected, _ = select_maximin(
            pool,
            existing,
            batch_size,
            float(config["bo"]["min_distance"]),
        )
        return selected, "maximin_initial_mobo"

    try:
        return mobo.select_qlognehvi(
            pool,
            existing,
            pending,
            observations,
            batch_size,
            config,
        )
    except Exception as exc:
        print("qLogNEHVI failed; using maximin fallback:", exc, file=sys.stderr)
        selected, _ = select_maximin(
            pool,
            existing,
            batch_size,
            float(config["bo"]["min_distance"]),
        )
        return selected, "maximin_mobo_fallback"


def particle_summary(csv_path, config):
    counts = {patch: 0 for patch in PATCHES}
    compactness_config = config.get("objective", {}).get("compactness", {})
    axes = compactness_config.get("plane_axes", ["x", "z"])
    substrate_points = []
    with Path(csv_path).open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            patch = row.get("patch")
            if patch in counts:
                counts[patch] += 1
            if patch == "wallSubstrate":
                try:
                    substrate_points.append([float(row[axis]) for axis in axes])
                except (KeyError, TypeError, ValueError):
                    pass
    return counts, np.asarray(substrate_points, dtype=float)


def compactness_reference_radius_mm(candidate, config):
    compactness_config = config.get("objective", {}).get("compactness", {})
    reference = compactness_config.get("reference_radius", "R_mm")
    if isinstance(reference, (int, float)):
        return max(float(reference), 1.0e-12)
    try:
        return max(float(candidate.get(str(reference), 1.0)), 1.0e-12)
    except (TypeError, ValueError):
        return 1.0


def deposition_metrics(substrate_points, candidate, config):
    compactness_config = config.get("objective", {}).get("compactness", {})
    radius_quantile = float(compactness_config.get("radius_quantile", 0.9))
    radius_quantile = min(max(radius_quantile, 0.0), 1.0)
    min_particles = max(int(compactness_config.get("min_particles", 20)), 1)

    metrics = {
        "deposit_centroid_x_mm": 0.0,
        "deposit_centroid_z_mm": 0.0,
        "deposit_rms_radius_mm": 0.0,
        "deposit_r90_radius_mm": 0.0,
        "deposit_footprint_area90_mm2": 0.0,
        "deposit_density_per_mm2": 0.0,
        "deposition_spread_score": 0.0,
        "deposition_particle_support": 0.0,
        "deposition_compactness": 0.0,
    }
    if substrate_points.size == 0:
        return metrics

    points_mm = substrate_points * 1000.0
    centroid = np.mean(points_mm, axis=0)
    centered = points_mm - centroid
    radii = np.sqrt(np.sum(centered * centered, axis=1))
    rms_radius = float(np.sqrt(np.mean(radii * radii)))
    q_radius = float(np.quantile(radii, radius_quantile))
    area = math.pi * max(q_radius, 1.0e-12) ** 2
    density = float(substrate_points.shape[0]) / area

    reference_radius = compactness_reference_radius_mm(candidate, config)
    spread_score = 1.0 / (1.0 + q_radius / reference_radius)
    particle_support = min(1.0, float(substrate_points.shape[0]) / float(min_particles))
    compactness = spread_score * particle_support

    metrics.update(
        {
            "deposit_centroid_x_mm": float(centroid[0]),
            "deposit_centroid_z_mm": float(centroid[1]) if centroid.shape[0] > 1 else 0.0,
            "deposit_rms_radius_mm": rms_radius,
            "deposit_r90_radius_mm": q_radius,
            "deposit_footprint_area90_mm2": area,
            "deposit_density_per_mm2": density,
            "deposition_spread_score": spread_score,
            "deposition_particle_support": particle_support,
            "deposition_compactness": compactness,
        }
    )
    return metrics


def target_deposition_metrics(substrate_points, n_substrate, config):
    target_config = config.get("objective", {}).get("target", {})
    center = target_config.get("center_m", [0.0, 0.0])
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        raise ValueError("objective.target.center_m must contain two coordinates")
    center_array = np.asarray([float(center[0]), float(center[1])], dtype=float)
    diameter_um = float(target_config.get("diameter_um", 10.0))
    if diameter_um <= 0.0:
        raise ValueError("objective.target.diameter_um must be positive")
    radius_m = diameter_um * 0.5e-6

    n_target = 0
    if substrate_points.size:
        points = np.asarray(substrate_points, dtype=float).reshape((-1, 2))
        radii = np.sqrt(np.sum((points - center_array) ** 2, axis=1))
        n_target = int(np.count_nonzero(radii <= radius_m))

    # Missing substrate coordinates receive no target credit.
    n_substrate_overspray = max(int(n_substrate) - n_target, 0)
    return {
        "target_center_x_m": float(center_array[0]),
        "target_center_z_m": float(center_array[1]),
        "target_diameter_um": diameter_um,
        "target_radius_um": diameter_um / 2.0,
        "n_target": n_target,
        "n_substrate_overspray": n_substrate_overspray,
    }


def target_centered_deposition_metrics(substrate_points, n_target, config):
    target_config = config.get("objective", {}).get("target", {})
    center = target_config.get("center_m", [0.0, 0.0])
    if not isinstance(center, (list, tuple)) or len(center) != 2:
        raise ValueError("objective.target.center_m must contain two coordinates")
    center_array = np.asarray([float(center[0]), float(center[1])], dtype=float)
    diameter_um = float(target_config.get("diameter_um", 10.0))
    if diameter_um <= 0.0:
        raise ValueError("objective.target.diameter_um must be positive")
    target_radius_um = diameter_um / 2.0

    metrics = {
        "target_rms_radius_um": 0.0,
        "target_r90_radius_um": 0.0,
        "target_centered_spread_score": 0.0,
        "target_centered_particle_support": 0.0,
        "target_centered_compactness": 0.0,
    }
    if substrate_points.size == 0:
        return metrics

    points = np.asarray(substrate_points, dtype=float).reshape((-1, 2))
    radii_um = np.sqrt(np.sum((points - center_array) ** 2, axis=1)) * 1.0e6
    compactness_config = config.get("objective", {}).get(
        "target_centered_compactness",
        {},
    )
    radius_quantile = float(compactness_config.get("radius_quantile", 0.9))
    radius_quantile = min(max(radius_quantile, 0.0), 1.0)
    min_particles = max(int(compactness_config.get("min_particles", 20)), 1)
    rms_radius_um = float(np.sqrt(np.mean(radii_um * radii_um)))
    r90_radius_um = float(np.quantile(radii_um, radius_quantile))
    spread_score = target_radius_um / (target_radius_um + r90_radius_um)
    particle_support = min(1.0, float(n_target) / float(min_particles))

    metrics.update(
        {
            "target_rms_radius_um": rms_radius_um,
            "target_r90_radius_um": r90_radius_um,
            "target_centered_spread_score": spread_score,
            "target_centered_particle_support": particle_support,
            "target_centered_compactness": spread_score * particle_support,
        }
    )
    return metrics


def objective_score(metrics, config, total_particles):
    objective = config.get("objective", {})
    mode = str(objective.get("mode", "weighted_sum"))
    if mode == "multi_objective":
        primary_score = float(metrics.get("target_fraction", 0.0))
        metrics["objective_primary_score"] = primary_score
        metrics["objective_secondary_raw"] = 0.0
        metrics["objective_secondary_score"] = 0.0
        metrics["objective_tie_break_scale"] = 0.0
        return primary_score

    secondary_raw = 0.0
    for key, weight in objective.get("weights", {}).items():
        secondary_raw += float(weight) * float(metrics.get(key, 0.0))

    if mode == "weighted_sum":
        metrics["objective_primary_score"] = 0.0
        metrics["objective_secondary_raw"] = secondary_raw
        metrics["objective_secondary_score"] = secondary_raw
        metrics["objective_tie_break_scale"] = 1.0
        return secondary_raw
    if mode != "target_lexicographic":
        raise ValueError("unsupported objective mode: %s" % mode)

    secondary_clip = abs(float(objective.get("secondary_clip", 1.0)))
    if secondary_clip <= 0.0:
        raise ValueError("objective.secondary_clip must be positive")
    secondary_score = min(max(secondary_raw / secondary_clip, -1.0), 1.0)
    tie_break_particles = float(objective.get("tie_break_particles", 0.25))
    if not 0.0 <= tie_break_particles < 0.5:
        raise ValueError("objective.tie_break_particles must be in [0, 0.5)")

    denominator = float(total_particles) if total_particles > 0 else 1.0
    tie_break_scale = tie_break_particles / denominator
    primary_score = float(metrics.get("target_fraction", 0.0))
    metrics["objective_primary_score"] = primary_score
    metrics["objective_secondary_raw"] = secondary_raw
    metrics["objective_secondary_score"] = secondary_score
    metrics["objective_tie_break_scale"] = tie_break_scale
    return primary_score + tie_break_scale * secondary_score


def parse_kv_file(path):
    data = {}
    try:
        with Path(path).open("r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
    except OSError:
        pass
    return data


def parse_vector_field_size(path):
    try:
        lines = Path(path).read_text(errors="ignore").splitlines()
    except OSError:
        return None
    after_header = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not after_header:
            if line == "}":
                after_header = True
            continue
        if re.fullmatch(r"\d+", line):
            return int(line)
    return None


def count_manual_injection_bins(path):
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return None
    n = len(re.findall(r"\btype\s+manualInjection\s*;", text))
    return n or None


def particle_total_particles(particle_dir, config):
    default_total = int(config["objective"]["total_particles"])
    run_config = parse_kv_file(Path(particle_dir) / "particle_run_config.txt")
    if run_config.get("total_particles"):
        try:
            return max(int(float(run_config["total_particles"])), 1)
        except ValueError:
            pass

    n_positions = parse_vector_field_size(Path(particle_dir) / "constant" / "kinematicCloudPositions")
    n_bins = count_manual_injection_bins(Path(particle_dir) / "constant" / "kinematicCloudProperties")
    if n_positions and n_bins:
        return max(n_positions * n_bins, 1)
    return default_total


def compute_metrics(counts, substrate_points, candidate, config, total_particles=None):
    total = int(total_particles if total_particles is not None else config["objective"]["total_particles"])
    n_outlet = counts.get("outlet", 0)
    n_substrate = counts.get("wallSubstrate", 0)
    n_upper = counts.get("wallUpper", 0)
    n_down = counts.get("wallDown", 0)
    n_cavity = counts.get("wallCavity", 0)
    n_wall_deposition = n_upper + n_down + n_cavity
    target_metrics = target_deposition_metrics(substrate_points, n_substrate, config)
    n_target = target_metrics["n_target"]
    n_substrate_overspray = target_metrics["n_substrate_overspray"]
    n_resolved = n_outlet + n_substrate + n_wall_deposition
    denominator = float(total) if total > 0 else 1.0
    resolved_denominator = float(n_resolved) if n_resolved > 0 else 1.0

    metrics = {
        "objective_version": str(config.get("objective", {}).get("version", "unversioned")),
        "evaluation_status": "complete",
        "n_outlet": n_outlet,
        "n_substrate": n_substrate,
        "n_target": n_target,
        "n_substrate_overspray": n_substrate_overspray,
        "n_wall_deposition": n_wall_deposition,
        "n_wall_upper": n_upper,
        "n_wall_down": n_down,
        "n_wall_cavity": n_cavity,
        "n_overspray": n_substrate_overspray,
        "n_resolved": n_resolved,
        "total_particles": total,
        "target_fraction": n_target / denominator,
        "target_precision": n_target / float(n_substrate) if n_substrate > 0 else 0.0,
        "substrate_fraction": n_substrate / denominator,
        "substrate_resolved_fraction": n_substrate / resolved_denominator,
        "substrate_overspray_fraction": n_substrate_overspray / denominator,
        "wall_deposition_fraction": n_wall_deposition / denominator,
        "overspray_fraction": n_substrate_overspray / denominator,
        "outlet_fraction": n_outlet / denominator,
        "resolved_ratio": n_resolved / denominator,
        "unresolved_fraction": max(total - n_resolved, 0) / denominator,
    }
    metrics.update(target_metrics)
    metrics.update(deposition_metrics(substrate_points, candidate, config))
    metrics.update(
        target_centered_deposition_metrics(substrate_points, n_target, config)
    )
    target_compactness = config.get("objective", {}).get("target_compactness", {})
    target_min_particles = max(int(target_compactness.get("min_particles", 20)), 1)
    target_support = min(1.0, float(n_target) / float(target_min_particles))
    metrics["target_particle_support"] = target_support
    metrics["targeted_deposition_compactness"] = (
        target_support * metrics["deposition_compactness"]
    )
    constraints = config.get("objective", {}).get("constraints", {})
    resolved_min = float(constraints.get("resolved_ratio_min", 0.95))
    wall_max = float(constraints.get("wall_deposition_fraction_max", 0.05))
    metrics["resolved_constraint"] = resolved_min - metrics["resolved_ratio"]
    metrics["wall_constraint"] = metrics["wall_deposition_fraction"] - wall_max
    metrics["score"] = objective_score(metrics, config, total)
    return metrics


def candidates_path(workdir):
    return workdir / "bo_candidates.csv"


def observations_path(workdir):
    return workdir / "bo_observations.csv"


def collect_completed(config, workdir, include_partial=False, cases=None):
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    observed_cases = {row.get("case") for row in observations}
    wanted = set(cases) if cases else None
    new_rows = []

    for candidate in candidates:
        case = candidate.get("case")
        if wanted is not None and case not in wanted:
            continue
        if not case or case in observed_cases:
            continue
        case_dir = workdir / case
        if (case_dir / "CFD_FAILED").exists():
            counts = {patch: 0 for patch in PATCHES}
            substrate_points = np.empty((0, len(config.get("objective", {}).get("compactness", {}).get("plane_axes", ["x", "z"]))))
            metrics = compute_metrics(counts, substrate_points, candidate, config)
            metrics["evaluation_status"] = "cfd_failed"
            metrics["score"] = float(config.get("objective", {}).get("failure_score", -2.0))
            row = dict(candidate)
            row.update(metrics)
            row["completed_at"] = now_iso()
            new_rows.append(row)
            continue
        particle_dir = workdir / case / "baseparticle"
        fates_path = particle_dir / "particle_fates_all.csv"
        done_path = particle_dir / "PARTICLE_DONE"
        failed_path = particle_dir / "PARTICLE_FAILED"
        if failed_path.exists():
            if fates_path.exists():
                counts, substrate_points = particle_summary(fates_path, config)
            else:
                counts = {patch: 0 for patch in PATCHES}
                axes = (
                    config.get("objective", {})
                    .get("compactness", {})
                    .get("plane_axes", ["x", "z"])
                )
                substrate_points = np.empty((0, len(axes)))
            total_particles = particle_total_particles(particle_dir, config)
            metrics = compute_metrics(
                counts,
                substrate_points,
                candidate,
                config,
                total_particles=total_particles,
            )
            metrics["evaluation_status"] = "particle_failed"
            metrics["score"] = float(config.get("objective", {}).get("failure_score", -2.0))
            row = dict(candidate)
            row.update(metrics)
            row["completed_at"] = now_iso()
            new_rows.append(row)
            continue
        if not fates_path.exists():
            continue
        if not include_partial and not done_path.exists():
            continue
        counts, substrate_points = particle_summary(fates_path, config)
        total_particles = particle_total_particles(particle_dir, config)
        metrics = compute_metrics(counts, substrate_points, candidate, config, total_particles=total_particles)
        row = dict(candidate)
        row.update(metrics)
        row["completed_at"] = now_iso()
        new_rows.append(row)

    append_csv_rows(observations_path(workdir), new_rows, observation_fieldnames(config))
    print("collect: %d new completed cases" % len(new_rows))
    return new_rows


def queued_jobs(config):
    slurm = config.get("slurm", {})
    squeue = slurm.get("squeue", "squeue")
    user = slurm.get("user") or os.environ.get("USER") or ""
    cmd = [squeue, "-h", "-o", "%j"]
    if user:
        cmd[1:1] = ["-u", user]
    try:
        result = subprocess.run(cmd, check=False, text=True, capture_output=True)
    except FileNotFoundError:
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def latest_numeric_time(case_dir):
    latest = None
    latest_value = None
    for child in Path(case_dir).iterdir():
        if not child.is_dir():
            continue
        try:
            value = float(child.name)
        except ValueError:
            continue
        if latest_value is None or value > latest_value:
            latest = child.name
            latest_value = value
    return latest


def cfd_completed(case_dir):
    case_dir = Path(case_dir)
    if not (case_dir / "CFD_DONE").exists():
        return False

    latest = latest_numeric_time(case_dir)
    if latest is None or not (case_dir / latest / "U").exists():
        return False

    for log_name in ("log.simpleFoam", "log.simpleFoam.restart"):
        log_path = case_dir / log_name
        if not log_path.exists():
            continue
        try:
            with log_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(size - 8192, 0))
                tail = f.read().decode("utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"(?m)^End\s*$", tail):
            return True
    return False


def run_sbatch(case_dir, job_name, script, config, dry_run=False):
    sbatch = config.get("slurm", {}).get("sbatch", "sbatch")
    cmd = [sbatch, "--job-name", job_name, script]
    nodelist = config.get("slurm", {}).get("nodelist")
    if nodelist:
        cmd[1:1] = ["--nodelist", nodelist]
    if dry_run:
        print("dry-run:", " ".join(cmd), "(cwd=%s)" % case_dir)
        return True
    result = subprocess.run(cmd, cwd=str(case_dir), check=False, text=True, capture_output=True)
    if result.returncode == 0:
        print(result.stdout.strip())
        return True
    print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
    return False


def submit_cfd(config, workdir, cases=None, dry_run=False):
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    observed = {row.get("case") for row in observations}
    wanted = set(cases) if cases else None
    jobs = queued_jobs(config)
    submitted = 0
    skipped = 0

    for row in candidates:
        case = row.get("case")
        if not case or (wanted is not None and case not in wanted):
            continue
        if case in observed:
            skipped += 1
            continue
        case_dir = workdir / case
        if not case_dir.exists():
            skipped += 1
            continue
        if cfd_completed(case_dir):
            skipped += 1
            continue
        if case in jobs:
            skipped += 1
            continue

        script = "run.sh"
        if not (case_dir / script).exists():
            skipped += 1
            continue
        if run_sbatch(case_dir, case, script, config, dry_run=dry_run):
            submitted += 1
    print("submit-cfd: submitted=%d skipped=%d" % (submitted, skipped))
    return submitted


def ensure_particle_case(case_dir, particle_template, particle_script):
    particle_dir = case_dir / "baseparticle"
    if not particle_dir.exists():
        shutil.copytree(str(particle_template), str(particle_dir))
    elif not (particle_dir / particle_script).exists():
        copy_template_contents(particle_template, particle_dir)
    return particle_dir


def submit_particles(config, workdir, particle_template, cases=None, dry_run=False):
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    observed = {row.get("case") for row in observations}
    wanted = set(cases) if cases else None
    jobs = queued_jobs(config)
    prefix = config.get("slurm", {}).get("particle_job_prefix", "P_")
    particle_script = particle_script_name(config)
    submitted = 0
    skipped = 0

    for row in candidates:
        case = row.get("case")
        if not case or (wanted is not None and case not in wanted):
            continue
        if case in observed:
            skipped += 1
            continue
        case_dir = workdir / case
        if not cfd_completed(case_dir):
            skipped += 1
            continue
        particle_dir = case_dir / "baseparticle"
        if (particle_dir / "PARTICLE_DONE").exists():
            skipped += 1
            continue
        job_name = prefix + case
        if job_name in jobs:
            skipped += 1
            continue
        if dry_run:
            if not particle_dir.exists():
                print("dry-run: would copy", particle_template, "to", particle_dir)
        else:
            particle_dir = ensure_particle_case(case_dir, particle_template, particle_script)
        if not (particle_dir / particle_script).exists() and not dry_run:
            skipped += 1
            continue
        if run_sbatch(particle_dir, job_name, particle_script, config, dry_run=dry_run):
            submitted += 1
    print("submit-particles: submitted=%d skipped=%d" % (submitted, skipped))
    return submitted


def suggest(config, workdir, base_template, batch_size, submit=False, dry_run=False):
    workdir.mkdir(parents=True, exist_ok=True)
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    existing = existing_units_from_rows(candidates, config)
    observed_cases = {row.get("case") for row in observations}
    pending = existing_units_from_rows(
        [row for row in candidates if row.get("case") not in observed_cases],
        config,
    )

    seed = int(config.get("seed", 0)) + len(candidates) * 9973
    rng = np.random.RandomState(seed)
    pool = generate_feasible_pool(config, rng, int(config["bo"]["candidate_pool"]))
    selected, method = select_candidates(
        pool,
        existing,
        pending,
        observations,
        batch_size,
        config,
    )
    if selected.size == 0:
        print("suggest: no feasible candidates selected")
        return []

    start_index = next_case_index(candidates, workdir, config)
    generation = generation_number(candidates)
    width = int(config["case_width"])
    rows = []

    for offset, unit in enumerate(selected):
        raw = scale_unit_to_raw(unit, config)
        params = convert_params(raw)
        if params is None:
            continue
        case = "%s_%0*d" % (config["case_prefix"], width, start_index + offset)
        case_dir = workdir / case
        row = {
            "case": case,
            "generation": generation,
            "method": method,
            "created_at": now_iso(),
        }
        row.update(raw)
        row.update(params)
        rows.append(row)
        if not dry_run:
            prepare_case(case_dir, base_template, params, config["output_keys"])
        else:
            print("dry-run: would prepare", case_dir)

    if dry_run:
        print("suggest: dry-run selected %d cases with method=%s" % (len(rows), method))
        return rows

    append_csv_rows(candidates_path(workdir), rows, candidate_fieldnames(config))
    print("suggest: prepared %d cases with method=%s" % (len(rows), method))
    if submit and rows:
        submit_cfd(config, workdir, cases=[row["case"] for row in rows], dry_run=dry_run)
    return rows


def pending_count(config, workdir):
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    observed = {row.get("case") for row in observations}
    return sum(1 for row in candidates if row.get("case") not in observed)


def print_status(config, workdir):
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    observed = {row.get("case") for row in observations}
    jobs = queued_jobs(config)
    prefix = config.get("slurm", {}).get("particle_job_prefix", "P_")
    counts = {
        "completed": 0,
        "ready_collect": 0,
        "particle_queued": 0,
        "particle_ready": 0,
        "cfd_done": 0,
        "cfd_queued": 0,
        "prepared": 0,
        "missing": 0,
    }
    for row in candidates:
        case = row.get("case")
        case_dir = workdir / case
        particle_dir = case_dir / "baseparticle"
        if case in observed:
            counts["completed"] += 1
        elif (particle_dir / "PARTICLE_DONE").exists() and (particle_dir / "particle_fates_all.csv").exists():
            counts["ready_collect"] += 1
        elif prefix + case in jobs:
            counts["particle_queued"] += 1
        elif cfd_completed(case_dir):
            if particle_dir.exists():
                counts["particle_ready"] += 1
            else:
                counts["cfd_done"] += 1
        elif case in jobs:
            counts["cfd_queued"] += 1
        elif case_dir.exists():
            counts["prepared"] += 1
        else:
            counts["missing"] += 1

    print("workdir:", workdir)
    print("candidates:", len(candidates))
    print("observations:", len(observations))
    for key in sorted(counts):
        print("%s: %d" % (key, counts[key]))
    if observations:
        best = max(observations, key=lambda row: float(row.get("score", "-inf")))
        print("best:", best.get("case"), "score=%s" % best.get("score"))


def init_workdir(config, config_dir, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    with (workdir / "bo_config_snapshot.json").open("w") as f:
        json.dump(config, f, indent=2)
    print("initialized", workdir)


def step(config, workdir, base_template, particle_template, batch_size, max_pending, submit, dry_run):
    collect_completed(config, workdir)
    if submit:
        submit_particles(config, workdir, particle_template, dry_run=dry_run)
        submit_cfd(config, workdir, dry_run=dry_run)
    candidates = read_csv_rows(candidates_path(workdir))
    observations = read_csv_rows(observations_path(workdir))
    gp_min_points = int(config.get("bo", {}).get("gp_min_points", 0))
    if len(observations) < gp_min_points and len(candidates) >= gp_min_points:
        print(
            "step: initial design target prepared "
            "(candidates=%d observations=%d target=%d)"
            % (len(candidates), len(observations), gp_min_points)
        )
        return []
    remaining = max_pending - pending_count(config, workdir)
    if remaining <= 0:
        print("step: pending limit reached")
        return []
    return suggest(
        config,
        workdir,
        base_template,
        min(batch_size, remaining),
        submit=submit,
        dry_run=dry_run,
    )


def build_parser():
    parser = argparse.ArgumentParser(description="AJP Bayesian optimization loop")
    parser.add_argument("--config", default="bo_config.json")
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--template-root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("--initial-batch", type=int, default=0)
    init_p.add_argument("--submit", action="store_true")
    init_p.add_argument("--dry-run", action="store_true")

    suggest_p = sub.add_parser("suggest")
    suggest_p.add_argument("--batch-size", type=int, default=4)
    suggest_p.add_argument("--submit", action="store_true")
    suggest_p.add_argument("--dry-run", action="store_true")

    collect_p = sub.add_parser("collect")
    collect_p.add_argument("--include-partial", action="store_true")

    submit_cfd_p = sub.add_parser("submit-cfd")
    submit_cfd_p.add_argument("--dry-run", action="store_true")

    submit_particle_p = sub.add_parser("submit-particles")
    submit_particle_p.add_argument("--dry-run", action="store_true")

    status_p = sub.add_parser("status")
    status_p.set_defaults()

    step_p = sub.add_parser("step")
    step_p.add_argument("--batch-size", type=int, default=4)
    step_p.add_argument("--max-pending", type=int, default=16)
    step_p.add_argument("--submit", action="store_true")
    step_p.add_argument("--dry-run", action="store_true")

    loop_p = sub.add_parser("loop")
    loop_p.add_argument("--batch-size", type=int, default=4)
    loop_p.add_argument("--max-pending", type=int, default=16)
    loop_p.add_argument("--sleep", type=int, default=600)
    loop_p.add_argument("--submit", action="store_true")
    loop_p.add_argument("--dry-run", action="store_true")
    loop_p.add_argument("--iterations", type=int, default=0)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config, config_dir = load_config(args.config)
    if args.workdir:
        config["workdir"] = args.workdir
    if args.template_root:
        config["template_root"] = args.template_root
    workdir, base_template, particle_template = get_paths(config, config_dir)

    if args.command == "init":
        init_workdir(config, config_dir, workdir)
        if args.initial_batch > 0:
            suggest(config, workdir, base_template, args.initial_batch, submit=args.submit, dry_run=args.dry_run)
    elif args.command == "suggest":
        suggest(config, workdir, base_template, args.batch_size, submit=args.submit, dry_run=args.dry_run)
    elif args.command == "collect":
        collect_completed(config, workdir, include_partial=args.include_partial)
    elif args.command == "submit-cfd":
        submit_cfd(config, workdir, dry_run=args.dry_run)
    elif args.command == "submit-particles":
        submit_particles(config, workdir, particle_template, dry_run=args.dry_run)
    elif args.command == "status":
        print_status(config, workdir)
    elif args.command == "step":
        step(
            config,
            workdir,
            base_template,
            particle_template,
            args.batch_size,
            args.max_pending,
            args.submit,
            args.dry_run,
        )
    elif args.command == "loop":
        iteration = 0
        while True:
            iteration += 1
            print("loop iteration", iteration, now_iso())
            step(
                config,
                workdir,
                base_template,
                particle_template,
                args.batch_size,
                args.max_pending,
                args.submit,
                args.dry_run,
            )
            if args.iterations and iteration >= args.iterations:
                break
            time.sleep(args.sleep)
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    main()
