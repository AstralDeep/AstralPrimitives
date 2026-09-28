"""Turns diff-cover's JSON report into one explicit changed-line coverage decision that names
the base and candidate commits and the paths changed between them: pass, fail, or
not-applicable when no measurable executable line changed. The quality-package job in
.github/workflows/ci.yml runs it after diff-cover compares the event's base SHA directly with
HEAD, and tests/test_check_changed_coverage.py pins its behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

PASSING_STATUSES = ("pass", "not-applicable")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
NULL_SHA = "0" * 40


class DecisionError(Exception):
    pass


class Report(NamedTuple):
    diff_name: str
    measured_lines: int
    changed_lines: int
    uncovered: Dict[str, List[int]]
    measured_paths: List[str]


class Revisions(NamedTuple):
    base_sha: str
    candidate_sha: str
    changed_paths: List[str]


def _count(document: Dict[str, Any], key: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DecisionError(f"diff-cover report {key} must be a non-negative integer")
    return value


def _line_numbers(stats: Dict[str, Any], path: str, key: str) -> List[int]:
    value = stats.get(key)
    if (
        not isinstance(value, list)
        or not all(isinstance(line, int) and not isinstance(line, bool) and line > 0 for line in value)
        or value != sorted(set(value))
    ):
        raise DecisionError(
            f"diff-cover report {key} for {path} must be ascending unique line numbers"
        )
    return value


def load_report(path: Path) -> Report:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DecisionError(f"cannot read diff-cover report {path}: {error}") from error
    if not isinstance(document, dict):
        raise DecisionError("diff-cover report must be a JSON object")
    diff_name, src_stats = document.get("diff_name"), document.get("src_stats")
    if not isinstance(diff_name, str) or not isinstance(src_stats, dict):
        raise DecisionError("diff-cover report must carry a diff_name string and a src_stats object")
    measured = _count(document, "total_num_lines")
    violations = _count(document, "total_num_violations")
    changed = _count(document, "num_changed_lines")
    uncovered: Dict[str, List[int]] = {}
    listed = 0
    for src_path, stats in src_stats.items():
        if not isinstance(stats, dict):
            raise DecisionError(f"diff-cover report stats for {src_path} must be an object")
        covered = _line_numbers(stats, src_path, "covered_lines")
        missing = _line_numbers(stats, src_path, "violation_lines")
        if not (covered or missing) or set(covered) & set(missing):
            raise DecisionError(
                f"diff-cover report lines for {src_path} must be non-empty and disjoint"
            )
        listed += len(covered) + len(missing)
        if missing:
            uncovered[src_path] = missing
    if listed != measured or sum(map(len, uncovered.values())) != violations or measured > changed:
        raise DecisionError("diff-cover report totals disagree with its per-file line lists")
    return Report(diff_name, measured, changed, uncovered, sorted(src_stats))


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], capture_output=True, encoding="utf-8", check=False
        )
    except OSError as error:
        raise DecisionError(f"cannot run git: {error}") from error
    if completed.returncode != 0:
        raise DecisionError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def resolve_revisions(base_sha: str) -> Revisions:
    if _git("status", "--porcelain", "--untracked-files=no").strip():
        raise DecisionError(
            "tracked files have uncommitted changes, so the measured tree is not a revision"
        )
    if _git("rev-parse", "--verify", f"{base_sha}^{{commit}}").strip() != base_sha:
        raise DecisionError(f"base {base_sha} is not a commit object")
    candidate = _git("rev-parse", "--verify", "HEAD^{commit}").strip()
    paths = _git("diff", "--name-only", "-z", base_sha, candidate).split("\0")
    return Revisions(base_sha, candidate, sorted(path for path in paths if path))


def decide(report: Report, revisions: Revisions, fail_under: Decimal) -> Dict[str, Any]:
    if not report.diff_name.startswith(f"{revisions.base_sha}..HEAD"):
        raise DecisionError(
            f"diff-cover compared {report.diff_name!r}, not {revisions.base_sha}..HEAD"
        )
    outside = sorted(set(report.measured_paths) - set(revisions.changed_paths))
    if outside:
        raise DecisionError(
            f"diff-cover measured paths outside the compared revisions: {', '.join(outside)}"
        )
    if report.changed_lines and not revisions.changed_paths:
        raise DecisionError("diff-cover counted changed lines but the compared revisions change no path")
    uncovered_lines = sum(map(len, report.uncovered.values()))
    covered_lines = report.measured_lines - uncovered_lines
    if not report.measured_lines:
        status = "not-applicable"
    elif covered_lines * 100 >= fail_under * report.measured_lines:
        status = "pass"
    else:
        status = "fail"
    decision: Dict[str, Any] = {"status": status}
    if status == "not-applicable":
        decision["reason"] = (
            "no_measurable_changed_lines" if revisions.changed_paths else "no_changed_paths"
        )
    decision.update(
        base_sha=revisions.base_sha,
        candidate_sha=revisions.candidate_sha,
        changed_paths=revisions.changed_paths,
        measured_paths=report.measured_paths,
        measured_lines=report.measured_lines,
        uncovered_lines=uncovered_lines,
        percent_covered=(
            str(
                (Decimal(covered_lines * 100) / report.measured_lines).quantize(
                    Decimal("0.01"), rounding=ROUND_FLOOR
                )
            )
            if report.measured_lines
            else None
        ),
        fail_under=str(fail_under),
    )
    if status == "fail":
        decision["uncovered"] = report.uncovered
    return decision


def _base_sha(text: str) -> str:
    if not COMMIT_SHA.fullmatch(text) or text == NULL_SHA:
        raise argparse.ArgumentTypeError(f"must be a non-zero 40-hex commit SHA, not {text!r}")
    return text


def _threshold(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        value = Decimal("NaN")
    if not value.is_finite() or not 0 <= value <= 100:
        raise argparse.ArgumentTypeError(f"must be a percentage from 0 to 100, not {text!r}")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record the changed-line coverage decision for a diff-cover JSON report."
    )
    parser.add_argument("report", type=Path, help="diff-cover --format json output")
    parser.add_argument(
        "--base-sha", required=True, type=_base_sha, help="the commit diff-cover compared with HEAD"
    )
    parser.add_argument("--fail-under", required=True, type=_threshold, help="minimum percent")
    args = parser.parse_args(argv)
    try:
        report = load_report(args.report)
        decision = decide(report, resolve_revisions(args.base_sha), args.fail_under)
    except DecisionError as error:
        decision = {"status": "error", "reason": str(error)}
    rendered = json.dumps(decision, indent=2)
    print(rendered)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(
                f"### Changed-line coverage: {decision['status']}\n\n```json\n{rendered}\n```\n"
            )
    return 0 if decision["status"] in PASSING_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
