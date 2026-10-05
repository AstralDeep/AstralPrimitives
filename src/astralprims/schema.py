"""JSON Schema (draft 2020-12) describing the canonical to_dict() output of the
primitives defined in astralprims.primitives; wire_schema() derives every entry
from the pydantic models at call time. __init__.py re-exports wire_schema as
the public surface, and tests/test_wire_schema.py pins the derived contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from .base import Primitive

_NONE_TYPE = type(None)

_ROOT_DESCRIPTION = (
    "Canonical JSON output of to_dict() and model_dump() for the primitives shipped "
    "by this AstralPrimitives release. Fields set to None are omitted, as is an "
    "empty css block, so nullable properties are absent rather than null. "
    "attributes is a trusted escape hatch merged last into the top-level object: "
    "additional keys are always accepted, but overriding a declared key, including "
    "type, may intentionally produce output outside this baseline schema. Custom "
    "registered primitives are not part of this versioned baseline."
)


def _nullable(annotation: Any) -> bool:
    return get_origin(annotation) is Union and _NONE_TYPE in get_args(annotation)


def _literal_type(value: Any) -> str:
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    raise TypeError(f"unsupported Literal value: {value!r}")


def _annotation_to_schema(annotation: Any, *, omit_none: bool) -> Dict[str, Any]:
    if annotation is Any:
        return {}
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    origin = get_origin(annotation)
    if origin is Union:
        members = get_args(annotation)
        if omit_none and _NONE_TYPE in members:
            members = tuple(m for m in members if m is not _NONE_TYPE)
            if len(members) == 1:
                return _annotation_to_schema(members[0], omit_none=False)
        return {
            "anyOf": [
                {"type": "null"} if member is _NONE_TYPE else _annotation_to_schema(member, omit_none=False)
                for member in members
            ]
        }
    if origin is Literal:
        choices = list(get_args(annotation))
        kinds = {_literal_type(choice) for choice in choices}
        if len(choices) == 1:
            return {"const": choices[0]}
        schema: Dict[str, Any] = {"enum": choices}
        if len(kinds) == 1:
            schema["type"] = kinds.pop()
        return schema
    if origin is list:
        items = get_args(annotation)
        if not items:
            return {"type": "array"}
        return {"type": "array", "items": _annotation_to_schema(items[0], omit_none=False)}
    if origin is dict:
        members = get_args(annotation)
        if not members:
            return {"type": "object"}
        value = _annotation_to_schema(members[1], omit_none=False)
        # {} and True accept identical values; True states the intent.
        return {"type": "object", "additionalProperties": value or True}
    if isinstance(annotation, type):
        if issubclass(annotation, Primitive):
            return {"$ref": "#/$defs/component"}
        if issubclass(annotation, BaseModel):
            return {"$ref": f"#/$defs/{_definition_name(annotation)}"}
    raise TypeError(f"unsupported wire annotation: {annotation!r}")


def _definition_name(model: type) -> str:
    return "".join(
        ("_" + char.lower()) if char.isupper() else char for char in model.__name__
    ).lstrip("_")


def _shipped_models() -> List[type]:
    from . import primitives

    discovered = (
        value
        for value in vars(primitives).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == primitives.__name__
    )
    return list(dict.fromkeys(discovered))


def _referenced_models(models: List[type]) -> set:
    referenced: set = set()

    def collect(annotation: Any) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            referenced.add(annotation)
            return
        for arg in get_args(annotation):
            collect(arg)

    for model in models:
        for field in model.model_fields.values():
            collect(field.annotation)
    return referenced


def _model_definition(model: type) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []
    if issubclass(model, Primitive):
        properties["type"] = {"const": model.model_fields["type"].default}
        required.append("type")
    for name, field in model.model_fields.items():
        if name in ("type", "attributes"):
            continue
        wire_key = field.alias or name
        properties[wire_key] = _annotation_to_schema(field.annotation, omit_none=True)
        if name != "css" and not _nullable(field.annotation):
            required.append(wire_key)
        default = field.get_default(call_default_factory=True, validated_data={})
        if default is not None and default is not PydanticUndefined:
            properties[wire_key]["default"] = default
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": issubclass(model, Primitive),
    }


def wire_schema() -> Dict[str, Any]:
    from astralprims import __version__

    models = _shipped_models()
    primitive_models = sorted(
        (model for model in models if issubclass(model, Primitive)),
        key=lambda model: model.model_fields["type"].default,
    )
    nested_models = sorted(
        (model for model in models if not issubclass(model, Primitive)),
        key=lambda model: model.__name__,
    )
    referenced = _referenced_models(models)
    definitions: Dict[str, Any] = {
        model.model_fields["type"].default: _model_definition(model)
        for model in primitive_models
    }
    for model in nested_models:
        definition = _model_definition(model)
        if model not in referenced:
            definition["description"] = (
                f"Serialized shape of the public {model.__name__} helper model. "
                "No primitive field references it, so this definition documents the "
                "helper without constraining any wire field."
            )
        definitions[_definition_name(model)] = definition
    definitions["component"] = {
        "oneOf": [
            {"$ref": f"#/$defs/{model.model_fields['type'].default}"}
            for model in primitive_models
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AstralPrimitives wire schema",
        "description": _ROOT_DESCRIPTION,
        "x-astralprims-version": __version__,
        "$ref": "#/$defs/component",
        "$defs": definitions,
    }
