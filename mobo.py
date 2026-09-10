"""Multi-objective utilities and BoTorch qLogNEHVI candidate selection."""

from __future__ import annotations

import math

import numpy as np


def parameter_keys(config):
    return list(config["parameters"])


def row_to_unit(row, config):
    values = []
    for key in parameter_keys(config):
        low, high = config["parameters"][key]
        values.append((float(row[key]) - float(low)) / (float(high) - float(low)))
    return np.asarray(values, dtype=float)


def mobo_config(config):
    return config.get("objective", {}).get("multi_objective", {})


def objective_keys(config):
    return list(
        mobo_config(config).get(
            "objectives",
            [
                "target_fraction",
                "target_precision",
                "target_centered_compactness",
            ],
        )
    )


def constraint_keys(config):
    return list(
        mobo_config(config).get(
            "constraints",
            ["resolved_constraint", "wall_constraint"],
        )
    )


def reference_point(config):
    values = mobo_config(config).get(
        "reference_point",
        [-1.0e-4] * len(objective_keys(config)),
    )
    if len(values) != len(objective_keys(config)):
        raise ValueError("multi-objective reference point dimension mismatch")
    return np.asarray(values, dtype=float)


def valid_observation_rows(observations, config):
    version = str(config.get("objective", {}).get("version", "unversioned"))
    required = parameter_keys(config) + objective_keys(config) + constraint_keys(config)
    rows = []
    for row in observations:
        if (
            row.get("objective_version") != version
            or row.get("evaluation_status") != "complete"
        ):
            continue
        try:
            values = [float(row[key]) for key in required]
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in values):
            rows.append(row)
    return rows


def row_is_feasible(row, config):
    try:
        return all(float(row[key]) <= 0.0 for key in constraint_keys(config))
    except (KeyError, TypeError, ValueError):
        return False


