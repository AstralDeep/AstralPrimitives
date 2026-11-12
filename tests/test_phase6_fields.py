"""Covers the value-binding, capability, handle, accessibility and provenance fields added to
the primitive models, and proves existing callers and serialization are unchanged by them.
"""

import json

import pytest
from jsonschema import Draft202012Validator

from astralprims import (
    Binding,
    BindingRef,
    Button,
    Handle,
    Image,
    Input,
    Primitive,
    ProgressBar,
    Text,
    wire_schema,
)


def test_new_fields_are_omitted_when_unset():
    assert Button(label="Go", action="go").to_dict() == {
        "type": "button",
        "label": "Go",
        "action": "go",
        "payload": {},
        "variant": "primary",
    }
    assert Text(content="x").to_dict() == {"type": "text", "content": "x", "variant": "body"}


def test_binding_serializes_as_a_bind_object_and_round_trips():
    node = Text(content=Binding(bind=BindingRef(event="ev1", path="/a/0")))
    wire = node.to_dict()
    assert wire["content"] == {"bind": {"event": "ev1", "path": "/a/0"}}
    assert Primitive.from_dict(json.loads(json.dumps(wire))).to_dict() == wire
    Draft202012Validator(wire_schema()).validate(wire)


def test_numeric_fields_accept_a_binding_or_a_number():
    assert ProgressBar(value=0.5).to_dict()["value"] == 0.5
    wire = ProgressBar(value={"bind": {"event": "e", "path": ""}}).to_dict()
    assert wire["value"] == {"bind": {"event": "e", "path": ""}}


def test_bound_text_still_rejects_other_types():
    with pytest.raises(ValueError):
        Text(content=5)
    with pytest.raises(ValueError):
        Text(content={"bind": {"path": "/x"}})


def test_capability_and_handles_serialize_as_handle_objects():
    button = Button(label="Run", capability=Handle(handle="cap-1"), accessible_name="Run", spoken="run it", compact="Run")
    wire = button.to_dict()
    assert wire["capability"] == {"handle": "cap-1"}
    assert (wire["accessible_name"], wire["spoken"], wire["compact"]) == ("Run", "run it", "Run")
    assert Input(capability={"handle": "c"}).to_dict()["capability"] == {"handle": "c"}
    assert Image(source={"handle": "img-1"}, alt="a").to_dict()["source"] == {"handle": "img-1"}
    Draft202012Validator(wire_schema()).validate(wire)


@pytest.mark.parametrize("origin", ["model", "tool", "host", "external"])
def test_provenance_accepts_known_origins(origin):
    assert Text(provenance=origin).to_dict()["provenance"] == origin


def test_provenance_rejects_unknown_origin():
    with pytest.raises(ValueError):
        Text(provenance="user")


def test_handle_requires_a_value():
    with pytest.raises(ValueError):
        Handle(handle="")
