"""Verify the bounded regression gate counts behavioral failures rather than broken runs.
Synthetic JUnit reports exercise survival, collection, import, skip, and control failures.
"""

import json
from pathlib import Path

import pytest


def test_only_the_named_behavior_failure_kills_a_mutation(tmp_path):
    from check_regression_effectiveness import classify_result

    report = tmp_path / "result.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_guard"><failure message="AssertionError: accepted invalid input"/></testcase></testsuite></testsuites>'
    )
    assert classify_result(1, report, "test_guard", mutant=True) == "killed"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_guard"/></testsuite></testsuites>'
    )
    assert classify_result(0, report, "test_guard", mutant=False) == "passed"
    with pytest.raises(ValueError, match="survived"):
        classify_result(0, report, "test_guard", mutant=True)


@pytest.mark.parametrize(
    "body",
    [
        '<error message="collection failed"/>',
        '<failure message="ModuleNotFoundError: missing"/>',
        '<failure message="ImportError: missing"/>',
        '<failure message="SyntaxError: invalid syntax"/>',
        '<failure message="NameError: missing"/>',
        "<skipped/>",
    ],
)
def test_broken_runs_do_not_count_as_mutation_kills(tmp_path, body):
    from check_regression_effectiveness import classify_result

    report = tmp_path / "result.xml"
    report.write_text(
        '<testsuites><testsuite><testcase name="test_guard">'
        + body
        + "</testcase></testsuite></testsuites>"
    )
    with pytest.raises(ValueError):
        classify_result(1, report, "test_guard", mutant=True)


def test_wrong_test_missing_report_and_failed_control_are_errors(tmp_path):
    from check_regression_effectiveness import classify_result

    report = tmp_path / "result.xml"
    with pytest.raises(ValueError):
        classify_result(1, report, "test_guard", mutant=True)
    report.write_text(
        '<testsuites><testsuite><testcase name="wrong"><failure message="AssertionError"/></testcase></testsuite></testsuites>'
    )
    with pytest.raises(ValueError):
        classify_result(1, report, "test_guard", mutant=True)
    report.write_text(
        '<testsuites><testsuite><testcase name="test_guard"><failure message="AssertionError"/></testcase></testsuite></testsuites>'
    )
    with pytest.raises(ValueError):
        classify_result(1, report, "test_guard", mutant=False)


def test_real_controls_and_known_broken_guards_fail_the_named_cases(
    monkeypatch, capsys
):
    from check_regression_effectiveness import main

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mutations"] == 6
    assert all(
        case["control"] == "passed" and case["mutation_result"] == "killed"
        for case in report["results"]
    )


def test_stale_mutation_target_and_cli_failure_are_errors(monkeypatch, capsys):
    import check_regression_effectiveness as gate

    root = Path(__file__).resolve().parents[1]
    mutation = ("invalid", "base.py", "missing maintained target", "", "test_guard")
    with pytest.raises(ValueError, match="maintained target"):
        gate.run_case(root, mutation, mutant=True)
    monkeypatch.setattr(gate, "MUTATIONS", [mutation])
    monkeypatch.chdir(root)
    assert gate.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"
