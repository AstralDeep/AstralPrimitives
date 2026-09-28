"""Exercises tooling/python-ci/check_changed_coverage.py in throwaway Git repositories: explicit
not-applicable, pass, and fail decisions, fail-closed handling of malformed reports and
revisions, and real diff-cover JSON reports wherever diff-cover is installed.
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

import check_changed_coverage as changed

MODULE = "".join(f"value_{number} = {number}\n" for number in range(1, 11))
BASE_DIFF = "base...HEAD, staged and unstaged changes"
requires_diff_cover = pytest.mark.skipif(
    importlib.util.find_spec("diff_cover") is None,
    reason="diff-cover is locked only for Python 3.10 and newer",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


def _stats(covered: list[int], violations: list[int]) -> dict:
    return {
        "percent_covered": 100.0,
        "violation_lines": violations,
        "covered_lines": covered,
        "violations": [[line, None] for line in violations],
    }


def _write_report(
    measured_stats: dict | None = None, *, changed_lines: int | None = None, **overrides: object
) -> Path:
    stats = measured_stats or {}
    measured = sum(len(s["covered_lines"]) + len(s["violation_lines"]) for s in stats.values())
    document = {
        "report_name": "XML",
        "diff_name": BASE_DIFF,
        "src_stats": stats,
        "total_num_lines": measured,
        "total_num_violations": sum(len(s["violation_lines"]) for s in stats.values()),
        "total_percent_covered": 100,
        "num_changed_lines": measured if changed_lines is None else changed_lines,
        **overrides,
    }
    path = Path("report.json")
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _decide(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict]:
    code = changed.main(["report.json", "--compare-branch", "base", "--fail-under=90", *args])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Coverage Test",
        "GIT_AUTHOR_EMAIL": "coverage@example.invalid",
        "GIT_COMMITTER_NAME": "Coverage Test",
        "GIT_COMMITTER_EMAIL": "coverage@example.invalid",
    }.items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, {"pkg/mod.py": MODULE, "README.md": "# Demo\n"})
    _git(root, "branch", "base")
    monkeypatch.chdir(root)
    return root


def test_a_diff_without_measurable_lines_is_recorded_as_not_applicable(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _commit(repo, {"README.md": "# Demo\n\nMore.\n"})
    _write_report(changed_lines=2)

    code, decision = _decide(capsys)

    assert code == 0
    assert decision == {
        "status": "not-applicable",
        "reason": "no_measurable_changed_lines",
        "compare_branch": "base",
        "base_sha": _git(repo, "rev-parse", "base"),
        "candidate_sha": _git(repo, "rev-parse", "HEAD"),
        "changed_paths": ["README.md"],
        "measured_paths": [],
        "measured_lines": 0,
        "uncovered_lines": 0,
        "percent_covered": None,
        "fail_under": "90",
    }
    assert summary.read_text(encoding="utf-8") == (
        "### Changed-line coverage: not-applicable\n\n"
        f"```json\n{json.dumps(decision, indent=2)}\n```\n"
    )


def test_an_empty_comparison_is_not_applicable_and_names_identical_revisions(
    repo: Path, capsys
) -> None:
    _write_report()

    code, decision = _decide(capsys)

    assert code == 0
    assert decision["status"] == "not-applicable"
    assert decision["reason"] == "no_changed_paths"
    assert decision["base_sha"] == decision["candidate_sha"] == _git(repo, "rev-parse", "HEAD")
    assert decision["changed_paths"] == []


def test_measured_lines_at_the_threshold_pass(repo: Path, capsys) -> None:
    _commit(repo, {"pkg/mod.py": MODULE + "extra = 11\n", "README.md": "# Demo!\n"})
    _write_report({"pkg/mod.py": _stats(list(range(1, 10)), [10])})

    code, decision = _decide(capsys)

    assert code == 0
    assert decision["status"] == "pass"
    assert "reason" not in decision and "uncovered" not in decision
    assert decision["changed_paths"] == ["README.md", "pkg/mod.py"]
    assert decision["measured_paths"] == ["pkg/mod.py"]
    assert decision["measured_lines"] == 10
    assert decision["uncovered_lines"] == 1
    assert decision["percent_covered"] == "90.00"


@pytest.mark.parametrize(
    "fail_under, status, code", [("90", "fail", 1), ("89.47", "pass", 0), ("89.48", "fail", 1)]
)
def test_measured_lines_are_compared_with_the_exact_threshold(
    repo: Path, capsys, fail_under: str, status: str, code: int
) -> None:
    _commit(repo, {"pkg/mod.py": MODULE + "extra = 11\n"})
    _write_report({"pkg/mod.py": _stats(list(range(1, 18)), [18, 19])})

    exit_code, decision = _decide(capsys, f"--fail-under={fail_under}")

    assert exit_code == code
    assert decision["status"] == status
    assert decision["percent_covered"] == "89.47"
    assert decision["fail_under"] == fail_under
    assert decision.get("uncovered") == ({"pkg/mod.py": [18, 19]} if status == "fail" else None)


@pytest.mark.parametrize(
    "content, message",
    [
        (None, "cannot read diff-cover report"),
        ("{", "cannot read diff-cover report"),
        ("[]", "must be a JSON object"),
        ('{"src_stats": {}}', "diff_name string and a src_stats object"),
        ('{"diff_name": "x", "src_stats": []}', "diff_name string and a src_stats object"),
    ],
)
def test_unreadable_reports_fail_closed(tmp_path: Path, content: str | None, message: str) -> None:
    path = tmp_path / "report.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    with pytest.raises(changed.DecisionError, match=message):
        changed.load_report(path)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"total_num_lines": -1}, "total_num_lines must be a non-negative integer"),
        ({"total_num_violations": True}, "total_num_violations must be a non-negative integer"),
        ({"num_changed_lines": "3"}, "num_changed_lines must be a non-negative integer"),
        ({"src_stats": {"pkg/mod.py": []}}, "stats for pkg/mod.py must be an object"),
        (
            {"src_stats": {"pkg/mod.py": {"violation_lines": []}}},
            "covered_lines for pkg/mod.py must be ascending unique line numbers",
        ),
        (
            {"src_stats": {"pkg/mod.py": _stats([2, 1], [])}},
            "covered_lines for pkg/mod.py must be ascending unique line numbers",
        ),
        (
            {"src_stats": {"pkg/mod.py": _stats([1], [0])}},
            "violation_lines for pkg/mod.py must be ascending unique line numbers",
        ),
        (
            {"src_stats": {"pkg/mod.py": _stats([1], [False])}},
            "violation_lines for pkg/mod.py must be ascending unique line numbers",
        ),
        ({"src_stats": {"pkg/mod.py": _stats([], [])}}, "must be non-empty and disjoint"),
        ({"src_stats": {"pkg/mod.py": _stats([1, 2], [2])}}, "must be non-empty and disjoint"),
        ({"total_num_lines": 4, "num_changed_lines": 4}, "totals disagree"),
        ({"total_num_violations": 2}, "totals disagree"),
        ({"num_changed_lines": 2}, "totals disagree"),
    ],
)
def test_inconsistent_reports_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict, message: str
) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write_report({"pkg/mod.py": _stats([1, 2], [3])}, **overrides)

    with pytest.raises(changed.DecisionError, match=message):
        changed.load_report(path)


def test_a_malformed_report_is_recorded_as_an_error(repo: Path, capsys) -> None:
    Path("report.json").write_text("not json", encoding="utf-8")

    code, decision = _decide(capsys)

    assert code == 1
    assert decision["status"] == "error"
    assert decision["reason"].startswith("cannot read diff-cover report report.json")


@pytest.mark.parametrize(
    "setup, args, message",
    [
        ("dirty", (), "tracked files have uncommitted changes"),
        ("none", ("--compare-branch", "missing"), "git merge-base missing"),
        ("none", ("--compare-branch=--all",), "compare branch must be a revision name"),
        ("none", ("--compare-branch=",), "compare branch must be a revision name"),
        ("other-branch", (), "diff-cover compared 'origin/main...HEAD"),
        ("outside", (), "measured paths outside the compared revisions: pkg/other.py"),
        ("phantom-lines", (), "counted changed lines but the compared revisions change no path"),
    ],
)
def test_reports_that_do_not_match_the_compared_revisions_fail_closed(
    repo: Path, capsys, setup: str, args: tuple, message: str
) -> None:
    if setup == "dirty":
        (repo / "README.md").write_text("# Uncommitted\n", encoding="utf-8")
        _write_report()
    elif setup == "other-branch":
        _write_report(diff_name="origin/main...HEAD, staged and unstaged changes")
    elif setup == "outside":
        _commit(repo, {"pkg/mod.py": MODULE + "extra = 11\n"})
        _write_report({"pkg/other.py": _stats([1], [])})
    elif setup == "phantom-lines":
        _write_report(changed_lines=3)
    else:
        _write_report()

    code, decision = _decide(capsys, *args)

    assert code == 1
    assert decision["status"] == "error"
    assert message in decision["reason"]


def test_a_missing_git_executable_is_recorded_as_an_error(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write_report()
    monkeypatch.setenv("PATH", str(tmp_path / "no-git-here"))

    code, decision = _decide(capsys)

    assert code == 1
    assert decision["status"] == "error"
    assert decision["reason"].startswith("cannot run git")


@pytest.mark.parametrize("value", ["abc", "nan", "inf", "-1", "100.01"])
def test_thresholds_outside_zero_to_one_hundred_are_rejected(value: str, capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        changed.main(["report.json", "--compare-branch", "base", f"--fail-under={value}"])

    assert exit_info.value.code == 2
    assert "must be a percentage from 0 to 100" in capsys.readouterr().err


def test_threshold_bounds_are_inclusive() -> None:
    assert changed._threshold("0") == Decimal("0")
    assert changed._threshold("100") == Decimal("100")


def test_the_script_entry_point_exits_with_the_decision_code(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write_report()
    script = Path(changed.__file__)
    monkeypatch.setattr(
        sys, "argv", [str(script), "report.json", "--compare-branch", "base", "--fail-under=90"]
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(script), run_name="__main__")

    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not-applicable"


def _cobertura(hits: dict[int, int]) -> str:
    lines = "".join(f'<line number="{line}" hits="{hit}"/>' for line, hit in sorted(hits.items()))
    return (
        '<?xml version="1.0" ?><coverage><packages><package name="pkg"><classes>'
        f'<class name="mod.py" filename="pkg/mod.py"><lines>{lines}</lines></class>'
        "</classes></package></packages></coverage>"
    )


def _run_diff_cover(repo: Path, hits: dict[int, int]) -> int:
    (repo / "coverage.xml").write_text(_cobertura(hits), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            "coverage.xml",
            "--compare-branch",
            "base",
            "--fail-under=90",
            "--format",
            "json:report.json",
        ],
        cwd=repo,
        capture_output=True,
        check=False,
    ).returncode


@requires_diff_cover
def test_real_diff_cover_reports_for_unmeasured_changes_are_not_applicable(
    repo: Path, capsys
) -> None:
    _commit(repo, {"README.md": "# Demo\n\nMore.\n"})

    assert _run_diff_cover(repo, {line: 1 for line in range(1, 11)}) == 0
    code, decision = _decide(capsys)

    assert code == 0
    assert decision["status"] == "not-applicable"
    assert decision["reason"] == "no_measurable_changed_lines"
    assert decision["changed_paths"] == ["README.md"]


@requires_diff_cover
@pytest.mark.parametrize(
    "line_12_hits, diff_cover_code, status, code", [(1, 0, "pass", 0), (0, 1, "fail", 1)]
)
def test_real_diff_cover_reports_for_measured_changes_are_decided_on_their_lines(
    repo: Path, capsys, line_12_hits: int, diff_cover_code: int, status: str, code: int
) -> None:
    _commit(repo, {"pkg/mod.py": MODULE + "value_11 = 11\nvalue_12 = 12\n"})
    hits = {line: 1 for line in range(1, 12)}
    hits[12] = line_12_hits

    assert _run_diff_cover(repo, hits) == diff_cover_code
    exit_code, decision = _decide(capsys)

    assert exit_code == code
    assert decision["status"] == status
    assert decision["measured_paths"] == ["pkg/mod.py"]
    assert decision["measured_lines"] == 2
    assert decision.get("uncovered") == ({"pkg/mod.py": [12]} if status == "fail" else None)
