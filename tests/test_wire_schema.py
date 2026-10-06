"""Tests for astralprims.wire_schema, the derived baseline JSON Schema for serialized
primitive output. They pin schema well-formedness, per-type round-trips against
emitted payloads, and the trusted-attributes escape-hatch semantics documented in
README.md.
"""

from typing import Any, Dict, List, Literal, Optional, Union, get_args, get_origin

import pytest
from jsonschema import Draft202012Validator, ValidationError
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

import astralprims
from astralprims import (
    ActionGroup,
    Button,
    Card,
    ChartDataset,
    ChatHistory,
    Container,
    Gauge,
    Grid,
    Grids,
    Image,
    List_,
    ParamPicker,
    PieChart,
    Primitive,
    ProgressBar,
    StatGroup,
    Table,
    Tabs,
    TabItem,
    Text,
    unregister_primitive,
    wire_schema,
)
from astralprims.base import _REGISTRY
from astralprims.schema import _annotation_to_schema

NONE_TYPE = type(None)


def _nullable(annotation: Any) -> bool:
    return get_origin(annotation) is Union and NONE_TYPE in get_args(annotation)


def _shipped_classes() -> list:
    from astralprims import primitives

    return sorted(
        (
            value
            for value in vars(primitives).values()
            if isinstance(value, type)
            and issubclass(value, BaseModel)
            and value.__module__ == primitives.__name__
        ),
        key=lambda cls: cls.__name__,
    )


_SHIPPED = _shipped_classes()
_PRIMITIVE_MODELS = sorted(
    (cls for cls in _SHIPPED if issubclass(cls, Primitive)),
    key=lambda cls: cls.model_fields["type"].default,
)
_NESTED_MODELS = [cls for cls in _SHIPPED if not issubclass(cls, Primitive)]
_NULLABLE_CASES = [
    (model, name)
    for model in _SHIPPED
    for name, field in model.model_fields.items()
    if name not in ("type", "attributes") and _nullable(field.annotation)
]


def _definition_name(model: type) -> str:
    if issubclass(model, Primitive):
        return model.model_fields["type"].default
    return "".join(
        ("_" + char.lower()) if char.isupper() else char for char in model.__name__
    ).lstrip("_")


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(wire_schema())


def test_version_metadata_matches_the_package():
    assert wire_schema()["x-astralprims-version"] == astralprims.__version__


def test_root_describes_the_baseline_and_the_escape_hatch():
    description = wire_schema()["description"]
    assert "$ref" not in description
    assert wire_schema()["$ref"] == "#/$defs/component"
    for marker in ("None", "css", "attributes", "type"):
        assert marker in description


def test_defs_cover_exactly_the_shipped_wire_types():
    schema = wire_schema()
    shipped_wire_types = {
        cls.model_fields["type"].default for cls in _PRIMITIVE_MODELS
    }
    registered = {
        wire_type
        for wire_type, cls in _REGISTRY.items()
        if cls.__module__ == astralprims.primitives.__name__
    }
    assert shipped_wire_types == registered
    assert set(schema["$defs"]) == shipped_wire_types | {
        "component",
        "tab_item",
        "chart_dataset",
    }


def test_component_union_references_every_wire_type():
    schema = wire_schema()
    refs = {entry["$ref"] for entry in schema["$defs"]["component"]["oneOf"]}
    wire_types = set(schema["$defs"]) - {"component", "tab_item", "chart_dataset"}
    assert refs == {f"#/$defs/{wire_type}" for wire_type in wire_types}


@pytest.mark.parametrize("model", _PRIMITIVE_MODELS, ids=lambda model: model.__name__)
def test_default_payload_validates_against_root_and_type_definition(model):
    schema = wire_schema()
    payload = model().to_dict()
    Draft202012Validator(schema).validate(payload)
    Draft202012Validator(schema["$defs"][_definition_name(model)]).validate(payload)


def test_every_field_is_described_according_to_the_serializer():
    schema = wire_schema()
    for model in _SHIPPED:
        definition = schema["$defs"][_definition_name(model)]
        properties = definition["properties"]
        required = set(definition.get("required", []))
        for name, field in model.model_fields.items():
            wire_key = field.alias or name
            if name == "attributes":
                assert wire_key not in properties
                continue
            assert wire_key in properties
            if name == "type":
                assert properties["type"] == {"const": field.default}
                assert "type" in required
                continue
            expected_required = name != "css" and not _nullable(field.annotation)
            assert (wire_key in required) == expected_required, wire_key
            default = field.get_default(call_default_factory=True)
            if default is None or default is PydanticUndefined:
                assert "default" not in properties[wire_key], wire_key
            else:
                assert properties[wire_key]["default"] == default, wire_key
        if issubclass(model, Primitive):
            assert definition["additionalProperties"] is True
        else:
            assert definition["additionalProperties"] is False


