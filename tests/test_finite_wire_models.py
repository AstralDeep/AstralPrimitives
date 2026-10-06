"""Verify finite-number checks after models and dataclasses expand into primitive wire data.
These regressions exercise the shared base serializer and its public input/output APIs.
"""

import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, field_serializer

from astralprims import Button, Container, Primitive, primitive_adapter


class PayloadModel(BaseModel):
    number: float


@dataclass
class PayloadDataclass:
    number: float


class SerializedPayload(BaseModel):
    number: float

    @field_serializer("number")
    def serialize_number(self, value: float) -> float:
        return float("nan")


class CustomDumpPayload(BaseModel):
    number: float

    def model_dump(self, **kwargs):
        return {"wire_number": self.number}


class MappingPayloadModel(BaseModel):
    values: dict


@dataclass
class MappingPayloadDataclass:
    values: dict


@pytest.mark.parametrize("factory", [PayloadModel, PayloadDataclass])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
@pytest.mark.parametrize("method", ["to_dict", "model_dump", "to_json"])
def test_non_finite_expanded_values_are_rejected(factory, number, field, method):
    primitive = Button(**{field: {"nested": [factory(number=number)]}})

    with pytest.raises(ValueError, match=rf"{field}\.nested\[0\]\.number"):
        getattr(primitive, method)()


@pytest.mark.parametrize("factory", [PayloadModel, PayloadDataclass])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_from_dict_rejects_non_finite_expanded_values(factory, number, field):
    wire = {"type": "button", field: {"nested": [factory(number=number)]}}

    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.nested\[0\]\.number"):
        Primitive.from_dict(wire)
    with pytest.raises(ValueError, match=rf"{field}\.nested\[0\]\.number"):
        primitive_adapter.validate_python(wire).to_dict()


@pytest.mark.parametrize("factory", [PayloadModel, PayloadDataclass])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_finite_expanded_values_keep_the_existing_wire_shape(factory, field):
    primitive = Button(
        label="declared",
        class_name="alias",
        css={},
        attributes={"label": "trusted"},
    )
    getattr(primitive, field)["nested"] = [factory(number=-2.5)]
    wire = primitive.to_dict()

    assert wire["label"] == "trusted"
    assert wire["class"] == "alias"
    assert "css" not in wire
    assert "attributes" not in wire
    assert "tooltip" not in wire
    assert list(wire)[0] == "type"
    nested = wire["payload"]["nested"] if field == "payload" else wire["nested"]
    assert nested == [{"number": -2.5}]
    assert primitive.model_dump() == wire
    assert json.loads(json.dumps(wire, allow_nan=False)) == wire
    assert json.loads(primitive.to_json()) == wire
    assert Primitive.from_dict(wire).to_dict() == wire
    assert primitive_adapter.validate_python(
        {
            "type": "button",
            "label": primitive.label,
            "class": primitive.class_name,
            "css": primitive.css,
            "payload": primitive.payload,
            "attributes": primitive.attributes,
        }
    ).to_dict() == wire
    assert Container(children=[primitive]).to_dict()["children"] == [wire]


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_model_serializer_cannot_introduce_non_finite_values(field):
    primitive = Button(**{field: {"nested": SerializedPayload(number=1)}})

    with pytest.raises(ValueError, match=rf"{field}\.nested\.number"):
        primitive.to_dict()
    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.nested\.number"):
        Primitive.from_dict({"type": "button", field: {"nested": SerializedPayload(number=1)}})


def test_finite_custom_dump_dispatch_is_preserved():
    model = CustomDumpPayload(number=2.5)
    primitive = Button(payload={"nested": [model]}, attributes={"nested": model})

    assert primitive.to_dict()["payload"] == {"nested": [{"wire_number": 2.5}]}
    assert primitive.to_dict()["nested"] == {"number": 2.5}
    assert json.loads(primitive.to_json()) == primitive.to_dict()


@pytest.mark.parametrize("collection", [tuple, set, frozenset])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_collection_values_are_rejected(collection, number):
    primitive = Button(attributes={"nested": collection([number])})

    with pytest.raises(ValueError, match=r"attributes\.nested\[0\]"):
        primitive.to_dict()
    with pytest.raises(ValueError, match=r"wire_payload\.attributes\.nested\[0\]"):
        Primitive.from_dict({"type": "button", "attributes": {"nested": collection([number])}})


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
@pytest.mark.parametrize("method", ["to_dict", "model_dump", "to_json"])
def test_non_finite_numeric_mapping_keys_are_rejected(number, field, method):
    primitive = Button(**{field: {"nested": {number: 1}}})

    with pytest.raises(ValueError, match=rf"{field}\.nested\.<key>"):
        getattr(primitive, method)()


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_from_dict_rejects_non_finite_numeric_mapping_keys(number, field):
    wire = {"type": "button", field: {"nested": {number: 1}}}

    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.nested\.<key>"):
        Primitive.from_dict(wire)
    with pytest.raises(ValueError, match=rf"{field}\.nested\.<key>"):
        primitive_adapter.validate_python(wire).to_dict()


@pytest.mark.parametrize("factory", [MappingPayloadModel, MappingPayloadDataclass])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_expanded_non_finite_numeric_mapping_keys_are_rejected(factory, number, field):
    value = factory(values={number: 1})
    primitive = Button(**{field: {"nested": value}})

    with pytest.raises(ValueError, match=rf"{field}\.nested\.values\.<key>"):
        primitive.to_dict()
    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.nested\.values\.<key>"):
        Primitive.from_dict({"type": "button", field: {"nested": value}})


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_finite_numeric_mapping_keys_keep_existing_wire_representation(field):
    mapping = {2: "integer", 2.5: "float", "tag": "string"}
    primitive = Button(**{field: {"nested": mapping}})
    wire = primitive.to_dict()
    nested = wire["payload"]["nested"] if field == "payload" else wire["nested"]

    assert nested == mapping
    assert [type(key) for key in nested] == [int, float, str]
    assert Primitive.from_dict(wire).to_dict() == wire
    decoded = json.loads(primitive.to_json())
    decoded_nested = decoded["payload"]["nested"] if field == "payload" else decoded["nested"]
    assert decoded_nested == {"2": "integer", "2.5": "float", "tag": "string"}
