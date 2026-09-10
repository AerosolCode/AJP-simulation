#!/usr/bin/env python3
"""Watch one BO case, then submit particles and collect the observation."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", help="Case name, for example case_0044")
    parser.add_argument("--config", default="bo_config.json")
    parser.add_argument("--poll", type=int, default=300)
    parser.add_argument("--cfd-timeout-hours", type=float, default=24.0)
    parser.add_argument("--particle-timeout-hours", type=float, default=6.0)
    return parser.parse_args()


def wait_for_marker(done: Path, failed: Path | None, poll: int, timeout_hours: float) -> str:
    start = time.monotonic()
    timeout = max(timeout_hours, 0.0) * 3600.0
    while True:
        if done.exists():
            return "done"
        if failed is not None and failed.exists():
            return "failed"
        if timeout and time.monotonic() - start > timeout:
            return "timeout"
        time.sleep(max(poll, 1))


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    sys.path.insert(0, str(repo_root))

    import bo_loop  # noqa: PLC0415

    config, config_dir = bo_loop.load_config(args.config)
    workdir, _base_template, particle_template = bo_loop.get_paths(config, config_dir)
    case_dir = workdir / args.case
    particle_dir = case_dir / "baseparticle"

    print(f"[watch] start case={args.case}", flush=True)
    print(f"[watch] workdir={workdir}", flush=True)

    status = wait_for_marker(
        case_dir / "CFD_DONE",
        case_dir / "CFD_FAILED",
        args.poll,
        args.cfd_timeout_hours,
    )
    print(f"[watch] cfd_status={status}", flush=True)
    if status != "done":
        return 1

    submitted = bo_loop.submit_particles(
        config,
        workdir,
        particle_template,
        cases=[args.case],
        dry_run=False,
    )
    print(f"[watch] particle_submit_count={submitted}", flush=True)

    status = wait_for_marker(
        particle_dir / "PARTICLE_DONE",
        None,
        args.poll,
        args.particle_timeout_hours,
    )
    print(f"[watch] particle_status={status}", flush=True)
    if status != "done":
        return 2

    bo_loop.collect_completed(config, workdir, cases=[args.case])
    print("[watch] collect complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
