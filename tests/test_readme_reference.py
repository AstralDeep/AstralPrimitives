"""Keeps README.md's primitive documentation exact: the committed reference block must equal
what tooling/python-ci/primitive_reference.py renders from the pydantic models, and every
wire type in the astralprims registry must be documented in the reference and the index.
"""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import pytest
from pydantic import BaseModel, Field

import primitive_reference as reference
from astralprims.base import _REGISTRY

README = Path(__file__).resolve().parents[1] / "README.md"
BUILT_IN = sorted(
    (wire_type, model)
    for wire_type, model in _REGISTRY.items()
    if model.__module__.startswith("astralprims.")
)


class Sample(BaseModel):
    required: int
    piped: str = "a|b"
    items: List[int] = Field(default_factory=list)
    renamed: Optional[str] = Field(default=None, alias="wire")


def test_readme_reference_matches_the_primitive_models() -> None:
    assert reference.extract(README.read_text(encoding="utf-8")) == reference.render()


@pytest.mark.parametrize("wire_type, model", BUILT_IN, ids=[wire for wire, _ in BUILT_IN])
def test_every_registered_primitive_is_documented(wire_type: str, model: type) -> None:
    text = README.read_text(encoding="utf-8")
    block = reference.extract(text)
    index = text.partition("## Built-in primitives")[2].partition("\n#")[0]

    assert re.search(
        rf"(?m)^\| `{re.escape(model.__name__)}`[^|]* \| `{re.escape(wire_type)}` \|", block
    ), f"README primitive reference is missing wire type {wire_type!r}"
    assert f"`{model.__name__}`" in index, f"README primitive index is missing {model.__name__}"


@pytest.mark.parametrize(
    "annotation, text",
    [
        (Any, "Any"),
        (type(None), "None"),
        (int, "int"),
        (Optional[str], "Optional[str]"),
        (Union[int, str], "Union[int, str]"),
        (Union[int, str, None], "Union[int, str, None]"),
        (List[Dict[str, Any]], "List[Dict[str, Any]]"),
        (Literal["start", 2], 'Literal["start", 2]'),
    ],
)
def test_annotations_render_in_typing_spelling(annotation: Any, text: str) -> None:
    assert reference.annotation_text(annotation) == text


def test_annotations_without_a_spelling_are_rejected() -> None:
    with pytest.raises(TypeError, match="no README spelling"):
        reference.annotation_text("List[int]")


def test_field_rows_show_wire_keys_defaults_and_escaped_pipes() -> None:
    fields = Sample.model_fields

    assert reference.field_row("required", fields["required"]) == ["`required`", "`int`", "`required`"]
    assert reference.field_row("piped", fields["piped"]) == ["`piped`", "`str`", '`"a\\|b"`']
    assert reference.field_row("items", fields["items"]) == ["`items`", "`List[int]`", "`[]`"]
    assert reference.field_row("renamed", fields["renamed"]) == [
        "`renamed` (wire `wire`)",
        "`Optional[str]`",
        "`None`",
    ]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_main_rewrites_only_the_marked_block_and_keeps_line_endings(
    tmp_path: Path, newline: str
) -> None:
    readme = tmp_path / "README.md"
    before = f"# Title\n\n{reference.START}\nstale\n{reference.END}\n\nTail\n"
    readme.write_bytes(before.replace("\n", newline).encode("utf-8"))

    assert reference.main([str(readme)]) == 0

    expected = f"# Title\n\n{reference.render()}\n\nTail\n".replace("\n", newline)
    assert readme.read_bytes().decode("utf-8") == expected


@pytest.mark.parametrize(
    "text",
    [
        "no markers\n",
        f"{reference.END}\n{reference.START}\n",
        f"{reference.START}\n{reference.START}\n{reference.END}\n",
        f"{reference.START}\n{reference.END}\n{reference.END}\n",
    ],
)
def test_main_refuses_a_readme_without_exactly_one_marked_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(text, encoding="utf-8")

    assert reference.main([str(readme)]) == 1
    assert readme.read_text(encoding="utf-8") == text
    assert "must contain exactly one" in capsys.readouterr().err


def test_the_script_entry_point_regenerates_the_given_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"{reference.START}\n{reference.END}\n", encoding="utf-8")
    script = Path(reference.__file__)
    monkeypatch.setattr(sys, "argv", [str(script), str(readme)])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(script), run_name="__main__")

    assert exit_info.value.code == 0
    assert readme.read_text(encoding="utf-8") == f"{reference.render()}\n"
