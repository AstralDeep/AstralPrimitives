"""Exercise shared child coercion through every composite primitive and TabItem.
Verify malformed discriminators are rejected and valid model/wire trees keep their shape.
"""

from collections import UserDict, deque

import pytest
from pydantic import ValidationError

from astralprims import (
    ActionGroup,
    Button,
    Card,
    Collapsible,
    Container,
    Grids,
    Primitive,
    TabItem,
    Tabs,
    Text,
    primitive_adapter,
)


CHILD_FIELDS = [
    (Container, "children"),
    (Card, "content"),
    (Grids, "children"),
    (Collapsible, "content"),
    (TabItem, "content"),
    (ActionGroup, "buttons"),
]
COLLECTIONS = [list, tuple, deque, iter]
INVALID_CHILDREN = [
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
]


@pytest.mark.parametrize("model, field", CHILD_FIELDS)
@pytest.mark.parametrize("collection", COLLECTIONS)
@pytest.mark.parametrize("mapping", [dict, UserDict])
@pytest.mark.parametrize("child", INVALID_CHILDREN)
def test_invalid_child_mappings_fail_for_every_supported_collection(
    model,
    field,
    collection,
    mapping,
    child,
):
    with pytest.raises(ValidationError):
        model(**{field: collection([mapping(child)])})


@pytest.mark.parametrize("model, field", CHILD_FIELDS)
@pytest.mark.parametrize("collection", COLLECTIONS)
@pytest.mark.parametrize("mapping", [dict, UserDict])
def test_tagged_mappings_and_existing_models_preserve_exact_wire_shape(
    model,
    field,
    collection,
    mapping,
):
    button = Button(label="go", action="submit", payload={})
    text_wire = {
        "type": "text",
        "content": "hello",
        "variant": "body",
        "class": "intro",
        "css": {},
        "external": "retained",
    }
    instance = model(**{field: collection([mapping(text_wire), button])})
    children = getattr(instance, field)
    assert isinstance(children[0], Text)
    assert children[0].content == "hello"
    assert children[0].attributes == {"external": "retained"}
    assert children[1] is button
    expected = {
        "type": "text",
        "class": "intro",
        "content": "hello",
        "variant": "body",
        "external": "retained",
    }
    assert instance.model_dump()[field] == [expected, button.to_dict()]
    if model is TabItem:
        assert (
            TabItem.model_validate(instance.model_dump()).model_dump()
            == instance.model_dump()
        )
        wire = Tabs(tabs=[instance]).to_dict()
        assert Primitive.from_dict(wire).to_dict() == wire
        assert Tabs.from_dict(wire).to_dict() == wire
        assert primitive_adapter.validate_python(wire).to_dict() == wire
    else:
        wire = instance.to_dict()
        assert Primitive.from_dict(wire).to_dict() == wire
        assert model.from_dict(wire).to_dict() == wire
        assert primitive_adapter.validate_python(wire).to_dict() == wire


@pytest.mark.parametrize("model, field", CHILD_FIELDS)
@pytest.mark.parametrize("value", ["text", b"text", {"type": "text"}, 1, None])
def test_invalid_child_collection_shapes_still_fail(model, field, value):
    with pytest.raises(ValidationError):
        model(**{field: value})


@pytest.mark.parametrize("child", INVALID_CHILDREN)
def test_nested_tree_rejects_invalid_child_on_all_deserialization_paths(child):
    wire = {
        "type": "container",
        "children": [
            {
                "type": "card",
                "content": [
                    {
                        "type": "grid",
                        "children": [
                            {
                                "type": "collapsible",
                                "content": [
                                    {
                                        "type": "tabs",
                                        "tabs": [
                                            {
                                                "content": [
                                                    {
                                                        "type": "action_group",
                                                        "buttons": [child],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    for validate in (
        Container.model_validate,
        Container.from_dict,
        Primitive.from_dict,
        primitive_adapter.validate_python,
    ):
        with pytest.raises(ValidationError):
            validate(wire)


def test_non_child_content_keeps_string_validation():
    assert Text(content="hello").to_dict() == {
        "type": "text",
        "content": "hello",
        "variant": "body",
    }
    for value in ([{"type": "text"}], {"type": "text"}, 1):
        with pytest.raises(ValidationError):
            Text(content=value)


def _raising_children():
    yield {"type": "text", "content": "first"}
    raise RuntimeError("iterator failed")


@pytest.mark.parametrize("model, field", CHILD_FIELDS)
def test_partial_child_iteration_failure_remains_a_validation_error(model, field):
    with pytest.raises(ValidationError, match="child collection cannot be iterated"):
        model(**{field: _raising_children()})


def test_text_rejects_invalid_iterables_without_consuming_them():
    visited = []

    def children():
        visited.append(True)
        yield {"type": "text"}
        raise RuntimeError("must not iterate scalar content")

    with pytest.raises(ValidationError):
        Text(content=children())
    assert visited == []
