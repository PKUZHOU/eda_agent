#!/usr/bin/env python3
"""Conservative report observations and comparable-manifest deltas (Python 3.6+)."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
CONTEXT = ("design", "rtl_sha256", "constraints_sha256", "libraries_sha256",
           "physical_technology_sha256", "rc_method", "stage", "tool_versions",
           "seed", "time_unit", "area_unit", "scenarios")
STAGES = ("synthesis", "placement", "cts", "route", "route_opt", "signoff")
ROUTED = ("route", "route_opt", "signoff")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root):
    root = Path(root)
    if not root.exists():
        raise ValueError("Report input does not exist: " + str(root))
    paths = [root] if root.is_file() else sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix in (".rpt", ".log"))
    result = {"kind": "observations_only", "signoff_certified": False,
              "files": [], "findings": [], "skipped_files": []}
    for path in paths:
        if path.stat().st_size > 20 * 1024 * 1024:
            result["skipped_files"].append(str(path))
            continue
        lines = path.read_text(errors="replace").splitlines()
        entry = {"path": str(path.resolve()), "sha256": digest(path),
                 "observations": [], "sampled_min_slack": None,
                 "tns": None, "units": "not_inferred"}
        slacks = []
        for lineno, line in enumerate(lines, 1):
            def observe(name, value):
                entry["observations"].append({"metric": name, "value": value,
                                               "line": lineno})

            def finding(code, severity):
                result["findings"].append({"code": code, "severity": severity,
                    "path": entry["path"], "line": lineno, "text": line.strip()})

            match = re.search(r"\bslack\s+\((?:MET|VIOLATED)\)\s+(" + NUMBER + r")", line)
            if match:
                value = float(match.group(1))
                slacks.append(value)
                observe("reported_path_slack", value)
            match = re.match(r"\s*Total cell area:\s*(" + NUMBER + r")", line)
            if match:
                observe("total_cell_area_report_units", float(match.group(1)))
            match = re.match(r"\s*Total number of DRCs\s*=\s*(\d+)\s*$", line)
            if match:
                observe("drc_count", int(match.group(1)))
                if int(match.group(1)):
                    finding("nonzero_drc_observed", "review_before_final_acceptance")
            match = re.match(r"\s*Total number of open nets\s*=\s*(\d+)", line)
            if match:
                observe("open_net_count", int(match.group(1)))
                if int(match.group(1)):
                    finding("open_nets_observed", "review_before_final_acceptance")
            if re.search(r"Zero interconnect delay|extractor can not be initialized|"
                         r"no valid parasitic", line, re.I):
                finding("invalid_parasitic_timing_evidence", "blocks_routed_timing_claim")
            if re.search(r"^\s*-(max_paths|slack_lesser_than)\b", line):
                finding("limited_timing_report", "scope_limitation")
            if "No paths with slack less than" in line:
                finding("no_matching_paths_not_numeric_wns", "scope_limitation")
            if re.match(r"\s*(Error:|Fatal:)", line, re.I):
                finding("tool_error_observed", "review_run_validity")
        if slacks:
            entry["sampled_min_slack"] = min(slacks)
        result["files"].append(entry)
    result["status"] = ("insufficient_reports" if not result["files"] else
                        "review_required" if result["findings"] else "no_known_pattern_found")
    result["limitations"] = [
        "No-pattern-found is not proof of validity; unknown formats remain unparsed.",
        "Observed log messages can describe intermediate states; inspect final stage evidence.",
        "Sampled path slack does not certify global WNS; TNS and units are not inferred."]
    return result


def present(value):
    return value is not None and value != "" and value != [] and value != {}


def numeric(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Missing/nonfinite numeric metric: " + field)
    return float(value)


def validate(run):
    if not isinstance(run, dict):
        raise ValueError("Manifest must be an object")
    if not isinstance(run.get("run_id"), str) or not run["run_id"].strip():
        raise ValueError("Nonempty run_id required")
    if run.get("status") != "completed":
        raise ValueError("Run must have completed; failure/timeout is not a QoR sample")
    context = run.get("context", {})
    if not isinstance(context, dict) or any(not present(context.get(k)) for k in CONTEXT):
        raise ValueError("Missing comparison context; see run-contract.md")
    if context["stage"] not in STAGES:
        raise ValueError("Unknown stage")
    scenarios = context["scenarios"]
    if (not isinstance(scenarios, list) or not scenarios or
            any(not isinstance(s, str) or not s.strip() for s in scenarios) or
            len(set(scenarios)) != len(scenarios)):
        raise ValueError("Scenarios must be a nonempty unique string list")
    evidence = run.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("Report provenance is required")
    for item in evidence:
        if not isinstance(item, dict) or not present(item.get("path")) or not re.fullmatch(
                r"[0-9a-fA-F]{64}", str(item.get("sha256", ""))):
            raise ValueError("Evidence needs a report path and SHA256")
    metrics = run.get("metrics", {})
    if not isinstance(metrics, dict) or not isinstance(metrics.get("scenarios"), dict):
        raise ValueError("Scenario metrics must be an object")
    if set(metrics["scenarios"]) != set(scenarios):
        raise ValueError("Scenario metrics do not match the required scenario set")
    if numeric(metrics.get("cell_area"), "cell_area") < 0:
        raise ValueError("Area must be nonnegative")
    for scenario, values in metrics["scenarios"].items():
        if not isinstance(values, dict):
            raise ValueError("Scenario values must be an object")
        for field in ("setup_wns", "setup_tns", "hold_wns", "hold_tns"):
            value = numeric(values.get(field), scenario + "." + field)
            if field.endswith("tns") and value > 0:
                raise ValueError("This contract uses nonpositive signed TNS")
    validity = run.get("validity", {})
    if not isinstance(validity, dict):
        raise ValueError("Validity must be an object")
    issues = [key for key in ("constraints_checked", "coverage_checked", "parasitics_checked")
              if validity.get(key) is not True]
    if validity.get("equivalence") != "pass":
        issues.append("equivalence_not_passed")
    if context["stage"] in ROUTED:
        for key in ("drc_count", "open_net_count", "unconstrained_endpoint_count"):
            value = metrics.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Expected a nonnegative integer for " + key)
            if value:
                issues.append(key + "_nonzero")
    return issues


def compare(baseline, candidate):
    invalidity = {"baseline": validate(baseline), "candidate": validate(candidate)}
    bc, cc = baseline["context"], candidate["context"]
    mismatches = [key for key in CONTEXT if bc[key] != cc[key]]
    if mismatches:
        raise ValueError("Incomparable context: " + ", ".join(mismatches))
    bm, cm = baseline["metrics"], candidate["metrics"]
    deltas = []

    def add(name, before, after, direction, unit):
        before, after = numeric(before, name), numeric(after, name)
        delta = after - before
        change = "unchanged" if delta == 0 else (
            "improved" if (delta > 0) == (direction == "higher") else "regressed")
        deltas.append({"metric": name, "baseline": before, "candidate": after,
                       "delta": delta, "unit": unit, "change": change})

    add("cell_area", bm["cell_area"], cm["cell_area"], "lower", bc["area_unit"])
    for scenario in bc["scenarios"]:
        for field in ("setup_wns", "setup_tns", "hold_wns", "hold_tns"):
            add(scenario + "." + field, bm["scenarios"][scenario][field],
                cm["scenarios"][scenario][field], "higher", bc["time_unit"])
    if bc["stage"] in ROUTED:
        for key in ("drc_count", "open_net_count", "unconstrained_endpoint_count"):
            add(key, bm[key], cm[key], "lower", "count")
    power_status = "not_compared"
    if "total_power" in bm or "total_power" in cm:
        fields = ("power_method", "activity_sha256", "power_unit")
        if ("total_power" not in bm or "total_power" not in cm or
                any(not present(bc.get(k)) or bc[k] != cc.get(k) for k in fields)):
            raise ValueError("Power requires both metrics and matching method/activity/units")
        if numeric(bm["total_power"], "power") < 0 or numeric(cm["total_power"], "power") < 0:
            raise ValueError("Power must be nonnegative")
        add("total_power", bm["total_power"], cm["total_power"], "lower", bc["power_unit"])
        power_status = "compared"
    changes = {d["change"] for d in deltas}
    relation = ("candidate_dominates" if "improved" in changes and "regressed" not in changes
                else "baseline_dominates" if "regressed" in changes and "improved" not in changes
                else "equal" if changes == {"unchanged"} else "tradeoff")
    return {"baseline": baseline["run_id"], "candidate": candidate["run_id"],
            "comparable": True, "relation": relation, "deltas": deltas,
            "power": power_status, "validity_issues": invalidity,
            "eligible_for_engineering_review": not any(invalidity.values()),
            "signoff_certified": False,
            "limitations": ["Provenance fields are checked, report contents are not certified.",
                             "Feasibility budgets and remaining physical/electrical checks need review."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("audit")
    p.add_argument("reports")
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("baseline")
    p.add_argument("candidate")
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if not args.command:
        parser.error("Choose audit or compare")
    try:
        result = (audit(args.reports) if args.command == "audit" else compare(
            json.loads(Path(args.baseline).read_text()), json.loads(Path(args.candidate).read_text())))
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.exit(2, "qor: " + str(error) + "\n")
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(str(Path(args.out).resolve()))


if __name__ == "__main__":
    main()
