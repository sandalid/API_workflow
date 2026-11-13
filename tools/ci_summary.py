"""Validate a completed CI API run and stage only its normalized reports.

This is an execution gate, not a workbook-case or business-flow verdict. Raw
Schemathesis reports, credentials and fixture/spec snapshots are never copied.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil


class ReportError(ValueError):
    """A missing, unsafe or malformed report; messages must not contain payloads."""


def confined(path, root):
    resolved = path.resolve(strict=True)
    if resolved == root or not resolved.is_relative_to(root):
        raise ReportError("The report path is outside the expected results folder.")
    return resolved


def find_run(results_dir):
    if not results_dir.is_absolute():
        raise ReportError("The results directory must be an absolute path.")
    root = results_dir.resolve(strict=True)
    pointer = confined(root / "last_run.txt", root)
    value = pointer.read_text(encoding="utf-8-sig").strip()
    if not value or "\n" in value or "\r" in value:
        raise ReportError("The latest-run pointer is empty or malformed.")
    candidate = Path(value)
    run = confined(candidate if candidate.is_absolute() else root / candidate, root)
    if not run.is_dir():
        raise ReportError("The latest-run pointer does not identify a directory.")
    return run


def read_report(run, name):
    path = confined(run / name, run)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ReportError(f"{name} must contain a JSON object.")
    return data, path


def validate(manifest, evidence, run_name):
    issues = []
    counts = {"requests": 0, "successful_checks": 0, "failed_checks": 0,
              "errored_checks": 0, "skipped_checks": 0, "execution_errors": 0}

    def issue(message):
        if message not in issues:
            issues.append(message)

    if not re.fullmatch(r"RUN-[A-Za-z0-9_-]+", run_name):
        issue("The run directory name is invalid.")
    if manifest.get("run_id") != run_name or evidence.get("run_id") != run_name:
        issue("Manifest and evidence run IDs do not match the selected run.")
    if evidence.get("schema_version") != 1:
        issue("The evidence schema version is missing or unsupported.")
    auth = manifest.get("auth")
    if not isinstance(auth, dict) or auth.get("status") != "ok":
        issue("Authentication was not confirmed successful.")
    if manifest.get("status") != "completed" or manifest.get("stop_reason") != "completed":
        issue("The run did not report a complete execution.")
    if not manifest.get("started") or not manifest.get("finished"):
        issue("The run start or finish timestamp is missing.")
    exit_code = manifest.get("exit_code")
    if type(exit_code) is not int or exit_code != 0:
        issue("The test process did not report a successful exit.")
    phases = manifest.get("phases")
    if not isinstance(phases, dict) or not phases:
        issue("Phase outcomes are missing or malformed.")
    elif any(status not in ("success", "skip") for status in phases.values()):
        issue("One or more execution phases failed or did not complete.")
    for report in (manifest, evidence):
        errors = report.get("execution_errors")
        if not isinstance(errors, list):
            issue("Execution-error records are missing or malformed.")
        else:
            counts["execution_errors"] = max(counts["execution_errors"], len(errors))
            if errors:
                issue("Execution errors were recorded.")

    interactions = evidence.get("interactions")
    if not isinstance(interactions, list):
        issue("Request evidence is missing or malformed.")
        return issues, counts
    counts["requests"] = len(interactions)
    if not interactions:
        issue("No requests were recorded; this is not a passing run.")
    if type(manifest.get("interactions")) is not int or manifest["interactions"] != len(interactions):
        issue("The manifest request count does not match the evidence.")
    for interaction in interactions:
        if not isinstance(interaction, dict):
            issue("A request record is malformed.")
            continue
        if interaction.get("error"):
            issue("A request execution error was recorded.")
        response = interaction.get("response")
        if not isinstance(response, dict) or type(response.get("status")) is not int or not 100 <= response["status"] <= 599:
            issue("A request has no valid recorded HTTP response.")
        elif response["status"] == 429:
            issue("Rate limiting prevented a reliable run.")
        checks = interaction.get("checks")
        if not isinstance(checks, list) or not checks:
            issue("A request has no recorded assertions.")
            continue
        performed = False
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"]:
                issue("An assertion record is malformed.")
                continue
            status = check.get("status")
            if status in ("success", "failure"):
                performed = True
                counts["successful_checks" if status == "success" else "failed_checks"] += 1
            elif status == "error":
                counts["errored_checks"] += 1
            elif status in ("skip", "skipped"):
                counts["skipped_checks"] += 1
            else:
                issue("An assertion has an unrecognized outcome.")
        if not performed:
            issue("A request has no completed assertions.")
    if counts["failed_checks"]:
        issue("Assertions failed.")
    if counts["errored_checks"]:
        issue("Assertion execution errors were recorded.")
    return issues, counts


def summarize(results_dir, output_dir):
    """Always write a body-free summary, including when execution/reporting fails."""
    output_dir.mkdir(parents=True, exist_ok=True)
    issues, counts = [], None
    run_name = None
    reports = {}
    try:
        run = find_run(results_dir)
        run_name = run.name if re.fullmatch(r"RUN-[A-Za-z0-9_-]+", run.name) else None
        for name in ("run.json", "evidence.json"):
            try:
                data, path = read_report(run, name)
                reports[name] = data
                # Keep diagnostic evidence for genuine failures; never copy raw or
                # unparsable files, or reports belonging to another run.
                if run_name and data.get("run_id") == run_name:
                    shutil.copyfile(path, output_dir / name)
            except (OSError, ValueError):
                issues.append(f"{name} is missing, malformed or outside the run folder.")
        if len(reports) == 2:
            validation_issues, counts = validate(reports["run.json"], reports["evidence.json"], run.name)
            issues.extend(validation_issues)
    except (OSError, ValueError):
        issues.append("The latest-run pointer is missing, malformed or outside the results folder.")
    outcome = "FAIL" if issues else "PASS"
    lines = [f"# API smoke test: {outcome}", ""]
    if run_name:
        lines += [f"Run: `{run_name}`", ""]
    if counts is not None:
        lines += ["| Evidence | Count |", "|---|---:|"]
        lines += [f"| {key.replace('_', ' ').capitalize()} | {value} |" for key, value in counts.items()]
        lines.append("")
    if issues:
        lines += [f"- {message}" for message in issues] + [""]
    lines += ["This result covers recorded API checks; it does not certify workbook cases or end-to-end business flows.", ""]
    summary = "\n".join(lines)
    (output_dir / "summary.md").write_text(summary, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write(summary + "\n")
    print(summary)
    return 1 if issues else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    return summarize(args.results_dir, args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
