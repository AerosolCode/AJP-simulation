#!/usr/bin/env python3
"""Coordinate independent Slurm workers from a single XEON6 BO master."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import bo_loop


ACTIVE_STAGES = {"cfd_submitted", "particle_submitted"}
FATES_HEADER = (
    "patch,time,currentProc,coord0,coord1,coord2,coord3,x,y,z,celli,tetFacei,"
    "tetPti,facei,stepFraction,origProc,origId,active,typeId,nParticle,d,dTarget,"
    "Ux,Uy,Uz,rho,age,tTurb,UTurbx,UTurby,UTurbz,UCorrectx,UCorrecty,UCorrectz,"
    "fx,fy,fz,angularMomentumx,angularMomentumy,angularMomentumz,torquex,torquey,"
    "torquez\n"
)
PARTICLE_RESULT_FILES = (
    "PARTICLE_DONE",
    "PARTICLE_FAILED",
    "PARTICLE_STATUS.txt",
    "particle_fates_all.csv",
    "particle_run_config.txt",
    "output_particle.txt",
    "error_particle.txt",
    "log.aerosolDynamicsFoam",
    "log.aerosolDynamicsFoam.chunk",
    "log.checkMesh.particle",
)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def load_site_env(path=None):
    site_path = Path(path or os.environ.get("AJP_SITE_ENV", SOURCE_ROOT / "site.env"))
    if not site_path.is_absolute():
        site_path = SOURCE_ROOT / site_path
    if site_path.is_file():
        for raw_line in site_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                raise ValueError("invalid site.env line: %s" % raw_line)
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("invalid site.env key: %s" % key)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, os.path.expandvars(os.path.expanduser(value)))
    default_ssh_user = os.environ.get("AJP_SSH_USER", os.environ.get("USER", ""))
    default_worker_root = os.environ.get(
        "AJP_WORKER_ROOT",
        str(Path.home() / "AJP-worker"),
    )
    for host_name in ("XEON1", "XEON4", "XEON5"):
        os.environ.setdefault("AJP_SSH_USER_%s" % host_name, default_ssh_user)
    for host_name in ("XEON6", "XEON1", "XEON4", "XEON5"):
        os.environ.setdefault("AJP_WORKER_ROOT_%s" % host_name, default_worker_root)
    return site_path


def expand_environment(value):
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value
    expanded = os.path.expandvars(os.path.expanduser(value))
    if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", expanded):
        raise ValueError("unresolved environment variable in config: %s" % value)
    return expanded


def resolve_path(value, base):
    path = Path(os.path.expandvars(str(value))).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_dispatch_config(path):
    load_site_env()
    config_path = Path(path).expanduser().resolve()
    with config_path.open() as stream:
        config = expand_environment(json.load(stream))
    base = config_path.parent
    config["source_root"] = str(resolve_path(config.get("source_root", "."), base))
    config["bo_config"] = str(resolve_path(config.get("bo_config", "bo_config.json"), base))
    config["workdir"] = str(resolve_path(config["workdir"], base))
    hosts = config.get("hosts", [])
    if len(hosts) != 4:
        raise ValueError("exactly four worker hosts must be configured")
    names = [host["name"] for host in hosts]
    if len(set(names)) != len(names):
        raise ValueError("worker host names must be unique")
    if sum(host.get("mode") == "local" for host in hosts) != 1:
        raise ValueError("exactly one local master/worker must be configured")
    for host in hosts:
        host["slots"] = max(int(host.get("slots", 1)), 1)
        if host.get("mode") not in {"local", "ssh"}:
            raise ValueError("unsupported worker mode for %s" % host["name"])
        worker_root = Path(str(host.get("worker_root", ""))).expanduser()
        if not worker_root.is_absolute():
            raise ValueError("worker_root must be absolute for %s" % host["name"])
        host["worker_root"] = str(worker_root)
        host["campaign_root"] = str(
            worker_root / "campaigns" / config["campaign"]
        )
        if host["mode"] == "ssh":
            ssh_user = str(host.get("ssh_user", "")).strip()
            if not ssh_user:
                raise ValueError("ssh_user is required for %s" % host["name"])
            address = str(host.get("address", host["name"]))
            host["ssh_target"] = "%s@%s" % (ssh_user, address) if ssh_user else address
    return config


def load_bo_context(dispatch_config):
    config, _ = bo_loop.load_config(dispatch_config["bo_config"])
    config["workdir"] = dispatch_config["workdir"]
    config["template_root"] = dispatch_config["source_root"]
    config_dir = Path(dispatch_config["bo_config"]).resolve().parent
    workdir, base_template, particle_template = bo_loop.get_paths(config, config_dir)
    return config, workdir, base_template, particle_template


def state_path(workdir):
    return Path(workdir) / "dispatcher_state.json"


def load_state(workdir, dispatch_config, objective_version):
    path = state_path(workdir)
    if path.exists():
        with path.open() as stream:
            state = json.load(stream)
        if state.get("campaign") != dispatch_config["campaign"]:
            raise RuntimeError("dispatcher state belongs to a different campaign")
        if state.get("objective_version") != objective_version:
            raise RuntimeError("dispatcher state belongs to a different objective version")
        return state
    return {
        "campaign": dispatch_config["campaign"],
        "objective_version": objective_version,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "cases": {},
    }


def save_state(workdir, state):
    path = state_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w") as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def run_command(command, cwd=None, timeout=90):
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def ssh_command(host, arguments, timeout=90):
    return run_command(["ssh", host, *arguments], timeout=timeout)


def ssh_target(host):
    return host.get("ssh_target", host["name"])


def remote_case_path(dispatch_config, host, case):
    return str(Path(host["campaign_root"]) / case)


def case_execution_path(dispatch_config, host, workdir, case):
    if host["mode"] == "local":
        return str(Path(workdir) / case)
    return remote_case_path(dispatch_config, host, case)


def ensure_particle_template(case_dir, particle_template, bo_config):
    return bo_loop.ensure_particle_case(
        Path(case_dir),
        Path(particle_template),
        bo_loop.particle_script_name(bo_config),
    )


def write_assignment(case_dir, dispatch_config, host, objective_version):
    assignment = {
        "campaign": dispatch_config["campaign"],
        "case": Path(case_dir).name,
        "host": host["name"],
        "objective_version": objective_version,
        "assigned_at": now_iso(),
    }
    with (Path(case_dir) / "worker_assignment.json").open("w") as stream:
        json.dump(assignment, stream, indent=2)
        stream.write("\n")


def stage_case(dispatch_config, host, case_dir):
    if host["mode"] == "local":
        return
    remote_case = remote_case_path(dispatch_config, host, Path(case_dir).name)
    mkdir_result = ssh_command(ssh_target(host), ["mkdir", "-p", str(Path(remote_case).parent)])
    if mkdir_result.returncode != 0:
        raise RuntimeError(mkdir_result.stderr.strip() or "remote mkdir failed")
    sync_result = run_command(
        [
            "rsync",
            "-a",
            "--delete",
            str(Path(case_dir)) + "/",
            "%s:%s/" % (ssh_target(host), remote_case),
        ],
        timeout=300,
    )
    if sync_result.returncode != 0:
        raise RuntimeError(sync_result.stderr.strip() or "case rsync failed")


def sbatch_export(environment):
    if not environment:
        return "ALL"
    items = ["ALL"]
    for key in sorted(environment):
        value = str(environment[key])
        if "," in value:
            raise ValueError("Slurm export values may not contain commas")
        items.append("%s=%s" % (key, value))
    return ",".join(items)


def submit_job(dispatch_config, host, workdir, case, stage):
    if stage == "cfd":
        relative_dir = ""
        script = "run.sh"
        environment = dict(dispatch_config.get("cfd_env", {}))
        job_tag = "C"
    elif stage == "particle":
        relative_dir = "baseparticle"
        script = "loopaerosolDynamics.sh"
        environment = dict(dispatch_config.get("particle_env", {}))
        job_tag = "P"
    else:
        raise ValueError("unsupported stage: %s" % stage)

    environment["AJP_WORKER_ROOT"] = host["worker_root"]
    environment["AJP_WORKER_ENV"] = str(Path(host["worker_root"]) / "worker-env.sh")

    if stage == "particle":
        clear_particle_completion_markers(
            dispatch_config,
            host,
            workdir,
            case,
        )

    execution_root = Path(case_execution_path(dispatch_config, host, workdir, case))
    execution_dir = execution_root / relative_dir
    job_name = "%s_%s_%s" % (
        dispatch_config["campaign"][:6],
        job_tag,
        case.replace("case_", ""),
    )
    sbatch_args = [
        "sbatch",
        "--parsable",
        "--job-name",
        job_name,
        "--export",
        sbatch_export(environment),
        script,
    ]
    if host["mode"] == "local":
        result = run_command(sbatch_args, cwd=execution_dir)
    else:
        remote_shell = "cd %s && %s" % (
            shlex.quote(str(execution_dir)),
            " ".join(shlex.quote(item) for item in sbatch_args),
        )
        result = ssh_command(ssh_target(host), [remote_shell])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "sbatch failed")
    job_id = result.stdout.strip().splitlines()[-1].split(";", 1)[0]
    if not job_id.isdigit():
        raise RuntimeError("could not parse Slurm job id: %s" % result.stdout.strip())
    return job_id


def clear_particle_completion_markers(
    dispatch_config,
    host,
    workdir,
    case,
):
    local_particle_dir = Path(workdir) / case / "baseparticle"
    for name in ("PARTICLE_DONE", "PARTICLE_FAILED"):
        (local_particle_dir / name).unlink(missing_ok=True)

    if host["mode"] == "local":
        return
    remote_particle_dir = (
        Path(case_execution_path(dispatch_config, host, workdir, case))
        / "baseparticle"
    )
    marker_paths = [
        str(remote_particle_dir / "PARTICLE_DONE"),
        str(remote_particle_dir / "PARTICLE_FAILED"),
    ]
    result = ssh_command(ssh_target(host), ["rm", "-f", *marker_paths])
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or "failed to clear remote particle markers"
        )


def marker_exists(dispatch_config, host, workdir, case, relative_path):
    execution_root = Path(case_execution_path(dispatch_config, host, workdir, case))
    marker = execution_root / relative_path
    if host["mode"] == "local":
        return marker.exists()
    result = ssh_command(ssh_target(host), ["test", "-e", str(marker)])
    return result.returncode == 0


def job_active(host, job_id):
    command = ["squeue", "-h", "-j", str(job_id), "-o", "%T"]
    if host["mode"] == "local":
        result = run_command(command)
    else:
        result = ssh_command(ssh_target(host), command)
    return result.returncode == 0 and bool(result.stdout.strip())


def retrieve_case(dispatch_config, host, workdir, case):
    if host["mode"] == "local":
        return
    remote_case = remote_case_path(dispatch_config, host, case)
    local_case = Path(workdir) / case
    local_case.mkdir(parents=True, exist_ok=True)
    include = [
        "/CFD_DONE",
        "/CFD_FAILED",
        "/output.txt",
        "/error.txt",
        "/log.simpleFoam",
        "/log.fieldMinMax.U",
        "/baseparticle/",
        "/baseparticle/PARTICLE_DONE",
        "/baseparticle/PARTICLE_FAILED",
        "/baseparticle/PARTICLE_STATUS.txt",
        "/baseparticle/particle_fates_all.csv",
        "/baseparticle/particle_run_config.txt",
        "/baseparticle/output_particle.txt",
        "/baseparticle/error_particle.txt",
        "/baseparticle/log.aerosolDynamicsFoam",
    ]
    command = ["rsync", "-a", "--prune-empty-dirs"]
    for pattern in include:
        command.extend(["--include", pattern])
    command.extend(
        [
            "--exclude",
            "*",
            "%s:%s/" % (ssh_target(host), remote_case),
            str(local_case) + "/",
        ]
    )
    result = run_command(command, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "result rsync failed")


def ensure_fates_file(workdir, case):
    particle_dir = Path(workdir) / case / "baseparticle"
    fates = particle_dir / "particle_fates_all.csv"
    if not fates.exists():
        particle_dir.mkdir(parents=True, exist_ok=True)
        fates.write_text(FATES_HEADER)


def host_by_name(dispatch_config, name):
    for host in dispatch_config["hosts"]:
        if host["name"] == name:
            return host
    raise KeyError("unknown worker host: %s" % name)


def active_counts(dispatch_config, state):
    counts = {host["name"]: 0 for host in dispatch_config["hosts"]}
    for entry in state["cases"].values():
        if entry.get("stage") in ACTIVE_STAGES and entry.get("host") in counts:
            counts[entry["host"]] += 1
    return counts


def choose_host(dispatch_config, state):
    counts = active_counts(dispatch_config, state)
    assigned = {host["name"]: 0 for host in dispatch_config["hosts"]}
    for entry in state["cases"].values():
        if entry.get("host") in assigned:
            assigned[entry["host"]] += 1
    available = [
        host
        for host in dispatch_config["hosts"]
        if counts[host["name"]] < host["slots"]
    ]
    if not available:
        return None
    return min(
        available,
        key=lambda host: (
            counts[host["name"]] / float(host["slots"]),
            assigned[host["name"]],
            [item["name"] for item in dispatch_config["hosts"]].index(host["name"]),
        ),
    )


def set_failed_marker(workdir, case, stage):
    case_dir = Path(workdir) / case
    if stage == "cfd":
        (case_dir / "CFD_FAILED").touch()
    else:
        particle_dir = case_dir / "baseparticle"
        particle_dir.mkdir(parents=True, exist_ok=True)
        (particle_dir / "PARTICLE_FAILED").touch()


def poll_case(dispatch_config, workdir, case, entry):
    stage = entry["stage"]
    host = host_by_name(dispatch_config, entry["host"])

    if stage == "cfd_submitted":
        if marker_exists(dispatch_config, host, workdir, case, "CFD_DONE"):
            try:
                job_id = submit_job(dispatch_config, host, workdir, case, "particle")
            except Exception as exc:
                entry.update(
                    error="particle submit: %s" % exc,
                    updated_at=now_iso(),
                )
            else:
                entry.update(
                    stage="particle_submitted",
                    particle_job_id=job_id,
                    missing_polls=0,
                    error="",
                    updated_at=now_iso(),
                )
            return True
        if marker_exists(dispatch_config, host, workdir, case, "CFD_FAILED"):
            retrieve_case(dispatch_config, host, workdir, case)
            set_failed_marker(workdir, case, "cfd")
            entry.update(stage="failed", error="CFD_FAILED", updated_at=now_iso())
            return True
        active = job_active(host, entry["cfd_job_id"])
    else:
        if marker_exists(
            dispatch_config,
            host,
            workdir,
            case,
            "baseparticle/PARTICLE_DONE",
        ):
            retrieve_case(dispatch_config, host, workdir, case)
            ensure_fates_file(workdir, case)
            entry.update(
                stage="complete",
                error="",
                updated_at=now_iso(),
                missing_polls=0,
            )
            return True
        active = job_active(host, entry["particle_job_id"])

    if active:
        if entry.get("missing_polls", 0):
            entry["missing_polls"] = 0
            entry["updated_at"] = now_iso()
            return True
        return False

    missing_polls = int(entry.get("missing_polls", 0)) + 1
    entry["missing_polls"] = missing_polls
    entry["updated_at"] = now_iso()
    if missing_polls < 2:
        return True

    retrieve_case(dispatch_config, host, workdir, case)
    failed_stage = "cfd" if stage == "cfd_submitted" else "particle"
    set_failed_marker(workdir, case, failed_stage)
    entry.update(
        stage="failed",
        error="%s job disappeared without completion marker" % failed_stage,
        updated_at=now_iso(),
    )
    return True


def poll_cases(dispatch_config, bo_config, workdir, state):
    changed = False
    for case, entry in list(state["cases"].items()):
        if entry.get("stage") not in ACTIVE_STAGES:
            continue
        try:
            changed = poll_case(dispatch_config, workdir, case, entry) or changed
        except Exception as exc:
            entry["poll_error"] = str(exc)
            entry["updated_at"] = now_iso()
            print("poll error %s: %s" % (case, exc), file=sys.stderr, flush=True)
            changed = True
    return changed


def dispatch_candidates(
    dispatch_config,
    bo_config,
    workdir,
    particle_template,
    state,
):
    candidates = bo_loop.read_csv_rows(bo_loop.candidates_path(workdir))
    observations = bo_loop.read_csv_rows(bo_loop.observations_path(workdir))
    observed = {row.get("case") for row in observations}
    objective_version = bo_config["objective"]["version"]
    submitted = 0

    for candidate in candidates:
        case = candidate.get("case")
        if not case or case in observed:
            continue
        existing = state["cases"].get(case)
        if existing and existing.get("stage") not in {"dispatch_error"}:
            continue
        host = choose_host(dispatch_config, state)
        if host is None:
            break
        case_dir = Path(workdir) / case
        try:
            ensure_particle_template(case_dir, particle_template, bo_config)
            write_assignment(case_dir, dispatch_config, host, objective_version)
            stage_case(dispatch_config, host, case_dir)
            job_id = submit_job(dispatch_config, host, workdir, case, "cfd")
        except Exception as exc:
            state["cases"][case] = {
                "host": host["name"],
                "stage": "dispatch_error",
                "error": str(exc),
                "attempts": int((existing or {}).get("attempts", 0)) + 1,
                "updated_at": now_iso(),
            }
            continue
        state["cases"][case] = {
            "host": host["name"],
            "remote_case": case_execution_path(dispatch_config, host, workdir, case),
            "stage": "cfd_submitted",
            "cfd_job_id": job_id,
            "missing_polls": 0,
            "attempts": int((existing or {}).get("attempts", 0)) + 1,
            "submitted_at": now_iso(),
            "updated_at": now_iso(),
        }
        submitted += 1
    return submitted


def stop_progress(dispatch_config, observations):
    stop_config = dispatch_config.get("loop", {}).get("stop", {})
    baseline_count = max(int(stop_config.get("baseline_observations", 0)), 0)
    baseline_count = min(baseline_count, len(observations))
    new_rows = observations[baseline_count:]
    min_improvement = max(float(stop_config.get("min_improvement", 0.0)), 0.0)

    metric = str(stop_config.get("metric", "score"))
    if metric == "hypervolume":
        best, last_improvement = hypervolume_improvement_progress(
            dispatch_config,
            observations[:baseline_count],
            new_rows,
            min_improvement,
        )
    else:
        baseline_scores = []
        for row in observations[:baseline_count]:
            try:
                baseline_scores.append(float(row["score"]))
            except (KeyError, TypeError, ValueError):
                pass
        best = max(baseline_scores) if baseline_scores else float("-inf")
        last_improvement = 0
        for index, row in enumerate(new_rows, start=1):
            try:
                score = float(row["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if score > best + min_improvement:
                best = score
                last_improvement = index

    new_count = len(new_rows)
    no_improvement_count = new_count - last_improvement
    max_new = max(int(stop_config.get("max_new_observations", 0)), 0)
    min_new = max(int(stop_config.get("min_new_observations", 0)), 0)
    patience = max(int(stop_config.get("patience", 0)), 0)

    reason = ""
    if max_new and new_count >= max_new:
        reason = "max_new_observations"
    elif (
        patience
        and new_count >= min_new
        and no_improvement_count >= patience
    ):
        reason = "stagnation"

    remaining_budget = None
    if max_new:
        remaining_budget = max(max_new - new_count, 0)
    return {
        "baseline_observations": baseline_count,
        "new_observations": new_count,
        "metric": metric,
        "best_score": None if best == float("-inf") else best,
        "last_improvement_new_observation": last_improvement,
        "no_improvement_count": no_improvement_count,
        "remaining_budget": remaining_budget,
        "reason": reason,
    }


def hypervolume_improvement_progress(
    dispatch_config,
    baseline_rows,
    new_rows,
    min_improvement,
):
    bo_config, _ = bo_loop.load_config(dispatch_config["bo_config"])
    import mobo

    objective_names = mobo.objective_keys(bo_config)
    valid_baseline = [
        row
        for row in mobo.valid_observation_rows(baseline_rows, bo_config)
        if mobo.row_is_feasible(row, bo_config)
    ]
    front = np.asarray(
        [
            [float(row[key]) for key in objective_names]
            for row in valid_baseline
        ],
        dtype=float,
    )
    if front.size:
        front = front[mobo.nondominated_mask(front)]
    else:
        front = np.empty((0, len(objective_names)), dtype=float)
    best = mobo.hypervolume_values(front, bo_config)
    last_improvement = 0

    version = bo_config["objective"]["version"]
    for index, row in enumerate(new_rows, start=1):
        if (
            row.get("objective_version") != version
            or row.get("evaluation_status") != "complete"
            or not mobo.row_is_feasible(row, bo_config)
        ):
            continue
        try:
            values = np.asarray(
                [float(row[key]) for key in objective_names],
                dtype=float,
            )
        except (KeyError, TypeError, ValueError):
            continue
        front = np.vstack([front, values[None, :]])
        front = front[mobo.nondominated_mask(front)]
        value = mobo.hypervolume_values(front, bo_config)
        if value > best + min_improvement:
            best = value
            last_improvement = index
    return best, last_improvement


def run_once(dispatch_config, bo_config, workdir, base_template, particle_template, state):
    poll_cases(dispatch_config, bo_config, workdir, state)
    bo_loop.collect_completed(bo_config, workdir)
    loop_config = dispatch_config.get("loop", {})
    observations = bo_loop.read_csv_rows(bo_loop.observations_path(workdir))
    progress = stop_progress(dispatch_config, observations)
    max_pending = int(loop_config.get("max_pending", 32))
    if progress["remaining_budget"] is not None:
        max_pending = min(max_pending, progress["remaining_budget"])
    if progress["reason"]:
        print(
            "stop: %s; draining prepared and active cases"
            % progress["reason"],
            flush=True,
        )
    else:
        bo_loop.step(
            bo_config,
            workdir,
            base_template,
            particle_template,
            int(loop_config.get("batch_size", 8)),
            max_pending,
            submit=False,
            dry_run=False,
        )
    submitted = dispatch_candidates(
        dispatch_config,
        bo_config,
        workdir,
        particle_template,
        state,
    )
    pending = bo_loop.pending_count(bo_config, workdir)
    progress["pending"] = pending
    progress["updated_at"] = now_iso()
    state["stop"] = progress
    save_state(workdir, state)
    print("%s dispatch submitted=%d" % (now_iso(), submitted), flush=True)
    return bool(progress["reason"] and pending == 0)


def collect_only(dispatch_config, bo_config, workdir, state):
    poll_cases(dispatch_config, bo_config, workdir, state)
    collected = bo_loop.collect_completed(bo_config, workdir)
    save_state(workdir, state)
    print("collect-only: collected=%d" % len(collected), flush=True)


def initialize(dispatch_config, initial_batch, submit_jobs=True):
    bo_config, workdir, base_template, particle_template = load_bo_context(dispatch_config)
    if bo_loop.candidates_path(workdir).exists() or state_path(workdir).exists():
        raise RuntimeError("campaign already initialized: %s" % workdir)
    bo_loop.init_workdir(bo_config, Path(dispatch_config["bo_config"]).parent, workdir)
    bo_loop.suggest(
        bo_config,
        workdir,
        base_template,
        initial_batch,
        submit=False,
        dry_run=False,
    )
    state = load_state(workdir, dispatch_config, bo_config["objective"]["version"])
    submitted = 0
    if submit_jobs:
        submitted = dispatch_candidates(
            dispatch_config,
            bo_config,
            workdir,
            particle_template,
            state,
        )
    save_state(workdir, state)
    action = "submitted" if submit_jobs else "prepared"
    print("initialized %s and %s %d cases" % (workdir, action, initial_batch if not submit_jobs else submitted))


def print_status(dispatch_config):
    bo_config, workdir, _, _ = load_bo_context(dispatch_config)
    state = load_state(workdir, dispatch_config, bo_config["objective"]["version"])
    candidates = bo_loop.read_csv_rows(bo_loop.candidates_path(workdir))
    observations = bo_loop.read_csv_rows(bo_loop.observations_path(workdir))
    observed = {row.get("case") for row in observations}
    unresolved = [
        row.get("case")
        for row in candidates
        if row.get("case") and row.get("case") not in observed
    ]
    prepared_unassigned = sum(
        1
        for case in unresolved
        if case not in state["cases"]
        or state["cases"][case].get("stage") == "dispatch_error"
    )
    counts = active_counts(dispatch_config, state)
    stages = {}
    for entry in state["cases"].values():
        stage = entry.get("stage", "unknown")
        stages[stage] = stages.get(stage, 0) + 1
    print("campaign:", dispatch_config["campaign"])
    print("objective_version:", bo_config["objective"]["version"])
    print("workdir:", workdir)
    print("candidates:", len(candidates))
    print("observations:", len(observations))
    print("pending:", len(unresolved))
    print("prepared_unassigned:", prepared_unassigned)
    for host in dispatch_config["hosts"]:
        name = host["name"]
        print("host %s: active=%d slots=%d" % (name, counts[name], host["slots"]))
    for stage in sorted(stages):
        print("stage %s: %d" % (stage, stages[stage]))
    progress = stop_progress(dispatch_config, observations)
    print(
        "stop: new=%d no_improvement=%d remaining=%s reason=%s"
        % (
            progress["new_observations"],
            progress["no_improvement_count"],
            progress["remaining_budget"],
            progress["reason"] or "running",
        )
    )
    if observations and bo_config.get("objective", {}).get("mode") == "multi_objective":
        try:
            import mobo

            pareto = mobo.pareto_rows(observations, bo_config)
            print("pareto:", len(pareto))
            print("hypervolume:", mobo.hypervolume(observations, bo_config))
            if pareto:
                best_target = max(
                    pareto,
                    key=lambda row: float(row["target_fraction"]),
                )
                print(
                    "max_target: %s target_fraction=%s"
                    % (best_target.get("case"), best_target.get("target_fraction"))
                )
        except Exception as exc:
            print("multi-objective status unavailable:", exc)
    elif observations:
        best = max(observations, key=lambda row: float(row["score"]))
        print("best: %s score=%s" % (best.get("case"), best.get("score")))


def archive_particle_result(workdir, case, entry, reason, timestamp):
    source = Path(workdir) / case / "baseparticle"
    destination = (
        Path(workdir)
        / "invalidated_particle_runs"
        / timestamp
        / case
    )
    destination.mkdir(parents=True, exist_ok=True)
    for name in PARTICLE_RESULT_FILES:
        path = source / name
        if path.is_file():
            shutil.copy2(path, destination / name)
    metadata = {
        "case": case,
        "host": entry["host"],
        "invalidated_at": now_iso(),
        "reason": reason,
        "previous_dispatch_state": dict(entry),
    }
    with (destination / "invalidation.json").open("w") as stream:
        json.dump(metadata, stream, indent=2, sort_keys=True)
        stream.write("\n")


def rewrite_csv(path, rows, fieldnames):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def reset_particle_cases(dispatch_config, cases, reason):
    bo_config, workdir, _, _ = load_bo_context(dispatch_config)
    state = load_state(
        workdir,
        dispatch_config,
        bo_config["objective"]["version"],
    )
    requested = list(dict.fromkeys(cases))
    validations = []
    for case in requested:
        entry = state["cases"].get(case)
        if entry is None:
            raise RuntimeError("case is not in dispatcher state: %s" % case)
        host = host_by_name(dispatch_config, entry["host"])
        particle_job_id = entry.get("particle_job_id")
        if particle_job_id and job_active(host, particle_job_id):
            raise RuntimeError(
                "%s particle job %s is still active"
                % (case, particle_job_id)
            )
        if not marker_exists(
            dispatch_config,
            host,
            workdir,
            case,
            "CFD_DONE",
        ):
            raise RuntimeError("%s has no reusable CFD_DONE marker" % case)
        validations.append((case, entry, host))

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for case, entry, host in validations:
        retrieve_case(dispatch_config, host, workdir, case)
        archive_particle_result(workdir, case, entry, reason, timestamp)
        clear_particle_completion_markers(
            dispatch_config,
            host,
            workdir,
            case,
        )
        entry.update(
            stage="cfd_submitted",
            missing_polls=0,
            error="",
            reset_at=now_iso(),
            reset_reason=reason,
            updated_at=now_iso(),
        )
        entry.pop("particle_job_id", None)
        entry.pop("poll_error", None)

    observations_file = bo_loop.observations_path(workdir)
    if observations_file.exists():
        with observations_file.open(newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = list(reader.fieldnames or [])
            observations = list(reader)
    else:
        fieldnames = bo_loop.observation_fieldnames(bo_config)
        observations = []
    requested_set = set(requested)
    invalidated = [
        row for row in observations if row.get("case") in requested_set
    ]
    retained = [
        row for row in observations if row.get("case") not in requested_set
    ]
    if invalidated:
        invalidated_at = now_iso()
        for row in invalidated:
            row["invalidated_at"] = invalidated_at
            row["invalidation_reason"] = reason
        bo_loop.append_csv_rows(
            Path(workdir) / "invalidated_observations.csv",
            invalidated,
            fieldnames + ["invalidated_at", "invalidation_reason"],
        )
    rewrite_csv(observations_file, retained, fieldnames)
    save_state(workdir, state)
    print(
        "reset particle stage for %d cases; invalidated %d observations"
        % (len(requested), len(invalidated))
    )


def acquire_lock(workdir):
    lock_path = Path(workdir) / "dispatcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("w")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        raise RuntimeError("another dispatcher owns %s" % lock_path)
    stream.write("%d\n" % os.getpid())
    stream.flush()
    return stream


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="bo_multihost_config.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--initial-batch", type=int, default=None)
    init_parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="create candidates and case templates without submitting Slurm jobs",
    )

    subparsers.add_parser("step")
    subparsers.add_parser("collect")
    drain_parser = subparsers.add_parser("drain")
    drain_parser.add_argument("--sleep", type=int, default=300)

    loop_parser = subparsers.add_parser("loop")
    loop_parser.add_argument("--sleep", type=int, default=None)
    loop_parser.add_argument("--iterations", type=int, default=0)

    reset_parser = subparsers.add_parser("reset-particles")
    reset_parser.add_argument("cases", nargs="+")
    reset_parser.add_argument("--reason", required=True)

    subparsers.add_parser("status")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    dispatch_config = load_dispatch_config(args.config)
    if args.command == "init":
        initial_batch = args.initial_batch
        if initial_batch is None:
            initial_batch = int(dispatch_config.get("loop", {}).get("initial_batch", 32))
        initialize(dispatch_config, initial_batch, submit_jobs=not args.prepare_only)
        return
    if args.command == "status":
        print_status(dispatch_config)
        return

    bo_config, workdir, base_template, particle_template = load_bo_context(dispatch_config)
    lock = acquire_lock(workdir)
    try:
        state = load_state(workdir, dispatch_config, bo_config["objective"]["version"])
        if args.command == "step":
            should_exit = run_once(
                dispatch_config,
                bo_config,
                workdir,
                base_template,
                particle_template,
                state,
            )
            return
        if args.command == "collect":
            collect_only(
                dispatch_config,
                bo_config,
                workdir,
                state,
            )
            return
        if args.command == "drain":
            while True:
                collect_only(
                    dispatch_config,
                    bo_config,
                    workdir,
                    state,
                )
                active = sum(active_counts(dispatch_config, state).values())
                print("drain: active=%d" % active, flush=True)
                if active == 0:
                    return
                time.sleep(max(int(args.sleep), 1))
        if args.command == "reset-particles":
            reset_particle_cases(
                dispatch_config,
                args.cases,
                args.reason,
            )
            return

        sleep_seconds = args.sleep
        if sleep_seconds is None:
            sleep_seconds = int(dispatch_config.get("loop", {}).get("sleep_seconds", 300))
        iteration = 0
        while True:
            iteration += 1
            print("dispatcher iteration %d %s" % (iteration, now_iso()), flush=True)
            should_exit = run_once(
                dispatch_config,
                bo_config,
                workdir,
                base_template,
                particle_template,
                state,
            )
            if should_exit:
                print("dispatcher stop condition drained; exiting", flush=True)
                break
            if args.iterations and iteration >= args.iterations:
                break
            time.sleep(sleep_seconds)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
