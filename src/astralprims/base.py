"""Pydantic base for every UI primitive: the type registry plus
to_dict/to_json/from_dict serialization. primitives.py subclasses Primitive;
__init__.py builds the union from the registry.
"""

from __future__ import annotations

import base64
import json
import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import PurePath
from typing import Any, Dict, Literal, Optional, get_args, get_origin

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

_JSON_NATIVE_SCALAR = (str, int, float, bool, type(None))


class PrimitiveTypeError(ValueError):
    pass


def _normalize_mapping_key(key: Any, path: str) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (int, float, Decimal)):
        return str(key)
    if isinstance(key, uuid.UUID):
        return str(key)
    if isinstance(key, Enum):
        return _normalize_mapping_key(key.value, path)
    raise PrimitiveTypeError(
        f"mapping key at {path!r} has non-JSON-native type {type(key).__name__!r}"
    )


def _normalize_value(value: Any, path: str = "") -> Any:
    if isinstance(value, _JSON_NATIVE_SCALAR):
        return value
    if isinstance(value, BaseModel):
        return _normalize_value(value.model_dump(), path)
    # Convert dataclass instances to dict via the existing wire adapter before
    # recursing. _assert_finite does the same conversion at its entrypoint;
    # _normalize_value must agree with it, otherwise dataclass payloads raise
    # a non-JSON-native-type error instead of being walked.
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_value(_WIRE_ADAPTER.dump_python(value), path)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, Enum):
        return _normalize_value(value.value, path)
    if isinstance(value, (set, frozenset)):
        try:
            items = sorted(value)
        except TypeError:
            items = sorted(value, key=lambda x: str(x))
        return [_normalize_value(v, f"{path}[{i}]") for i, v in enumerate(items)]
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        # Preserve mapping keys as-is in the returned dict (existing tests
        # pin int/float keys surviving to_dict). _assert_finite_mapping_keys
        # has already raised on NaN/Inf float keys before _normalize_value
        # runs. We still need to detect collisions that would otherwise be
        # silently dropped by json.dumps — str "1" and int 1 both serialize
        # to the JSON key "1" and one would overwrite the other.
        out: Dict[Any, Any] = {}
        seen: Dict[str, Any] = {}
        for k, v in value.items():
            nkey = _normalize_mapping_key(k, f"{path}.<key>")
            if nkey in seen and seen[nkey] != k:
                raise PrimitiveTypeError(
                    f"normalized key collision at {path!r}.<key>: "
                    f"{nkey!r} produced by {seen[nkey]!r} and {k!r}"
                )
            seen[nkey] = k
            out[k] = _normalize_value(v, f"{path}.{k}" if path else str(k))
        return out
    raise PrimitiveTypeError(
        f"primitive payload field at {path!r} has non-JSON-native type {type(value).__name__!r}"
    )


def _assert_finite(value: Any, path: str = "") -> None:
    if isinstance(value, BaseModel) or (is_dataclass(value) and not isinstance(value, type)):
        value = _WIRE_ADAPTER.dump_python(value)
    if isinstance(value, float):
        if math.isnan(value):
            target = f" at field {path!r}" if path else ""
            raise ValueError(f"Non-finite numeric value NaN is not allowed in wire representation{target}.")
        if math.isinf(value):
            target = f" at field {path!r}" if path else ""
            sign = "Infinity" if value > 0 else "-Infinity"
            raise ValueError(f"Non-finite numeric value {sign} is not allowed in wire representation{target}.")
    elif isinstance(value, dict):
        _assert_finite_mapping_keys(value, path)
        for k, v in value.items():
            _assert_finite(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for idx, item in enumerate(value):
            _assert_finite(item, f"{path}[{idx}]")


def _assert_finite_mapping_keys(value: Dict[Any, Any], path: str) -> None:
    for key in value:
        if isinstance(key, float):
            _assert_finite(key, f"{path}.<key>" if path else "<key>")


def _dump(value: Any, path: str = "") -> Any:
    # Check mapping keys for finite BEFORE _normalize_value converts
    # float keys to strings (which would hide NaN/Inf in keys).
    if isinstance(value, dict):
        _assert_finite_mapping_keys(value, path)
    value = _normalize_value(value, path)
    if isinstance(value, BaseModel):
        return _dump(value.model_dump(), path)
    if isinstance(value, list):
        return [_dump(v, f"{path}[{idx}]") for idx, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: _dump(v, f"{path}.{k}" if path else str(k)) for k, v in value.items()}
    value = _WIRE_ADAPTER.dump_python(value)
    _assert_finite(value, path)
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
            attributes = _WIRE_ADAPTER.dump_python(self.attributes)
            _assert_finite(attributes, "attributes")
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

        _assert_finite(data, "wire_payload")

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
