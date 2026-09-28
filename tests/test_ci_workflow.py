"""Tests for AstralPrimitives' GitHub Actions workflows: pinned/approved action SHAs, a
job-level timeout of at most 30 minutes on every job, the main/PR
quality-compatibility-package gate sequence with changed lines gated against the event's base
SHA, and the hash-constrained Python 3.9 build backend.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_SHA = re.compile(r"^[^\s#]+@[0-9a-f]{40}(?:\s+#.*)?$")
APPROVED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "astral-sh/setup-uv": "c771a70e6277c0a99b617c7a806ffedaca235ff9",
    "pypa/gh-action-pypi-publish": "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
}
JOB_TIMEOUT = re.compile(r"(?m)^    timeout-minutes:(.*)$")
MAX_JOB_MINUTES = 30
EVENT_BASE_SHA = "BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}"


def _job_ids(text: str) -> set[str]:
    jobs = text.partition("\njobs:\n")[2]
    assert jobs, "workflow must define jobs"
    return set(re.findall(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", jobs))


def _job(text: str, job_id: str) -> str:
    jobs = text.partition("\njobs:\n")[2]
    match = re.search(
        rf"(?ms)^  {re.escape(job_id)}:\s*\n(.*?)(?=^  [A-Za-z0-9_-]+:\s*$|\Z)",
        jobs,
    )
    assert match, f"missing job {job_id!r}"
    return match.group(1)


def _assert_actions_are_approved(text: str) -> None:
    uses = [line.strip().removeprefix("- ") for line in text.splitlines() if "uses:" in line]
    assert uses
    for use in uses:
        reference = use.partition("uses:")[2].strip()
        assert ACTION_SHA.fullmatch(reference), f"action is not SHA-pinned: {reference}"
        target = reference.partition(" #")[0]
        action, separator, sha = target.partition("@")
        assert separator and APPROVED_ACTIONS.get(action) == sha, (
            f"unapproved action pin: {target}"
        )


def _assert_jobs_are_time_bounded(text: str) -> None:
    for job_id in sorted(_job_ids(text)):
        values = [value.strip() for value in JOB_TIMEOUT.findall(_job(text, job_id))]
        assert len(values) == 1, f"job {job_id!r} must declare one job-level timeout-minutes"
        assert values[0].isdigit() and 1 <= int(values[0]) <= MAX_JOB_MINUTES, (
            f"job {job_id!r} timeout-minutes must be an integer from 1 to {MAX_JOB_MINUTES}"
        )


def test_every_workflow_job_is_time_bounded_and_uses_only_approved_actions() -> None:
    workflows = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])

    assert {"ci.yml", "python-publish.yml"} <= {path.name for path in workflows}
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        _assert_jobs_are_time_bounded(text)
        _assert_actions_are_approved(text)
        assert "continue-on-error:" not in text, path.name


@pytest.mark.parametrize(
    "job_body, message",
    [
        ("    runs-on: ubuntu-24.04\n", "must declare one job-level timeout-minutes"),
        (
            "    steps:\n      - run: true\n        timeout-minutes: 5\n",
            "must declare one job-level timeout-minutes",
        ),
        (
            "    timeout-minutes: 10\n    timeout-minutes: 10\n",
            "must declare one job-level timeout-minutes",
        ),
        ("    timeout-minutes: 31\n", "integer from 1 to 30"),
        ("    timeout-minutes: 0\n", "integer from 1 to 30"),
        ("    timeout-minutes: ${{ inputs.minutes }}\n", "integer from 1 to 30"),
    ],
)
def test_missing_or_unbounded_job_timeouts_are_rejected(job_body: str, message: str) -> None:
    bounded = "name: sample\njobs:\n  bounded:\n    timeout-minutes: 30\n"
    _assert_jobs_are_time_bounded(bounded)

    with pytest.raises(AssertionError, match=message):
        _assert_jobs_are_time_bounded(f"{bounded}  candidate:\n{job_body}")


def test_main_and_pull_requests_run_locked_quality_compatibility_and_package_gates() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert _job_ids(text) == {"quality-package", "compatibility", "gates"}
    assert re.search(
        r"(?m)^on:\n  pull_request:\n    branches: \[main\]\n  push:\n    branches: \[main\]$",
        text,
    )
    assert "workflow_dispatch:" not in text
    assert re.search(r"(?m)^permissions:\n  contents: read$", text)
    assert "id-token:" not in text
    assert "continue-on-error:" not in text
    assert "uv build --frozen" not in text
    assert "version: \"0.11.26\"" in text
    _assert_actions_are_approved(text)

    quality = _job(text, "quality-package")
    for command in (
        "uv lock --check",
        "uv sync --frozen --group ci",
        "ruff check .",
        "--cov=astralprims --cov=tooling/python-ci --cov-branch --cov-report=xml --cov-fail-under=90",
        "fetch-depth: 0",
        EVENT_BASE_SHA,
        "set -euo pipefail",
        '[[ "$BASE_SHA" =~ ^[a-f0-9]{40}$ ]] || { echo "::error::BASE_SHA is not a 40-hex SHA"; exit 1; }',
        '[[ "$BASE_SHA" != 0000000000000000000000000000000000000000 ]] || { echo "::error::BASE_SHA is all zeros"; exit 1; }',
        "diff-cover coverage.xml",
        "--compare-branch \"$BASE_SHA\" --diff-range-notation '..' --fail-under=90",
        "--format json:changed-coverage.json",
        "python tooling/python-ci/check_changed_coverage.py",
        'changed-coverage.json --base-sha "$BASE_SHA" --fail-under=90',
        "uv build --build-constraints tooling/python-ci/build-requirements.lock.txt --require-hashes",
        "twine check dist/*",
        'installed_version == manifest["project"]["version"]',
        'astralprims.__version__ == installed_version',
        'path.as_posix() == "astralprims/py.typed"',
        'Text(content="ci").to_dict() == {',
        '"variant": "body"',
    ):
        assert command in quality
    assert (
        quality.index(EVENT_BASE_SHA)
        < quality.index('[[ "$BASE_SHA"')
        < quality.index("diff-cover coverage.xml")
        < quality.index("check_changed_coverage.py")
        < quality.index("uv build")
    )
    assert "origin/main" not in text
    assert "dist/*.whl" in quality and "dist/*.tar.gz" in quality

    compatibility = _job(text, "compatibility")
    matrix = re.search(r"python: \[([^]]+)\]", compatibility)
    assert matrix
    assert set(re.findall(r'"([^"]+)"', matrix.group(1))) == {"3.9", "3.11", "3.14"}
    assert "pytest -q -p no:cacheprovider" in compatibility

    gates = _job(text, "gates")
    assert "if: always()" in gates
    assert "needs: [quality-package, compatibility]" in gates
    assert "needs.quality-package.result" in gates
    assert "needs.compatibility.result" in gates


def _base_sha_guard() -> str:
    quality = _job((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"), "quality-package")
    guard = [line.strip() for line in quality.splitlines() if line.strip().startswith("[[ ")]
    assert guard, "quality-package must validate BASE_SHA before diff-cover"
    return "\n".join(["set -euo pipefail", *guard])


@pytest.mark.parametrize(
    "base_sha, error",
    [
        ("0123456789abcdef0123456789abcdef01234567", None),
        ("0" * 40, "BASE_SHA is all zeros"),
        ("", "BASE_SHA is not a 40-hex SHA"),
        ("0123456789ABCDEF0123456789ABCDEF01234567", "BASE_SHA is not a 40-hex SHA"),
        ("0123456789abcdef0123456789abcdef0123456", "BASE_SHA is not a 40-hex SHA"),
        ("0123456789abcdef0123456789abcdef012345678", "BASE_SHA is not a 40-hex SHA"),
        ("origin/main", "BASE_SHA is not a 40-hex SHA"),
    ],
)
def test_the_changed_line_step_accepts_only_a_nonzero_40_hex_base_sha(
    base_sha: str, error: str | None
) -> None:
    completed = subprocess.run(
        ["bash", "-c", _base_sha_guard()],
        env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "BASE_SHA": base_sha},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (completed.returncode, completed.stdout) == (
        (0, "") if error is None else (1, f"::error::{error}\n")
    )


def test_the_changed_line_step_fails_when_the_event_supplies_no_base_sha() -> None:
    completed = subprocess.run(
        ["bash", "-c", _base_sha_guard()],
        env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"},
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0


def test_publication_verifies_without_oidc_before_environment_protected_upload() -> None:
    text = (WORKFLOWS / "python-publish.yml").read_text(encoding="utf-8")

    assert _job_ids(text) == {"verify-package", "publish"}
    assert "pull_request:" not in text
    _assert_actions_are_approved(text)
    assert "version: \"0.11.26\"" in text
    assert "uv build --frozen" not in text

    verify = _job(text, "verify-package")
    assert "permissions:\n      contents: read" in verify
    assert "id-token:" not in verify
    for command in (
        "uv lock --check",
        "uv sync --frozen --group ci",
        "ruff check .",
        "pytest -q -p no:cacheprovider",
        "uv build --build-constraints tooling/python-ci/build-requirements.lock.txt --require-hashes",
        "twine check dist/*",
        'if [ "$EXISTS" = "error" ]; then',
    ):
        assert command in verify

    publish = _job(text, "publish")
    assert "needs: verify-package" in publish
    assert "environment:\n      name: pypi" in publish
    assert "permissions:\n      id-token: write" in publish
    assert "actions/download-artifact@" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "checkout@" not in publish
    assert "run:" not in publish
    assert "needs.verify-package.outputs.exists == 'false'" in publish

    assert text.count("id-token: write") == 1


def test_same_shape_unapproved_action_sha_is_rejected() -> None:
    valid_yaml = f"""\
jobs:
  test:
    steps:
      - uses: actions/checkout@{APPROVED_ACTIONS['actions/checkout']}
"""
    mutated = valid_yaml.replace(APPROVED_ACTIONS["actions/checkout"], "0" * 40)

    with pytest.raises(AssertionError, match="unapproved action pin"):
        _assert_actions_are_approved(mutated)


def test_build_backend_is_exact_and_hash_constrained_for_python39() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    constraints = (
        ROOT / "tooling" / "python-ci" / "build-requirements.lock.txt"
    ).read_text(encoding="utf-8")

    assert 'requires = ["hatchling==1.27.0"]' in project
    assert 'dependencies = ["pydantic>=2"]' in project
    pins = set(re.findall(r"(?m)^([a-z0-9-]+)==([^ ;\\]+)", constraints))
    assert pins == {
        ("hatchling", "1.27.0"),
        ("packaging", "26.3"),
        ("pathspec", "1.1.1"),
        ("pluggy", "1.6.0"),
        ("tomli", "2.4.1"),
        ("trove-classifiers", "2026.6.1.19"),
    }
    assert "tomli==2.4.1 ; python_full_version < '3.11'" in constraints
    assert constraints.count("--hash=sha256:") >= len(pins) * 2
