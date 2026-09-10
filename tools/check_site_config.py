#!/usr/bin/env python3
"""Resolve and display the per-user AJP cluster configuration."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import bo_multihost


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="bo_multihost_config.json")
    parser.add_argument(
        "--local-tools",
        action="store_true",
        help="also check commands and paths on the current machine",
    )
    args = parser.parse_args(argv)

    site_path = bo_multihost.load_site_env()
    config = bo_multihost.load_dispatch_config(args.config)
    master_python = os.environ.get("AJP_MASTER_PYTHON", "python3")

    errors = []
    if not site_path.is_file():
        errors.append("site.env is missing; copy site.env.example first")

    print("site_env:", site_path)
    print("master_python:", master_python)
    print("campaign:", config["campaign"])
    print("local_workdir:", config["workdir"])
    for host in config["hosts"]:
        worker_root = Path(host["worker_root"])
        target = "local" if host["mode"] == "local" else host["ssh_target"]
        if not worker_root.is_absolute():
            errors.append("worker root is not absolute for %s" % host["name"])
        if host["mode"] == "ssh" and host["ssh_user"].startswith("student_"):
            errors.append("SSH user is still a placeholder for %s" % host["name"])
        print("host %s: mode=%s target=%s slots=%s worker_root=%s campaign_root=%s" % (
            host["name"],
            host["mode"],
            target,
            host["slots"],
            host["worker_root"],
            host["campaign_root"],
        ))

    if args.local_tools:
        for command in (master_python, "ssh", "rsync", "sbatch"):
            found = Path(command).is_file() if "/" in command else shutil.which(command)
            print("local_tool %s: %s" % (command, "OK" if found else "MISSING"))
            if not found:
                errors.append("local tool is missing: %s" % command)

    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