def nondominated_mask(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 2:
        raise ValueError("objective values must be a 2-D array")
    mask = np.ones(values.shape[0], dtype=bool)
    for index in range(values.shape[0]):
        if not mask[index]:
            continue
        dominates = np.all(values >= values[index], axis=1) & np.any(
            values > values[index],
            axis=1,
        )
        if np.any(dominates):
            mask[index] = False
    return mask


def pareto_rows(observations, config):
    rows = [
        row
        for row in valid_observation_rows(observations, config)
        if row_is_feasible(row, config)
    ]
    if not rows:
        return []
    values = np.asarray(
        [[float(row[key]) for key in objective_keys(config)] for row in rows],
        dtype=float,
    )
    mask = nondominated_mask(values)
    return [row for row, keep in zip(rows, mask) if keep]


def hypervolume_values(values, config):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0
    import torch
    from botorch.utils.multi_objective.box_decompositions.dominated import (
        DominatedPartitioning,
    )

    values = torch.as_tensor(values, dtype=torch.double)
    ref = torch.as_tensor(reference_point(config), dtype=torch.double)
    partitioning = DominatedPartitioning(ref_point=ref, Y=values)
    return float(partitioning.compute_hypervolume().item())


def hypervolume(observations, config):
    rows = pareto_rows(observations, config)
    values = [
        [float(row[key]) for key in objective_keys(config)]
        for row in rows
    ]
    return hypervolume_values(values, config)


def select_training_rows(observations, config):
    rows = valid_observation_rows(observations, config)
    max_points = max(int(config.get("bo", {}).get("max_training_points", 384)), 1)
    if len(rows) <= max_points:
        return rows

    objective_names = objective_keys(config)
    pareto_cases = {row.get("case") for row in pareto_rows(rows, config)}
    selected = set()
    for index, row in enumerate(rows):
        if (
            row.get("case") in pareto_cases
            or float(row.get("target_fraction", 0.0)) > 0.0
        ):
            selected.add(index)

    recent_points = max(int(config.get("bo", {}).get("recent_training_points", 64)), 0)
    for index in range(max(0, len(rows) - recent_points), len(rows)):
        selected.add(index)

    if len(selected) > max_points:
        ranked = sorted(
            selected,
            key=lambda index: tuple(
                float(rows[index][key]) for key in objective_names
            ),
            reverse=True,
        )
        selected = set(ranked[:max_points])

    units = np.vstack([row_to_unit(row, config) for row in rows])
    if selected:
        selected_units = units[sorted(selected)]
        min_distances = np.min(
            np.sqrt(np.sum((units[:, None, :] - selected_units[None, :, :]) ** 2, axis=2)),
            axis=1,
        )
    else:
        first = int(np.argmax([float(row[objective_names[0]]) for row in rows]))
        selected.add(first)
        min_distances = np.sqrt(np.sum((units - units[first]) ** 2, axis=1))

    min_distances[list(selected)] = -1.0
    while len(selected) < max_points:
        index = int(np.argmax(min_distances))
        selected.add(index)
        distance = np.sqrt(np.sum((units - units[index]) ** 2, axis=1))
        min_distances = np.minimum(min_distances, distance)
        min_distances[list(selected)] = -1.0

    return [rows[index] for index in sorted(selected)]


def select_qlognehvi(pool, existing, pending, observations, batch_size, config):
    import torch
    from botorch.acquisition.multi_objective.logei import (
        qLogNoisyExpectedHypervolumeImprovement,
    )
    from botorch.acquisition.multi_objective.objective import (
        IdentityMCMultiOutputObjective,
    )
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.outcome import Standardize
    from botorch.optim import optimize_acqf_discrete
    from botorch.sampling.normal import SobolQMCNormalSampler
    from gpytorch.mlls import ExactMarginalLogLikelihood

    rows = select_training_rows(observations, config)
    gp_min_points = int(config.get("bo", {}).get("gp_min_points", 32))
    if len(rows) < gp_min_points:
        raise RuntimeError("insufficient multi-objective observations")

    objective_names = objective_keys(config)
    constraint_names = constraint_keys(config)
    output_names = objective_names + constraint_names
    train_x = torch.as_tensor(
        np.vstack([row_to_unit(row, config) for row in rows]),
        dtype=torch.double,
    )
    train_y = torch.as_tensor(
        [[float(row[key]) for key in output_names] for row in rows],
        dtype=torch.double,
    )

    threads = max(int(config.get("bo", {}).get("torch_threads", 4)), 1)
    torch.set_num_threads(threads)
    torch.manual_seed(int(config.get("seed", 0)) + len(observations))
    model = SingleTaskGP(
        train_x,
        train_y,
        outcome_transform=Standardize(m=train_y.shape[-1]),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(
        mll,
        optimizer_kwargs={
            "options": {
                "maxiter": int(config.get("bo", {}).get("fit_maxiter", 75)),
            }
        },
    )

    objective = IdentityMCMultiOutputObjective(
        outcomes=list(range(len(objective_names)))
    )
    constraints = [
        (lambda samples, index=index: samples[..., len(objective_names) + index])
        for index in range(len(constraint_names))
    ]
    sampler = SobolQMCNormalSampler(
        sample_shape=torch.Size(
            [int(config.get("bo", {}).get("mc_samples", 64))]
        ),
        seed=int(config.get("seed", 0)) + len(observations) * 31,
    )
    pending_tensor = None
    if pending.size:
        pending_tensor = torch.as_tensor(pending, dtype=torch.double)
    acquisition = qLogNoisyExpectedHypervolumeImprovement(
        model=model,
        ref_point=reference_point(config).tolist(),
        X_baseline=train_x,
        sampler=sampler,
        objective=objective,
        constraints=constraints,
        X_pending=pending_tensor,
        prune_baseline=True,
        cache_root=True,
    )
    choices = torch.as_tensor(pool, dtype=torch.double)
    avoid = None
    if existing.size:
        avoid = torch.as_tensor(existing, dtype=torch.double)
    candidates, _ = optimize_acqf_discrete(
        acq_function=acquisition,
        q=batch_size,
        choices=choices,
        max_batch_size=int(config.get("bo", {}).get("acq_batch_size", 128)),
        unique=True,
        X_avoid=avoid,
    )
    return candidates.detach().cpu().numpy(), "qlognehvi"