def test_button_required_fields_match_the_wire_contract():
    assert set(wire_schema()["$defs"]["button"]["required"]) == {
        "type",
        "label",
        "action",
        "payload",
        "variant",
    }


def test_nullable_field_with_emitted_default_is_annotated_but_not_required():
    schema = wire_schema()
    chat_history = schema["$defs"]["chat_history"]
    assert chat_history["properties"]["title"]["default"] == "Recent chats"
    assert "title" not in chat_history["required"]
    with_title = ChatHistory().to_dict()
    assert with_title["title"] == "Recent chats"
    without_title = ChatHistory(title=None).to_dict()
    assert "title" not in without_title
    validator = Draft202012Validator(schema)
    validator.validate(with_title)
    validator.validate(without_title)


def test_class_alias_and_grid_alias_follow_the_serializer():
    schema = wire_schema()
    button = schema["$defs"]["button"]["properties"]
    assert "class" in button
    assert "class_name" not in button
    payload = Button(class_name="primary").to_dict()
    assert payload["class"] == "primary"
    Draft202012Validator(schema).validate(payload)
    assert "grid" in schema["$defs"]
    assert "grids" not in schema["$defs"]
    assert Grid is Grids


def test_empty_css_is_omitted_and_css_is_never_required():
    schema = wire_schema()
    validator = Draft202012Validator(schema)
    for model in _PRIMITIVE_MODELS:
        payload = model(css={}).to_dict()
        assert "css" not in payload
        validator.validate(payload)
        assert "css" not in schema["$defs"][_definition_name(model)]["required"]


@pytest.mark.parametrize(
    "model,name", _NULLABLE_CASES, ids=lambda value: getattr(value, "__name__", value)
)
def test_nullable_field_omitted_from_wire_still_validates(model, name):
    schema = wire_schema()
    payload = model(**{name: None}).model_dump()
    wire_key = model.model_fields[name].alias or name
    assert wire_key not in payload
    Draft202012Validator(schema["$defs"][_definition_name(model)]).validate(payload)
    if issubclass(model, Primitive):
        Draft202012Validator(schema).validate(payload)


@pytest.mark.parametrize(
    "model,name", _NULLABLE_CASES, ids=lambda value: getattr(value, "__name__", value)
)
def test_explicit_null_for_omittable_fields_is_rejected(model, name):
    schema = wire_schema()
    payload = model(**{name: None}).model_dump()
    wire_key = model.model_fields[name].alias or name
    payload[wire_key] = None
    definition = schema["$defs"][_definition_name(model)]
    with pytest.raises(ValidationError):
        Draft202012Validator(definition).validate(payload)
    if issubclass(model, Primitive):
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(payload)


def test_nested_compositions_validate_against_the_root_schema():
    validator = Draft202012Validator(wire_schema())
    page = Container(css={"display": "flex"}, direction="column").add(
        Text(content="Welcome", variant="h1"),
        Card(title="Sign up").add(
            Text(content="Enter your details below."),
            Button(label="Get started", action="signup"),
        ),
    )
    validator.validate(page.to_dict())
    validator.validate(
        Tabs(
            tabs=[
                TabItem(label="One", content=[Text(content="a")]),
                TabItem(label="Two", value="t2"),
            ]
        ).to_dict()
    )
    validator.validate(
        ActionGroup(
            label="Actions",
            align="end",
            buttons=[
                Button(label="Save", action="save"),
                Button(label="Export", action="export", variant="secondary"),
            ],
        ).to_dict()
    )
    validator.validate(List_(items=["plain", {"structured": True}]).to_dict())
    validator.validate(
        Table(headers=["h"], rows=[["text", 1, True, 0.5, {"nested": [1]}, None]]).to_dict()
    )
    validator.validate(
        StatGroup(title="week", items=[{"label": "requests", "value": "1,284"}]).to_dict()
    )
    validator.validate(
        Gauge(label="humidity", value=0.62, thresholds=[{"at": 0.8, "variant": "warning"}]).to_dict()
    )
    validator.validate(ParamPicker(fields=[{"name": "region"}]).to_dict())
    validator.validate(PieChart(labels=["a"], data=[0.25]).to_dict())
    validator.validate(ProgressBar(value=0.5).to_dict())
    validator.validate(Image(url="https://example.com/i.png", alt="an image").to_dict())


