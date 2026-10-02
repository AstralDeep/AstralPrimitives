"""
base.py — shared Primitive base class.

v2 (bounty #8 primitives-004): to_json now passes allow_nan=False so that
NaN/Infinity values raise a clear ValueError at the wire boundary instead
of producing non-standard JSON tokens that crash MCP/A2A consumers.
"""
import json
import math
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


def _reject_non_finite(value: Any, path: str = "value") -> None:
    """Recursively reject NaN/Infinity in nested values before serialisation.

    json.dumps(allow_nan=False) catches top-level issues, but consumers
    benefit from a typed ValueError with the offending field path.
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(
                f"non-finite numeric value at {path}: {value!r} "
                "(JSON wire format requires finite numbers)"
            )
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_non_finite(v, f"{path}[{i}]")


class Primitive(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    type: str = Field(..., alias="type")
    attributes: Dict[str, Any] = Field(default_factory=dict)

    def _dump(self) -> Dict[str, Any]:
        """Build the canonical wire dict for this primitive."""
        out: Dict[str, Any] = {"type": self.type}
        for name, field in self.model_fields.items():
            if name == "attributes":
                continue
            try:
                value = getattr(self, name)
            except AttributeError:
                continue
            if value is None:
                continue
            if name == "css" and not value:
                continue
            out[field.alias or name] = value
        out.update(self.attributes or {})
        return out

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        # primitives-004: reject NaN/Infinity at the wire boundary so
        # downstream JSON parsers (MCP, A2A, native SDKs) never receive
        # non-standard tokens.
        payload = self.model_dump()
        _reject_non_finite(payload)
        kwargs.setdefault("allow_nan", False)
        return json.dumps(payload, **kwargs)

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
        attributes: Dict[str, Any] = {}
        for key, value in data.items():
            if key == "type":
                continue
            if key in known:
                kwargs[key] = value
            else:
                attributes[key] = value
        if attributes:
            kwargs["attributes"] = attributes
        return target(**kwargs)


# Registry populated by primitives.py on import
_REGISTRY: Dict[str, type] = {}


def register_primitive(cls: type) -> type:
    _REGISTRY[cls.model_fields["type"].default] = cls
    return cls
