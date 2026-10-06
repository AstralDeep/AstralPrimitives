"""Pydantic base for every UI primitive: the type registry plus
to_dict/to_json/from_dict serialization. primitives.py subclasses Primitive;
__init__.py builds the union from the registry.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Dict, Literal, Optional, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_serializer
from pydantic_core import PydanticUndefined

CSS = Dict[str, str]

_REGISTRY: Dict[str, type["Primitive"]] = {}


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _coerce_children(value: Any) -> Any:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        try:
            children = list(value)
        except Exception as error:
            raise ValueError("child collection cannot be iterated") from error
        coerced = []
        for v in children:
            if isinstance(v, Mapping):
                type_name = v.get("type")
                if not isinstance(type_name, str) or not type_name.strip():
                    raise ValueError(
                        "child dictionary is missing required concrete 'type' key (a non-empty string)"
                    )
                coerced.append(Primitive.from_dict(dict(v)))
            else:
                coerced.append(v)
        return coerced
    return value


class SerModel(BaseModel):
    @model_serializer(mode="plain")
    def _serialize(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, field in type(self).model_fields.items():
            value = getattr(self, name)
            if value is None:
                continue
            out[field.alias or name] = _dump(value)
        return out


class PrimitiveTypeCollisionError(ValueError):
    pass


def unregister_primitive(type_name: str) -> Optional[type["Primitive"]]:
    return _REGISTRY.pop(type_name, None)


class Primitive(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: str = "primitive"
    css: Optional[CSS] = None
    id: Optional[str] = None
    class_name: Optional[str] = Field(default=None, alias="class")
    tooltip: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        type_field = cls.model_fields.get("type")
        if type_field is None:
            raise ValueError(f"Primitive subclass {cls.__name__} must define a 'type' field.")

        default_val = type_field.default
        if default_val is PydanticUndefined or default_val is None:
            raise ValueError(
                f"Primitive subclass {cls.__name__} must define a default string for 'type'."
            )
        if not isinstance(default_val, str) or not default_val.strip():
            raise ValueError(
                f"Primitive subclass {cls.__name__} 'type' default must be a non-empty string, got {default_val!r}."
            )

        origin = get_origin(type_field.annotation)
        if origin is Literal:
            allowed = get_args(type_field.annotation)
            if default_val not in allowed:
                raise ValueError(
                    f"Primitive subclass {cls.__name__} default 'type' {default_val!r} does not match Literal choices {allowed!r}."
                )

        wire_type = default_val
        if wire_type != "primitive":
            existing = _REGISTRY.get(wire_type)
            if existing is not None and existing is not cls:
                raise PrimitiveTypeCollisionError(
                    f"Primitive wire type {wire_type!r} is already registered to {existing.__name__}; collision detected for {cls.__name__}."
                )
            _REGISTRY[wire_type] = cls

    # check_fields=False lets one validator serve every subclass
    @field_validator("children", "content", mode="before", check_fields=False)
    @classmethod
    def _coerce_primitive_children(cls, v: Any, info: ValidationInfo) -> Any:
        if cls.model_fields[info.field_name].annotation is str:
            return v
        return _coerce_children(v)

    @model_serializer(mode="plain")
    def _serialize(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"type": self.type}
        for name, field in type(self).model_fields.items():
            if name in ("type", "attributes"):
                continue
            value = getattr(self, name)
            if value is None:
                continue
            if name == "css" and not value:
                continue
            out[field.alias or name] = _dump(value)
        out.update(self.attributes or {})
        return out

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.model_dump(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Primitive":
        if "type" not in data:
            raise ValueError("primitive dict is missing required 'type' key")

        type_name = data["type"]
        target = cls if cls is not Primitive else _REGISTRY.get(type_name)
        if target is None:
            raise ValueError(f"unknown primitive type: {type_name!r}")

        known = set()
        for name, field in target.model_fields.items():
            known.add(name)
            if field.alias:
                known.add(field.alias)

        kwargs: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "type":
                continue
            (kwargs if key in known else extra)[key] = value

        if extra:
            kwargs["attributes"] = {**kwargs.get("attributes", {}), **extra}
        kwargs['type'] = type_name
        return target.model_validate(kwargs)
