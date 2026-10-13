"""Exercise fluent child validation and atomic mutations in primitives.py.
Check constructor parity, concrete child identities and serialized tree round trips.
"""

import json
from collections import UserDict
from types import MappingProxyType

import pytest

from astralprims import Button, Card, Container, Grid, Grids, Primitive, Text, primitive_adapter


COMPOSITES = [(Container, "children"), (Card, "content"), (Grids, "children")]
INVALID_SCALARS = ["oops", b"oops", bytearray(b"oops"), 1, 1.5, True, None, [], ()]
INVALID_MAPPINGS = [
    {"content": "untagged"},
    {"type": ""},
    {"type": "   "},
    {"type": None},
    {"type": 1},
    {"type": True},
    {"type": ["text"]},
    {"type": {"text": True}},
    {"type": "unknown"},
    {"type": "primitive"},
    {"type": "text", "content": []},
    {"type": "container", "children": [{"content": "untagged"}]},
]


@pytest.mark.parametrize(
    "model, field, expected",
    [
        (Container, "children", {"type": "container", "children": []}),
        (Card, "content", {"type": "card", "title": "", "content": [], "variant": "default"}),
        (Grids, "children", {"type": "grid", "columns": 2, "children": [], "gap": 20}),
    ],
)
def test_empty_add_is_chainable_and_preserves_exact_defaults(model, field, expected):
    instance = model()
    collection = getattr(instance, field)
    assert instance.add() is instance
    assert getattr(instance, field) is collection
    assert instance.to_dict() == expected


@pytest.mark.parametrize("model, field", COMPOSITES)
def test_add_preserves_concrete_models_identity_order_and_chainability(model, field):
    existing = Text(content="existing")
    instance = model(**{field: [existing]})
    collection = getattr(instance, field)
    text = Text(content="added", class_name="intro", css={})
    button = Button(label="go", action="submit", payload={})

    assert instance.add(text).add(button).add() is instance
    assert getattr(instance, field) is collection
    assert collection[0] is existing
    assert collection[1] is text
    assert collection[2] is button
    assert instance.to_dict()[field] == [
        {"type": "text", "content": "existing", "variant": "body"},
        {"type": "text", "class": "intro", "content": "added", "variant": "body"},
        {"type": "button", "label": "go", "action": "submit", "payload": {}, "variant": "primary"},
    ]


@pytest.mark.parametrize("model, field", COMPOSITES)
@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
def test_tagged_mappings_follow_constructor_policy_and_round_trip(model, field, mapping):
    nested_wire = {
        "type": "card",
        "content": [{"type": "text", "content": "nested", "class": "intro", "css": {}}],
        "external": "retained",
        "attributes": {"title": "trusted"},
    }
    button = Button(label="go")
    instance = model()
    assert instance.add(mapping(nested_wire), button) is instance
    collection = getattr(instance, field)
    assert isinstance(collection[0], Card)
    assert isinstance(collection[0].content[0], Text)
    assert collection[1] is button
    assert instance.to_dict()[field][0] == {
        "type": "card",
        "title": "trusted",
        "content": [{"type": "text", "class": "intro", "content": "nested", "variant": "body"}],
        "variant": "default",
        "external": "retained",
    }
    constructed = model(**{field: [mapping(nested_wire), button]})
    wire = instance.to_dict()
    assert wire == constructed.to_dict()
    assert list(wire)[0] == "type"
    assert instance.model_dump() == wire
    assert json.loads(instance.to_json()) == wire
    assert Primitive.from_dict(wire).to_dict() == wire
    assert model.from_dict(wire).to_dict() == wire
    assert primitive_adapter.validate_python(wire).to_dict() == wire


@pytest.mark.parametrize("model, field", COMPOSITES)
@pytest.mark.parametrize("invalid", INVALID_SCALARS)
@pytest.mark.parametrize("mixed", [False, True])
def test_scalar_failure_leaves_existing_collection_and_models_unchanged(model, field, invalid, mixed):
    existing = Text(content="existing")
    instance = model(**{field: [existing]})
    collection = getattr(instance, field)
    wire = instance.to_dict()
    additions = (Text(content="valid"), invalid, Button(label="later")) if mixed else (invalid,)

    with pytest.raises(ValueError):
        instance.add(*additions)

    assert getattr(instance, field) is collection
    assert len(collection) == 1
    assert collection[0] is existing
    assert instance.to_dict() == wire


@pytest.mark.parametrize("model, field", COMPOSITES)
@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize("invalid", INVALID_MAPPINGS)
def test_invalid_mapping_after_valid_siblings_fails_atomically(model, field, mapping, invalid):
    existing = Text(content="existing")
    instance = model(**{field: [existing]})
    collection = getattr(instance, field)
    wire = instance.to_dict()

    with pytest.raises(ValueError):
        instance.add(Text(content="valid"), {"type": "button", "label": "valid"}, mapping(invalid))

    assert getattr(instance, field) is collection
    assert len(collection) == 1
    assert collection[0] is existing
    assert instance.to_dict() == wire


@pytest.mark.parametrize("model, field", COMPOSITES)
def test_mapping_lookup_failure_does_not_commit_previous_valid_children(model, field):
    class FailingMapping(UserDict):
        def get(self, key, default=None):
            raise ValueError("child mapping lookup failed")

    instance = model(**{field: [Text(content="existing")]})
    collection = getattr(instance, field)
    wire = instance.to_dict()

    with pytest.raises(ValueError, match="child mapping lookup failed"):
        instance.add({"type": "text", "content": "valid"}, FailingMapping({"type": "text"}))

    assert getattr(instance, field) is collection
    assert instance.to_dict() == wire


def test_grid_alias_retains_fluent_add_validation_and_round_trip():
    grid = Grid().add(Text(content="existing"))
    collection = grid.children
    wire = grid.to_dict()

    with pytest.raises(ValueError):
        grid.add({"type": "button", "label": "valid"}, "invalid")

    assert grid.children is collection
    assert grid.to_dict() == wire
    assert grid.add({"type": "text", "content": "added"}) is grid
    assert isinstance(grid.children[1], Text)
    assert isinstance(Primitive.from_dict(grid.to_dict()), Grid)
    assert primitive_adapter.validate_python(grid.to_dict()).to_dict() == grid.to_dict()
