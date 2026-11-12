"""Fails when a committed schema file differs from what the package code generates, so the files
under schema/ and a2ui/ cannot drift from the models.
"""

import json

import pytest

import generate_schemas


@pytest.mark.parametrize("path", sorted(generate_schemas.targets()), ids=lambda p: p.name)
def test_committed_file_matches_generated_output(path):
    expected = generate_schemas.render(generate_schemas.targets()[path]())
    assert path.read_text(encoding="utf-8") == expected, "run scripts/generate_schemas.py"


def test_wire_file_carries_the_package_version():
    import astralprims

    path = next(p for p in generate_schemas.targets() if p.name == "astralprims.wire.json")
    assert json.loads(path.read_text(encoding="utf-8"))["x-astralprims-version"] == astralprims.__version__


def test_check_mode_reports_a_stale_file(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "schema" / "x.json"
    stale.parent.mkdir()
    stale.write_text("{}\n")
    monkeypatch.setattr(generate_schemas, "targets", lambda: {stale: lambda: {"a": 1}})
    monkeypatch.setattr(generate_schemas, "ROOT", tmp_path)
    assert generate_schemas.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().err
    assert stale.read_text() == "{}\n"
    assert generate_schemas.main([]) == 0
    assert json.loads(stale.read_text()) == {"a": 1}
    assert generate_schemas.main(["--check"]) == 0
