"""Pydantic base for every UI primitive: the type registry plus
to_dict/to_json/from_dict serialization. primitives.py subclasses Primitive;
__init__.py builds the union from the registry.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, Literal, Optional, get_args, get_origin
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_serializer,
)
from pydantic_core import PydanticUndefined

CSS = Dict[str, str]

_REGISTRY: Dict[str, type["Primitive"]] = {}
_WIRE_ADAPTER = TypeAdapter(Any)


def _wire_target(path: str) -> str:
    return f" at field {path!r}" if path else ""


def _assert_finite_float(value: float, path: str) -> None:
    if math.isnan(value):
        raise ValueError(f"Non-finite numeric value NaN is not allowed in wire representation{_wire_target(path)}.")
    if math.isinf(value):
        sign = "Infinity" if value > 0 else "-Infinity"
        raise ValueError(f"Non-finite numeric value {sign} is not allowed in wire representation{_wire_target(path)}.")


def _dump_key(key: Any, path: str) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if key is None:
        return "null"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, float):
        _assert_finite_float(key, path)
        return str(key)
    raise ValueError(
        f"Unsupported mapping key of type {type(key).__name__!r} is not allowed in wire representation{_wire_target(path)}."
    )


def _dump_scalar(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        _assert_finite_float(value, path)
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"Non-UTF-8 bytes value is not allowed in wire representation{_wire_target(path)}; decode it to a string first."
            ) from error
    raise ValueError(
        f"Unsupported value of type {type(value).__name__!r} is not allowed in wire representation{_wire_target(path)}."
    )


def _dump(value: Any, path: str = "") -> Any:
    if isinstance(value, BaseModel):
        return _dump(value.model_dump(), path)
    if is_dataclass(value) and not isinstance(value, type):
        return _dump(_WIRE_ADAPTER.dump_python(value), path)
    if isinstance(value, Mapping):
        return {
            _dump_key(key, f"{path}.<key>" if path else "<key>"): _dump(
                item, f"{path}.{key}" if path else str(key)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_dump(item, f"{path}[{idx}]") for idx, item in enumerate(value)]
    return _dump_scalar(value, path)


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


def _is_child_collection(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if isinstance(origin, type) and issubclass(origin, Iterable):
        return not issubclass(origin, Mapping)
    return any(_is_child_collection(argument) for argument in get_args(annotation))


class SerModel(BaseModel):
    @model_serializer(mode="plain")
    def _serialize(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, field in type(self).model_fields.items():
            value = getattr(self, name)
            if value is None:
                continue
            key = field.alias or name
            out[key] = _dump(value, key)
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
        if not isinstance(v, list) and not _is_child_collection(
            cls.model_fields[info.field_name].annotation
        ):
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
            key = field.alias or name
            out[key] = _dump(value, key)
        if self.attributes:
            attributes = _dump(_WIRE_ADAPTER.dump_python(self.attributes), "attributes")
            out.update(attributes)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        if kwargs.get("allow_nan"):
            raise ValueError("allow_nan=True is not permitted: wire JSON must be strict standard-JSON")
        kwargs["allow_nan"] = False
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Primitive":
        if "type" not in data:
            raise ValueError("primitive dict is missing required 'type' key")

        data = _dump(data, "wire_payload")

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
