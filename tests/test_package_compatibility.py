"""Exercise immutable-base package qualification and version policy using synthetic trees.
These tests isolate release decisions from the candidate's fixtures and version claims.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def release_tree(tmp_path):
    for path in ("src", "tests/fixtures"):
        shutil.copytree(ROOT / path, tmp_path / path)
    for path in ("pyproject.toml", "uv.lock"):
        shutil.copy(ROOT / path, tmp_path / path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Synthetic CI test")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "release baseline")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def test_behavior_changes_require_a_patch_but_headers_do_not():
    from check_package_compatibility import qualify_sources

    original = {
        "__init__.py": '__version__ = "0.11.1"\n__all__ = ["Text"]',
        "primitives.py": '"""Header."""\nclass Text:\n    content: str = ""',
    }
    candidate = dict(
        original,
        **{"primitives.py": '"""New header."""\nclass Text:\n    content: str = ""'},
    )
    assert (
        qualify_sources(original, candidate, "0.11.1", "0.11.1")["required_bump"]
        == "none"
    )
    candidate["primitives.py"] += "\n    def _validate(self):\n        return False"
    with pytest.raises(ValueError, match="patch"):
        qualify_sources(original, candidate, "0.11.1", "0.11.1")
    assert (
        qualify_sources(original, candidate, "0.11.1", "0.11.2")["required_bump"]
        == "patch"
    )


@pytest.mark.parametrize(
    "candidate_source",
    [
        'class Text:\n    content: str = "changed"',
        "class Text:\n    content: int = 0",
        'class Text:\n    renamed: str = ""',
        'class Text:\n    content: str = ""\n    optional: str = ""',
    ],
)
def test_public_field_and_emitted_default_changes_require_a_minor_before_one(
    candidate_source,
):
    from check_package_compatibility import qualify_sources

    original = {
        "__init__.py": '__all__ = ["Text"]',
        "primitives.py": 'class Text:\n    content: str = ""',
    }
    candidate = dict(original, **{"primitives.py": candidate_source})
    with pytest.raises(ValueError, match="minor"):
        qualify_sources(original, candidate, "0.11.1", "0.11.2")
    assert (
        qualify_sources(original, candidate, "0.11.1", "0.12.0")["required_bump"]
        == "minor"
    )


def test_released_exports_and_post_one_breaks_enforce_semver():
    from check_package_compatibility import qualify_sources

    original = {"__init__.py": '__all__ = ["Text", "Grid"]'}
    removed = {"__init__.py": '__all__ = ["Text"]'}
    with pytest.raises(ValueError, match="major"):
        qualify_sources(original, removed, "1.2.3", "1.3.0")
    assert qualify_sources(original, removed, "1.2.3", "2.0.0")["removed_exports"] == [
        "Grid"
    ]
    assert (
        qualify_sources(
            original,
            {"__init__.py": '__all__ = ["Text", "Grid", "New"]'},
            "1.2.3",
            "1.3.0",
        )["required_bump"]
        == "minor"
    )


def test_wire_regression_needs_a_breaking_release_even_when_source_is_unchanged():
    from check_package_compatibility import qualify_sources

    with pytest.raises(ValueError, match="minor"):
        qualify_sources({}, {}, "0.11.1", "0.11.2", wire_changed=True)


@pytest.mark.parametrize("version", ["0.11.1", "0.10.9", "bad", "0.11.2rc1"])
def test_behavior_changes_reject_nonadvancing_or_non_release_versions(version):
    from check_package_compatibility import qualify_sources

    with pytest.raises(ValueError):
        qualify_sources({"x.py": "a = 1"}, {"x.py": "a = 2"}, "0.11.1", version)


def test_immutable_tree_gate_uses_base_fixtures_and_versions(release_tree):
    from check_package_compatibility import qualify_tree

    root, base = release_tree
    decision = qualify_tree(root, base)
    assert decision["status"] == "pass"
    assert decision["required_bump"] == "none"
    assert decision["base_sha"] == decision["fixture_sha"] == base
    assert decision["fixture_cases"] == 7
    (root / "tests/fixtures/released_wire.json").write_text(
        '[{"input":{"type":"text"},"expected":{"spoofed":true}}]'
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "candidate fixture spoof")
    decision = qualify_tree(root, base)
    assert decision["fixture_sha"] == base
    assert decision["wire_changed"] is False
    source = root / "src/astralprims/primitives.py"
    source.write_text(
        source.read_text().replace('variant: str = "body"', 'variant: str = "mutated"')
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "runtime defect")
    with pytest.raises(ValueError, match="minor"):
        qualify_tree(root, base)


def test_initial_fixture_is_verified_against_immutable_base(release_tree):
    from check_package_compatibility import qualify_tree

    root, _ = release_tree
    _git(root, "rm", "tests/fixtures/released_wire.json")
    _git(root, "commit", "-m", "pre-fixture release")
    base = _git(root, "rev-parse", "HEAD")
    (root / "tests/fixtures").mkdir(parents=True)
    shutil.copy(
        ROOT / "tests/fixtures/released_wire.json",
        root / "tests/fixtures/released_wire.json",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "first independently authored fixture")
    assert qualify_tree(root, base)["fixture_sha"] == _git(root, "rev-parse", "HEAD")
    cases = json.loads((root / "tests/fixtures/released_wire.json").read_text())
    cases[0]["expected"]["variant"] = "spoofed"
    (root / "tests/fixtures/released_wire.json").write_text(json.dumps(cases))
    _git(root, "add", ".")
    _git(root, "commit", "-m", "incorrect first fixture")
    with pytest.raises(ValueError, match="immutable base behavior"):
        qualify_tree(root, base)


@pytest.mark.parametrize("sha", ["origin/main", "0" * 40, "f" * 40])
def test_bad_or_missing_base_is_rejected(release_tree, sha):
    from check_package_compatibility import qualify_tree

    with pytest.raises(ValueError):
        qualify_tree(release_tree[0], sha)


def test_dirty_tree_and_empty_fixture_fail_closed(release_tree):
    from check_package_compatibility import qualify_tree

    root, base = release_tree
    (root / "pyproject.toml").write_text('version = "invalid"')
    with pytest.raises(ValueError, match="dirty"):
        qualify_tree(root, base)
    _git(root, "restore", "pyproject.toml")
    (root / "tests/fixtures/released_wire.json").write_text("[]")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "empty fixture baseline")
    with pytest.raises(ValueError, match="empty or malformed"):
        qualify_tree(root, _git(root, "rev-parse", "HEAD"))


@pytest.mark.parametrize(
    "manifest, runtime, lock",
    [
        (
            'version = "0.11.1"',
            '__version__="0.11.2"',
            '[[package]]\nname = "astralprims"\nversion = "0.11.1"',
        ),
        (
            'version = "0.11.1"',
            '__version__="0.11.1"',
            '[[package]]\nname = "astralprims"\nversion = "0.11.2"',
        ),
        ("no version", '__version__="0.11.1"', ""),
    ],
)
def test_disagreement_or_missing_version_is_rejected(manifest, runtime, lock):
    from check_package_compatibility import _check_versions

    with pytest.raises(ValueError):
        _check_versions({"__init__.py": runtime}, manifest, lock)


def test_probe_errors_empty_sources_and_cli_status(release_tree, monkeypatch, capsys):
    from check_package_compatibility import _probe, _tree, main

    root, base = release_tree
    with pytest.raises(ValueError, match="probe failed"):
        _probe({"__init__.py": 'raise ImportError("synthetic")'}, [])
    monkeypatch.chdir(root)
    assert main(["--base-sha", base]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    assert main(["--base-sha", "bad"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    _git(root, "rm", "-r", "src")
    _git(root, "commit", "-m", "removed package")
    with pytest.raises(ValueError, match="source tree is empty"):
        _tree(root, _git(root, "rev-parse", "HEAD"))


def test_source_deletion_signatures_and_version_only_changes():
    from check_package_compatibility import qualify_sources

    assert (
        qualify_sources({"x.py": "a = 1"}, {}, "0.11.1", "0.11.2")["required_bump"]
        == "patch"
    )
    assert (
        qualify_sources(
            {"__init__.py": '__version__="0.11.1"'},
            {"__init__.py": '__version__="0.11.2"'},
            "0.11.1",
            "0.11.2",
        )["required_bump"]
        == "none"
    )
    with pytest.raises(ValueError, match="minor"):
        qualify_sources(
            {"__init__.py": '__all__=["run"]\ndef run(a):\n    return a'},
            {"__init__.py": '__all__=["run"]\ndef run():\n    return None'},
            "0.11.1",
            "0.11.2",
        )


@pytest.mark.parametrize(
    "before, after",
    [
        ('def run():\n    __version__ = "old"', 'def run():\n    __version__ = "new"'),
        ('__version__ = "0.11.1"', 'alias = __version__ = "0.11.1"'),
    ],
)
def test_runtime_version_assignments_are_behavior_changes(before, after):
    from check_package_compatibility import qualify_sources

    with pytest.raises(ValueError, match="patch"):
        qualify_sources(
            {"x.py": before},
            {"x.py": after},
            "0.11.1",
            "0.11.1",
        )


def test_released_alias_target_changes_require_a_breaking_version():
    from check_package_compatibility import qualify_sources

    with pytest.raises(ValueError, match="minor"):
        qualify_sources(
            {"__init__.py": '__all__ = ["Grid"]', "primitives.py": "Grid = Grids"},
            {"__init__.py": '__all__ = ["Grid"]', "primitives.py": "Grid = Card"},
            "0.11.1",
            "0.11.2",
        )
