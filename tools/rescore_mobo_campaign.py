#!/usr/bin/env python3
"""Build or extend a multi-objective campaign from raw particle-fate files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import bo_loop
import mobo


def rescore(
    source_candidates,
    source_observations,
    source_workdir,
    output,
    config,
    append=False,
):
    candidates = bo_loop.read_csv_rows(source_candidates)
    observations = bo_loop.read_csv_rows(source_observations)
    candidates_by_case = {row.get("case"): row for row in candidates}

    output_candidates_path = bo_loop.candidates_path(output)
    output_observations_path = bo_loop.observations_path(output)
    if not append and (
        output_candidates_path.exists() or output_observations_path.exists()
    ):
        raise RuntimeError("output campaign already contains BO CSV files: %s" % output)

    existing_observations = bo_loop.read_csv_rows(output_observations_path)
    seen = {row.get("case") for row in existing_observations}
    rescored_candidates = []
    rescored_observations = []

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
        particle_dir = source_workdir / case / "baseparticle"
        fates_path = particle_dir / "particle_fates_all.csv"
        if not fates_path.is_file():
            continue
        counts, substrate_points = bo_loop.particle_summary(fates_path, config)
        try:
            total_particles = max(int(float(source_row["total_particles"])), 1)
        except (KeyError, TypeError, ValueError):
            total_particles = bo_loop.particle_total_particles(particle_dir, config)

        metrics = bo_loop.compute_metrics(
            counts,
            substrate_points,
            candidate,
            config,
            total_particles=total_particles,
        )
        row = dict(candidate)
        row.update(metrics)
        row["completed_at"] = source_row.get("completed_at", bo_loop.now_iso())
        row["source_objective_version"] = source_row.get("objective_version", "")
        row["source_score"] = source_row.get("score", "")
        rescored_candidates.append(dict(candidate))
        rescored_observations.append(row)
        seen.add(case)

    if not rescored_observations:
        return []
    if not output.exists():
        bo_loop.init_workdir(config, Path("."), output)
    bo_loop.append_csv_rows(
        output_candidates_path,
        rescored_candidates,
        bo_loop.candidate_fieldnames(config),
    )
    bo_loop.append_csv_rows(
        output_observations_path,
        rescored_observations,
        bo_loop.observation_fieldnames(config),
    )
    return rescored_observations


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="bo_config.json")
    parser.add_argument("--source-candidates", required=True)
    parser.add_argument("--source-observations", required=True)
    parser.add_argument("--source-workdir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--append", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    config, _ = bo_loop.load_config(args.config)
    output = Path(args.output).expanduser().resolve()
    rows = rescore(
        Path(args.source_candidates).expanduser().resolve(),
        Path(args.source_observations).expanduser().resolve(),
        Path(args.source_workdir).expanduser().resolve(),
        output,
        config,
        append=args.append,
    )
    observations = bo_loop.read_csv_rows(bo_loop.observations_path(output))
    pareto = mobo.pareto_rows(observations, config)
    print("new rescored observations:", len(rows))
    print("total observations:", len(observations))
    print("pareto observations:", len(pareto))
    print("hypervolume:", mobo.hypervolume(observations, config))
    if pareto:
        best_target = max(pareto, key=lambda row: float(row["target_fraction"]))
        print(
            "max target: %s target_fraction=%s precision=%s centered_compactness=%s"
            % (
                best_target["case"],
                best_target["target_fraction"],
                best_target["target_precision"],
                best_target["target_centered_compactness"],
            )
        )


if __name__ == "__main__":
    main()
