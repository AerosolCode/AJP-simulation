#!/usr/bin/env python3
"""Seed a new BO campaign by rescoring completed historical observations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import bo_loop


def rescore(source_candidates, source_observations, output, config):
    candidates = bo_loop.read_csv_rows(source_candidates)
    observations = bo_loop.read_csv_rows(source_observations)
    candidates_by_case = {row.get("case"): row for row in candidates}

    seeded_candidates = []
    seeded_observations = []
    seen = set()
    objective = config["objective"]
    target_min_particles = max(
        int(objective.get("target_compactness", {}).get("min_particles", 20)),
        1,
    )

    for source_row in observations:
        case = source_row.get("case")
        candidate = candidates_by_case.get(case)
        if (
            not case
            or case in seen
            or candidate is None
            or source_row.get("evaluation_status") != "complete"
        ):
            continue
        try:
            total = max(int(float(source_row["total_particles"])), 1)
            n_target = max(int(float(source_row["n_target"])), 0)
            compactness = float(source_row["deposition_compactness"])
        except (KeyError, TypeError, ValueError):
            continue

        row = dict(source_row)
        row["source_objective_version"] = source_row.get("objective_version", "")
        row["source_score"] = source_row.get("score", "")
        row["objective_version"] = objective["version"]
        target_support = min(1.0, float(n_target) / float(target_min_particles))
        row["target_particle_support"] = target_support
        row["targeted_deposition_compactness"] = target_support * compactness
        row["score"] = bo_loop.objective_score(row, config, total)

        seeded_candidates.append(dict(candidate))
        seeded_observations.append(row)
        seen.add(case)

    if not seeded_observations:
        raise RuntimeError("no complete observations were available to rescore")
    if bo_loop.candidates_path(output).exists() or bo_loop.observations_path(output).exists():
        raise RuntimeError("output campaign already contains BO CSV files: %s" % output)

    bo_loop.init_workdir(config, Path("."), output)
    bo_loop.append_csv_rows(
        bo_loop.candidates_path(output),
        seeded_candidates,
        bo_loop.candidate_fieldnames(config),
    )
    bo_loop.append_csv_rows(
        bo_loop.observations_path(output),
        seeded_observations,
        bo_loop.observation_fieldnames(config),
    )
    return seeded_observations


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="bo_config.json")
    parser.add_argument("--source-candidates", required=True)
    parser.add_argument("--source-observations", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main():
    args = build_parser().parse_args()
    config, _ = bo_loop.load_config(args.config)
    rows = rescore(
        Path(args.source_candidates).expanduser().resolve(),
        Path(args.source_observations).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        config,
    )
    best = max(rows, key=lambda row: float(row["score"]))
    print("rescored observations:", len(rows))
    print(
        "best: %s score=%s target_fraction=%s"
        % (best["case"], best["score"], best["target_fraction"])
    )


if __name__ == "__main__":
    main()
