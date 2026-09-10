#!/usr/bin/env python3
"""Classify CFD failures and compare their design conditions with valid runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


FLOAT_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
TIME_RE = re.compile(r"^Time = (" + FLOAT_PATTERN + r")$")
CONTINUITY_RE = re.compile(
    r"sum local = (" + FLOAT_PATTERN + r"), global = (" + FLOAT_PATTERN
    + r"), cumulative = (" + FLOAT_PATTERN + r")"
)
MESH_RE = re.compile(r"mesh size: nodes=(\d+) elements=(\d+)")
MAX_U_RE = re.compile(r"max\(mag\(U\)\)=(" + FLOAT_PATTERN + r")")


def read_csv(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def read_text(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def finite_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def percentile(values, fraction):
    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    location = (len(clean) - 1) * fraction
    lower = int(math.floor(location))
    upper = int(math.ceil(location))
    weight = location - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def parse_output(case_dir):
    text = read_text(case_dir / "output.txt")
    mesh_match = MESH_RE.search(text)
    max_u_matches = MAX_U_RE.findall(text)
    result = {
        "mesh_nodes": int(mesh_match.group(1)) if mesh_match else None,
        "mesh_elements": int(mesh_match.group(2)) if mesh_match else None,
        "max_u_mps": float(max_u_matches[-1]) if max_u_matches else None,
        "potential_failed": "[run] potentialFoam failed" in text,
        "simple_failed": "[run] simpleFoam failed" in text,
        "unclean_end": "[run] simpleFoam log did not end cleanly" in text,
        "velocity_rejected": "[run] invalid CFD U field" in text,
        "velocity_check_failed": "[run] failed to inspect U field" in text
        or "[run] failed to parse max(mag(U))" in text,
        "mesh_rejected": "[run] mesh exceeds configured size limit" in text,
        "run_finished": text.rstrip().endswith("finished"),
    }
    return result


def parse_simple_log(case_dir):
    path = case_dir / "log.simpleFoam"
    result = {
        "last_iteration": None,
        "first_continuity_gt_1e3": None,
        "first_continuity_gt_1e12": None,
        "max_log10_continuity": None,
        "last_local_continuity": None,
        "last_global_continuity": None,
        "last_cumulative_continuity": None,
        "simple_end": False,
        "simple_sigfpe": False,
        "turbulence_divide_sigfpe": False,
    }
    if not path.is_file():
        return result

    current_time = None
    max_log = -math.inf
    try:
        stream = path.open(errors="replace")
    except OSError:
        return result
    with stream:
        for raw_line in stream:
            line = raw_line.strip()
            time_match = TIME_RE.match(line)
            if time_match:
                current_time = float(time_match.group(1))
                result["last_iteration"] = current_time
                continue
            continuity_match = CONTINUITY_RE.search(line)
            if continuity_match:
                values = [abs(float(value)) for value in continuity_match.groups()]
                result["last_local_continuity"] = values[0]
                result["last_global_continuity"] = values[1]
                result["last_cumulative_continuity"] = values[2]
                magnitude = max(values)
                if magnitude > 0.0:
                    max_log = max(max_log, math.log10(magnitude))
                if (
                    magnitude > 1.0e3
                    and result["first_continuity_gt_1e3"] is None
                ):
                    result["first_continuity_gt_1e3"] = current_time
                if (
                    magnitude > 1.0e12
                    and result["first_continuity_gt_1e12"] is None
                ):
                    result["first_continuity_gt_1e12"] = current_time
            if line == "End":
                result["simple_end"] = True
            if "Foam::sigFpe::sigHandler" in line:
                result["simple_sigfpe"] = True
            if "Foam::divide(" in line:
                result["turbulence_divide_sigfpe"] = True
    if max_log > -math.inf:
        result["max_log10_continuity"] = max_log
    return result


def classify_failure(output, simple, error_text):
    if output["mesh_rejected"]:
        return "mesh_size_limit"
    if output["velocity_rejected"]:
        return "completed_with_runaway_velocity"
    if output["velocity_check_failed"]:
        return "velocity_field_check_failed"
    if output["unclean_end"]:
        return "simpleFoam_unclean_end"
    if output["simple_failed"]:
        if "simpleFoam" in error_text and "Floating point exception" in error_text:
            if simple["turbulence_divide_sigfpe"]:
                return "simpleFoam_turbulence_divide_SIGFPE"
            return "simpleFoam_SIGFPE"
        return "simpleFoam_nonzero_exit"
    return "unclassified_CFD_failure"


def derived_features(row):
    result = {}
    qaerosol_lpm = finite_float(row.get("Qaerosol_lpm"))
    qsheath_lpm = finite_float(row.get("Qsheath_lpm"))
    rin_mm = finite_float(row.get("Rin_mm"))
    radius_mm = finite_float(row.get("R_mm"))
    r1_mm = finite_float(row.get("R1_mm"))
    l2_mm = finite_float(row.get("L2_mm"))
    t_mm = finite_float(row.get("t_mm"))
    if qaerosol_lpm is not None and rin_mm and rin_mm > 0.0:
        flow_m3s = qaerosol_lpm * 1.0e-3 / 60.0
        result["aerosol_mean_velocity_mps"] = flow_m3s / (
            math.pi * (rin_mm * 1.0e-3) ** 2
        )
    if qaerosol_lpm is not None and qsheath_lpm is not None:
        total = qaerosol_lpm + qsheath_lpm
        if total > 0.0:
            result["aerosol_flow_fraction"] = qaerosol_lpm / total
    if radius_mm and radius_mm > 0.0:
        if rin_mm is not None:
            result["Rin_over_R"] = rin_mm / radius_mm
        if r1_mm is not None:
            result["R1_over_R"] = r1_mm / radius_mm
        if l2_mm is not None:
            result["L2_over_R"] = l2_mm / radius_mm
        if t_mm is not None:
            result["t_over_R"] = t_mm / radius_mm
    return result


def case_record(row, campaign, state):
    case = row["case"]
    case_dir = campaign / case
    output = parse_output(case_dir)
    failed = row.get("evaluation_status") == "cfd_failed"
    simple = parse_simple_log(case_dir) if failed else {}
    error_text = read_text(case_dir / "error.txt")
    record = dict(row)
    record.update(output)
    record.update(simple)
    record.update(derived_features(row))
    assignment = state.get("cases", {}).get(case, {})
    record["host"] = assignment.get("host", "")
    record["failed"] = failed
    record["failure_class"] = (
        classify_failure(output, simple, error_text) if failed else "complete"
    )
    record["potential_SIGFPE"] = (
        "potentialFoam" in error_text and "Floating point exception" in error_text
    )
    return record


def feature_values(records, key, failed):
    return [
        value
        for record in records
        if record["failed"] == failed
        for value in [finite_float(record.get(key))]
        if value is not None
    ]


def feature_summary(records, keys):
    summaries = []
    for key in keys:
        failed_values = feature_values(records, key, True)
        complete_values = feature_values(records, key, False)
        if len(failed_values) < 3 or len(complete_values) < 3:
            continue
        all_values = failed_values + complete_values
        q25 = percentile(all_values, 0.25)
        q75 = percentile(all_values, 0.75)
        scale = q75 - q25 if q25 is not None and q75 is not None else 0.0
        failed_median = statistics.median(failed_values)
        complete_median = statistics.median(complete_values)
        separation = (
            (failed_median - complete_median) / scale
            if scale and math.isfinite(scale)
            else 0.0
        )
        summaries.append(
            {
                "feature": key,
                "failed_median": failed_median,
                "complete_median": complete_median,
                "iqr_scaled_median_shift": separation,
                "failed_n": len(failed_values),
                "complete_n": len(complete_values),
            }
        )
    return sorted(
        summaries,
        key=lambda item: abs(item["iqr_scaled_median_shift"]),
        reverse=True,
    )


def quartile_failure_rates(records, key):
    rows = []
    for record in records:
        value = finite_float(record.get(key))
        if value is not None:
            rows.append((value, bool(record["failed"])))
    rows.sort()
    if len(rows) < 8:
        return []
    result = []
    for quartile in range(4):
        start = len(rows) * quartile // 4
        end = len(rows) * (quartile + 1) // 4
        subset = rows[start:end]
        failed = sum(item[1] for item in subset)
        result.append(
            {
                "quartile": quartile + 1,
                "min": subset[0][0],
                "max": subset[-1][0],
                "failed": failed,
                "total": len(subset),
                "rate": failed / float(len(subset)),
            }
        )
    return result


def print_summary(records, feature_keys):
    failed_records = [record for record in records if record["failed"]]
    complete_records = [record for record in records if not record["failed"]]
    print("records:", len(records))
    print("complete:", len(complete_records))
    print("cfd_failed:", len(failed_records))
    print("failure_rate:", len(failed_records) / float(max(len(records), 1)))
    print("failure_classes:", dict(Counter(r["failure_class"] for r in failed_records)))
    print("host_outcomes:")
    host_counts = defaultdict(Counter)
    for record in records:
        host_counts[record["host"]]["failed" if record["failed"] else "complete"] += 1
    for host in sorted(host_counts):
        counts = host_counts[host]
        total = counts["failed"] + counts["complete"]
        print(
            "  %s complete=%d failed=%d rate=%.4f"
            % (host, counts["complete"], counts["failed"], counts["failed"] / total)
        )

    print("failed_cases:")
    for record in failed_records:
        print(
            "  %(case)s host=%(host)s class=%(failure_class)s "
            "last_iteration=%(last_iteration)s first_gt_1e3=%(first_continuity_gt_1e3)s "
            "log10_continuity=%(max_log10_continuity)s maxU=%(max_u_mps)s"
            % record
        )

    summaries = feature_summary(records, feature_keys)
    print("top_feature_shifts:")
    for item in summaries[:15]:
        print(
            "  %(feature)s failed_median=%(failed_median).6g "
            "complete_median=%(complete_median).6g shift_iqr=%(iqr_scaled_median_shift).3f"
            % item
        )
    print("top_feature_quartiles:")
    for item in summaries[:8]:
        print("  " + item["feature"])
        for quartile in quartile_failure_rates(records, item["feature"]):
            print(
                "    Q%(quartile)d [%(min).6g, %(max).6g] "
                "failed=%(failed)d/%(total)d rate=%(rate).3f"
                % quartile
            )


def write_records(path, records):
    keys = []
    for record in records:
        for key in record:
            if key not in keys:
                keys.append(key)
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", default=None)
    parser.add_argument("--method", default="qlognehvi")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    campaign = Path(args.campaign).resolve()
    with Path(args.config).open() as stream:
        config = json.load(stream)
    state_path = Path(args.state) if args.state else campaign / "dispatcher_state.json"
    with state_path.open() as stream:
        state = json.load(stream)
    observations = read_csv(campaign / "bo_observations.csv")
    version = str(config.get("objective", {}).get("version", ""))
    rows = [
        row
        for row in observations
        if row.get("objective_version") == version
        and row.get("evaluation_status") in {"complete", "cfd_failed"}
        and (not args.method or row.get("method") == args.method)
    ]
    records = [case_record(row, campaign, state) for row in rows]
    if args.csv:
        write_records(args.csv, records)

    feature_keys = list(config.get("parameters", {}))
    feature_keys.extend(
        [
            "Rin_mm",
            "L0_mm",
            "L2_mm",
            "L3_mm",
            "L4_mm",
            "t_mm",
            "theta2_deg",
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
            "aerosol_mean_velocity_mps",
            "aerosol_flow_fraction",
            "Rin_over_R",
            "R1_over_R",
            "L2_over_R",
            "t_over_R",
            "mesh_nodes",
            "mesh_elements",
        ]
    )
    print_summary(records, feature_keys)


if __name__ == "__main__":
    main()