def test_nested_container_nulls_stay_valid_while_field_level_nulls_are_rejected():
    validator = Draft202012Validator(wire_schema())
    validator.validate(
        Table(headers=["h"], rows=[["text", None, {"nested": None}]]).to_dict()
    )
    with pytest.raises(ValidationError):
        validator.validate({"type": "chat_history", "title": None, "items": []})


def test_baseline_rejects_wrong_types_missing_fields_and_unknown_discriminants():
    validator = Draft202012Validator(wire_schema())
    with pytest.raises(ValidationError):
        validator.validate({"type": "text", "content": 5, "variant": "body"})
    with pytest.raises(ValidationError):
        validator.validate({"type": "text"})
    with pytest.raises(ValidationError):
        validator.validate({"type": "nonsense"})


def test_attributes_additive_keys_pass_but_overrides_escape_the_baseline():
    validator = Draft202012Validator(wire_schema())
    validator.validate(
        Button(label="x", attributes={"tracking": "abc", "retries": 2}).to_dict()
    )
    overridden = Button(label="x", attributes={"label": 123}).to_dict()
    assert overridden["label"] == 123
    with pytest.raises(ValidationError):
        validator.validate(overridden)
    retyped = Button(label="x", attributes={"type": "mystery"}).to_dict()
    assert retyped["type"] == "mystery"
    with pytest.raises(ValidationError):
        validator.validate(retyped)


def test_chart_dataset_def_is_a_documented_helper_not_a_datasets_contract():
    schema = wire_schema()
    definition = schema["$defs"]["chart_dataset"]
    assert "ChartDataset" in definition["description"]
    Draft202012Validator(definition).validate(ChartDataset(label="x", data=[1.0]).model_dump())
    for wire_type in ("bar_chart", "line_chart", "radar_chart"):
        items = schema["$defs"][wire_type]["properties"]["datasets"]["items"]
        assert items == {"type": "object", "additionalProperties": True}


def test_nested_model_defs_reject_unknown_keys():
    chart = Draft202012Validator(wire_schema()["$defs"]["chart_dataset"])
    with pytest.raises(ValidationError):
        chart.validate({"label": "x", "data": [], "boom": 1})
    tab = Draft202012Validator(wire_schema()["$defs"]["tab_item"])
    with pytest.raises(ValidationError):
        tab.validate({"label": "x", "content": [], "extra": True})


def test_mapper_omits_none_only_at_field_level():
    assert _annotation_to_schema(Optional[str], omit_none=True) == {"type": "string"}
    assert _annotation_to_schema(Union[str, NONE_TYPE], omit_none=False) == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    listed = _annotation_to_schema(List[Optional[str]], omit_none=True)
    assert listed == {
        "type": "array",
        "items": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }


def test_mapper_handles_component_refs_literals_and_unknown_annotations():
    assert _annotation_to_schema(Primitive, omit_none=False) == {"$ref": "#/$defs/component"}
    assert _annotation_to_schema(TabItem, omit_none=False) == {"$ref": "#/$defs/tab_item"}
    assert _annotation_to_schema(Literal["a"], omit_none=False) == {"const": "a"}
    assert _annotation_to_schema(Literal[1, 2], omit_none=False) == {
        "type": "integer",
        "enum": [1, 2],
    }
    assert _annotation_to_schema(Dict[str, int], omit_none=False) == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }
    with pytest.raises(TypeError):
        _annotation_to_schema(set, omit_none=False)


def test_mapper_literals_cover_json_scalar_kinds_and_bare_containers():
    assert _annotation_to_schema(Literal["a", "b"], omit_none=False) == {
        "type": "string",
        "enum": ["a", "b"],
    }
    assert _annotation_to_schema(Literal[True, False], omit_none=False) == {
        "type": "boolean",
        "enum": [True, False],
    }
    assert _annotation_to_schema(Literal[0.5, 1.5], omit_none=False) == {
        "type": "number",
        "enum": [0.5, 1.5],
    }
    assert _annotation_to_schema(List, omit_none=False) == {"type": "array"}
    assert _annotation_to_schema(Dict, omit_none=False) == {"type": "object"}
    with pytest.raises(TypeError):
        _annotation_to_schema(Literal[b"raw"], omit_none=False)


def test_repeated_calls_are_equal_but_independent():
    first = wire_schema()
    second = wire_schema()
    assert first == second
    first["$defs"]["button"]["properties"]["label"]["default"] = "mutated"
    assert second["$defs"]["button"]["properties"]["label"]["default"] == ""


def test_custom_primitive_registration_does_not_change_the_baseline():
    baseline = wire_schema()

    class Ribbon(Primitive):
        type: Literal["ribbon"] = "ribbon"
        label: str = ""

    try:
        assert wire_schema() == baseline
    finally:
        unregister_primitive("ribbon")
