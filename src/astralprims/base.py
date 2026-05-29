"""Base machinery shared by every UI primitive.

A primitive is a Pydantic model describing a piece of UI. It validates on
construction, serializes to a plain ``dict``/JSON (``to_dict``/``to_json``), and
can be reconstructed from a ``dict`` (``from_dict``) — so primitives can be
stored, transported, validated on inbound FastAPI requests, and rendered by a
server-driven UI. JSON stays the wire format; Pydantic is the authoring layer.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

# A CSS block is just a mapping of (kebab-case) property -> value.
CSS = Dict[str, str]

# Registry of ``type`` string -> Primitive subclass, populated as subclasses are
# defined. Used by :func:`Primitive.from_dict` to round-trip dicts back into
# objects and by ``__init__`` to build the discriminated union.
_REGISTRY: Dict[str, type["Primitive"]] = {}


def _dump(value: Any) -> Any:
    """Recursively serialize a value, dispatching nested models to their own
    serializer (so each model controls its own output shape)."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _coerce_children(value: Any) -> Any:
    """Turn a list of child dicts (each carrying a ``type``) into primitives."""
    if isinstance(value, list):
        return [
            Primitive.from_dict(v) if isinstance(v, dict) and "type" in v else v
            for v in value
        ]
    return value


class SerModel(BaseModel):
    """A model that serializes by dropping ``None`` fields and honoring aliases.

    Used for nested non-primitive helpers (``TabItem``, ``ChartDataset``).
    """

    @model_serializer(mode="plain")
    def _serialize(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, field in type(self).model_fields.items():
            value = getattr(self, name)
            if value is None:
                continue
            out[field.alias or name] = _dump(value)
        return out


class Primitive(BaseModel):
    """Base class for all UI primitives.

    Subclasses set ``type`` to a ``Literal[...]`` and declare their own fields.
    Serialization emits ``"type"`` first, drops ``None``, omits an empty ``css``
    block, renames ``class_name`` to ``"class"``, and merges ``attributes`` at
    the top level.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: str = "primitive"
    css: Optional[CSS] = None
    id: Optional[str] = None
    class_name: Optional[str] = Field(default=None, alias="class")
    tooltip: Optional[str] = None
    # Free-form extra attributes merged into the output (escape hatch).
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        type_field = cls.model_fields.get("type")
        if type_field is not None and isinstance(type_field.default, str):
            _REGISTRY[type_field.default] = cls

    # Reconstruct nested ``children``/``content`` dicts into primitives. Declared
    # here with check_fields=False so it applies to whichever subclasses have
    # those fields (Container, Card, Grids, Collapsible, ...).
    @field_validator("children", "content", mode="before", check_fields=False)
    @classmethod
    def _coerce_primitive_children(cls, v: Any) -> Any:
        return _coerce_children(v)

    # -- serialization ----------------------------------------------------

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
                continue  # omit empty style blocks
            out[field.alias or name] = _dump(value)
        # Extra attributes are merged last so callers can override or extend.
        out.update(self.attributes or {})
        return out

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain ``dict`` with ``"type"`` first."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Serialize to a JSON string. Extra kwargs go to :func:`json.dumps`."""
        return json.dumps(self.model_dump(), **kwargs)

    # -- deserialization --------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Primitive":
        """Reconstruct a primitive (and any children) from a ``dict``.

        Dispatches on the ``"type"`` key to the matching registered subclass.
        Unknown keys are funneled into ``attributes``.
        """
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
        return target.model_validate(kwargs)
