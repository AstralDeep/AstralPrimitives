from __future__ import annotations

import re
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
        "--cov=astralprims --cov-branch --cov-report=xml --cov-fail-under=90",
        "diff-cover coverage.xml --compare-branch origin/main --fail-under=90",
        "uv build --build-constraints tooling/python-ci/build-requirements.lock.txt --require-hashes",
        "twine check dist/*",
        'installed_version == manifest["project"]["version"]',
        'astralprims.__version__ == installed_version',
        'path.as_posix() == "astralprims/py.typed"',
        'Text(content="ci").to_dict() == {',
        '"variant": "body"',
    ):
        assert command in quality
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
