"""Renders the README primitive reference (each primitive's class, wire type, and field types
and defaults) from the pydantic models in src/astralprims/primitives.py and rewrites the
marked block in README.md. tests/test_readme_reference.py fails while the committed block
differs from this rendering.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from astralprims import Primitive, primitives

START = "<!-- primitive-reference:start -->"
END = "<!-- primitive-reference:end -->"
README = Path(__file__).resolve().parents[2] / "README.md"
GENERIC_NAMES = {list: "List", dict: "Dict"}


def value_text(value: Any) -> str:
    return json.dumps(value) if isinstance(value, str) else repr(value)


def annotation_text(annotation: Any) -> str:
    if annotation is Any:
        return "Any"
    if annotation is type(None):
        return "None"
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Union:
        members = [arg for arg in args if arg is not type(None)]
        if len(args) == 2 and len(members) == 1:
            return f"Optional[{annotation_text(members[0])}]"
        return f"Union[{', '.join(map(annotation_text, args))}]"
    if origin is Literal:
        return f"Literal[{', '.join(map(value_text, args))}]"
    if origin in GENERIC_NAMES:
        return f"{GENERIC_NAMES[origin]}[{', '.join(map(annotation_text, args))}]"
    if isinstance(annotation, type):
        return annotation.__name__
    raise TypeError(f"no README spelling for annotation {annotation!r}")


def default_text(field: FieldInfo) -> str:
    if field.is_required():
        return "required"
    return value_text(field.get_default(call_default_factory=True, validated_data={}))


def field_text(name: str, field: FieldInfo) -> str:
    wire_key = field.alias or name
    return f"`{name}`" if wire_key == name else f"`{name}` (wire `{wire_key}`)"


def _code(text: str) -> str:
    return f"`{text}`".replace("|", "\\|")


def field_row(name: str, field: FieldInfo) -> List[str]:
    return [field_text(name, field), _code(annotation_text(field.annotation)), _code(default_text(field))]


def _grouped(lead: List[str], fields: Iterable[Tuple[str, FieldInfo]]) -> List[List[str]]:
    return [
        (lead if index == 0 else [""] * len(lead)) + field_row(name, field)
        for index, (name, field) in enumerate(fields)
    ]


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    return ["| " + " | ".join(row) + " |" for row in (header, ["---"] * len(header), *rows)]


def _documented_models() -> Dict[type, List[str]]:
    names: Dict[type, List[str]] = {}
    for name, value in vars(primitives).items():
        if (
            isinstance(value, type)
            and issubclass(value, BaseModel)
            and value.__module__ == primitives.__name__
        ):
            names.setdefault(value, []).append(name)
    return names


def render() -> str:
    common = [(name, field) for name, field in Primitive.model_fields.items() if name != "type"]
    primitive_rows: List[List[str]] = []
    nested_rows: List[List[str]] = []
    for model, names in _documented_models().items():
        aliases = ", ".join(f"`{name}`" for name in names if name != model.__name__)
        label = f"`{model.__name__}`" + (f" (alias {aliases})" if aliases else "")
        if issubclass(model, Primitive):
            wire_type = _code(model.model_fields["type"].default)
            own = [(n, f) for n, f in model.model_fields.items() if n not in Primitive.model_fields]
            primitive_rows += _grouped([label, wire_type], own)
        else:
            nested_rows += _grouped([label], model.model_fields.items())
    return "\n".join(
        [
            START,
            "",
            "### Common fields",
            "",
            *_table(("Field", "Type", "Default"), _grouped([], common)),
            "",
            "### Primitives",
            "",
            *_table(("Class", "Wire type", "Field", "Type", "Default"), primitive_rows),
            "",
            "### Nested models",
            "",
            *_table(("Class", "Field", "Type", "Default"), nested_rows),
            "",
            END,
        ]
    )


def extract(text: str) -> str:
    start, end = text.find(START), text.find(END)
    if text.count(START) != 1 or text.count(END) != 1 or end < start:
        raise ValueError(f"README must contain exactly one {START} ... {END} block")
    return text[start : end + len(END)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the README primitive reference.")
    parser.add_argument("readme", nargs="?", type=Path, default=README)
    readme = parser.parse_args(argv).readme
    raw = readme.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    try:
        current = extract(text)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    with open(readme, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as handle:
        handle.write(text.replace(current, render()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
