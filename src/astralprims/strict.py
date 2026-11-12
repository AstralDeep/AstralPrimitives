"""Builds the strict generation profile: a closed, bounded JSON Schema of the vocabulary that a decoding
grammar can be generated from. validate.py checks model-produced trees against it, and a2ui.py derives the
published catalog from it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PROFILE_ID = "astralprims-generation-strict"
MAX_DEPTH = 8
MAX_NODES = 300
ID_PATTERN = "^[A-Za-z][A-Za-z0-9_-]{0,63}$"
HANDLE_PATTERN = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
EVENT_PATTERN = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
POINTER_PATTERN = "^(/[^/~]*(~[01][^/~]*)*)*$"
NAME_PATTERN = "^[A-Za-z][A-Za-z0-9_]{0,47}$"

EXCLUDED_TYPES = {
    "chat_history": "produced by the host from stored chats",
    "diff": "produced by tools from real file changes",
    "findings": "produced by tools from a review",
    "plotly_chart": "carries open-ended chart configuration",
    "theme_apply": "changes the host theme, which a model may not do",
}

SEMANTIC = ["default", "primary", "secondary", "success", "warning", "error", "info"]
TEXT_VARIANTS = ["body", "h1", "h2", "h3", "h4", "h5", "h6", "caption", "muted", "label"]


def _str(max_len: int, min_len: int = 0, pattern: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "string", "minLength": min_len, "maxLength": max_len}
    if pattern:
        out["pattern"] = pattern
    return out


def _int(lo: int, hi: int) -> Dict[str, Any]:
    return {"type": "integer", "minimum": lo, "maximum": hi}


def _num(lo: float, hi: float) -> Dict[str, Any]:
    return {"type": "number", "minimum": lo, "maximum": hi}


def _enum(*values: str) -> Dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def _arr(item: Dict[str, Any], max_items: int, min_items: int = 0) -> Dict[str, Any]:
    return {"type": "array", "items": item, "minItems": min_items, "maxItems": max_items}


def _obj(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or []),
        "additionalProperties": False,
    }


def _bound(literal: Dict[str, Any]) -> Dict[str, Any]:
    return {"anyOf": [literal, {"$ref": "#/$defs/binding"}]}


def _children(max_items: int, min_items: int = 0) -> Dict[str, Any]:
    return _arr({"$ref": "#/$defs/component"}, max_items, min_items)


TITLE = _str(120)
LABEL = _str(80)
SHORT = _str(40)
VARIANT = _enum(*SEMANTIC)
UNIT = _num(0, 1)
DATA = _arr(_num(-1e12, 1e12), 200)
HANDLE_REF = {"$ref": "#/$defs/handle"}


def _spec() -> Dict[str, Dict[str, Any]]:
    dataset = _obj({"label": SHORT, "data": DATA}, ["label", "data"])
    cell = {
        "anyOf": [_str(200), _num(-1e12, 1e12), {"type": "boolean"}, {"$ref": "#/$defs/binding"}]
    }
    return {
        "container": {"properties": {"children": _children(50), "direction": _enum("row", "column")}},
        "card": {"properties": {"title": TITLE, "content": _children(50), "variant": VARIANT}},
        "grid": {"properties": {"columns": _int(1, 6), "children": _children(50), "gap": _int(0, 64)}},
        "tabs": {
            "properties": {
                "tabs": _arr(
                    _obj({"label": _str(40, 1), "value": SHORT, "content": _children(20)}, ["label", "content"]),
                    8,
                    1,
                ),
                "variant": VARIANT,
            }
        },
        "collapsible": {
            "properties": {"title": TITLE, "content": _children(50), "default_open": {"type": "boolean"}}
        },
        "divider": {"properties": {"variant": _enum("solid", "dashed", "dotted")}},
        "text": {
            "properties": {"content": _bound(_str(4000)), "variant": _enum(*TEXT_VARIANTS)},
            "required": ["content"],
        },
        "button": {
            "properties": {"label": _str(60, 1), "variant": VARIANT},
            "required": ["label"],
            "actionable": True,
        },
        "action_group": {
            "properties": {
                "buttons": _arr({"$ref": "#/$defs/button"}, 8, 1),
                "align": _enum("start", "center", "end", "between"),
                "label": LABEL,
            },
            "required": ["buttons"],
            "forms": True,
        },
        "input": {
            "properties": {
                "placeholder": LABEL,
                "name": _str(48, 1, NAME_PATTERN),
                "value": _str(500),
            },
            "required": ["name"],
            "actionable": True,
        },
        "param_picker": {
            "properties": {
                "title": TITLE,
                "description": _str(400),
                "fields": _arr(
                    _obj(
                        {
                            "name": _str(48, 1, NAME_PATTERN),
                            "label": _str(80, 1),
                            "kind": _enum("text", "number", "select", "boolean"),
                            "options": _arr(_str(80, 1), 20),
                            "required": {"type": "boolean"},
                        },
                        ["name", "label", "kind"],
                    ),
                    12,
                    1,
                ),
                "submit_label": SHORT,
            },
            "required": ["fields"],
            "actionable": True,
        },
        "image": {
            "properties": {"source": HANDLE_REF, "alt": _str(200, 1)},
            "required": ["source", "alt"],
        },
        "code": {
            "properties": {
                "code": _str(8000),
                "language": _str(24, 1, "^[A-Za-z0-9_+#.-]+$"),
                "show_line_numbers": {"type": "boolean"},
            },
            "required": ["code"],
        },
        "alert": {
            "properties": {
                "message": _bound(_str(1000)),
                "variant": _enum("info", "success", "warning", "error"),
                "title": TITLE,
            },
            "required": ["message"],
        },
        "progress": {
            "properties": {
                "value": _bound(UNIT),
                "label": LABEL,
                "variant": VARIANT,
                "show_percentage": {"type": "boolean"},
            },
            "required": ["value"],
        },
        "metric": {
            "properties": {
                "title": TITLE,
                "value": _bound(_str(40)),
                "subtitle": LABEL,
                "icon": _str(40, 0, "^[A-Za-z0-9_-]*$"),
                "variant": VARIANT,
                "progress": UNIT,
            },
            "required": ["title", "value"],
        },
        "list": {
            "properties": {
                "items": _arr(
                    {
                        "anyOf": [
                            _str(300),
                            _obj({"title": _str(200), "subtitle": _str(200), "description": _str(600)}, ["title"]),
                        ]
                    },
                    100,
                ),
                "ordered": {"type": "boolean"},
                "variant": _enum("default", "detailed"),
            },
            "required": ["items"],
        },
        "table": {
            "properties": {
                "headers": _arr(_str(80), 12, 1),
                "rows": _arr(_arr(cell, 12), 100),
                "variant": VARIANT,
            },
            "required": ["headers", "rows"],
        },
        "bar_chart": {
            "properties": {"title": TITLE, "labels": _arr(SHORT, 200), "datasets": _arr(dataset, 8, 1)},
            "required": ["labels", "datasets"],
        },
        "line_chart": {
            "properties": {"title": TITLE, "labels": _arr(SHORT, 200), "datasets": _arr(dataset, 8, 1)},
            "required": ["labels", "datasets"],
        },
        "pie_chart": {
            "properties": {"title": TITLE, "labels": _arr(SHORT, 50), "data": _arr(_num(0, 1e12), 50)},
            "required": ["labels", "data"],
        },
        "donut_chart": {
            "properties": {
                "title": TITLE,
                "labels": _arr(SHORT, 50),
                "data": _arr(_num(0, 1e12), 50),
                "center_label": SHORT,
                "center_value": _bound(_str(40)),
            },
            "required": ["labels", "data"],
        },
        "radar_chart": {
            "properties": {
                "title": TITLE,
                "axes": _arr(SHORT, 12, 3),
                "datasets": _arr(dataset, 6, 1),
                "max_value": _num(0, 1e12),
            },
            "required": ["axes", "datasets"],
        },
        "audio": {
            "properties": {
                "source": HANDLE_REF,
                "label": LABEL,
                "description": _str(400),
                "loop": {"type": "boolean"},
                "showControls": {"type": "boolean"},
            },
            "required": ["source", "label"],
        },
        "file_upload": {
            "properties": {
                "label": LABEL,
                "accept": _str(100, 1, "^[A-Za-z0-9*/.,+ -]+$"),
            },
            "required": ["label"],
            "actionable": True,
        },
        "file_download": {
            "properties": {"label": LABEL, "target": HANDLE_REF, "filename": _str(120)},
            "required": ["label", "target"],
        },
        "badge": {
            "properties": {"label": _bound(SHORT), "variant": VARIANT, "icon": _str(40, 0, "^[A-Za-z0-9_-]*$")},
            "required": ["label"],
        },
        "hero": {
            "properties": {
                "title": TITLE,
                "subtitle": _str(240),
                "eyebrow": SHORT,
                "icon": _str(40, 0, "^[A-Za-z0-9_-]*$"),
                "variant": VARIANT,
                "badges": _arr(SHORT, 8),
            },
            "required": ["title"],
        },
        "keyvalue": {
            "properties": {
                "title": TITLE,
                "items": _arr(
                    _obj({"label": _str(80, 1), "value": _str(300), "hint": _str(200)}, ["label", "value"]),
                    50,
                    1,
                ),
                "columns": _int(1, 4),
            },
            "required": ["items"],
        },
        "timeline": {
            "properties": {
                "title": TITLE,
                "items": _arr(
                    _obj(
                        {
                            "title": _str(200, 1),
                            "description": _str(400),
                            "time": SHORT,
                            "variant": VARIANT,
                        },
                        ["title"],
                    ),
                    50,
                    1,
                ),
            },
            "required": ["items"],
        },
        "stat_group": {
            "properties": {
                "title": TITLE,
                "items": _arr(
                    _obj(
                        {
                            "label": _str(80, 1),
                            "value": _str(40),
                            "delta": SHORT,
                            "trend": _enum("up", "down", "flat"),
                            "hint": _str(200),
                            "variant": VARIANT,
                        },
                        ["label", "value"],
                    ),
                    12,
                    1,
                ),
                "columns": _int(1, 6),
            },
            "required": ["items"],
        },
        "gauge": {
            "properties": {
                "label": _str(80, 1),
                "value": _bound(UNIT),
                "display_value": _bound(SHORT),
                "thresholds": _arr(_obj({"at": UNIT, "variant": VARIANT}, ["at", "variant"]), 6),
                "subtitle": LABEL,
            },
            "required": ["label", "value"],
        },
        "pipeline_stepper": {
            "properties": {
                "title": TITLE,
                "steps": _arr(
                    _obj(
                        {
                            "label": _str(80, 1),
                            "status": _enum("done", "active", "pending", "error"),
                            "detail": _str(200),
                        },
                        ["label", "status"],
                    ),
                    20,
                    1,
                ),
                "orientation": _enum("horizontal", "vertical"),
            },
            "required": ["steps"],
        },
        "rating": {
            "properties": {
                "value": _bound(_num(0, 10)),
                "max_value": _int(1, 10),
                "label": LABEL,
                "subtitle": LABEL,
                "show_value": {"type": "boolean"},
            },
            "required": ["value"],
        },
        "color_picker": {
            "properties": {
                "label": _str(80, 1),
                "color_key": _str(48, 1, NAME_PATTERN),
                "value": _str(9, 4, "^#[0-9A-Fa-f]{3,8}$"),
            },
            "required": ["label", "color_key"],
            "actionable": True,
        },
    }


def _definition(wire_type: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    actionable = bool(spec.get("actionable"))
    properties: Dict[str, Any] = {
        "type": {"const": wire_type},
        "id": _str(64, 1, ID_PATTERN),
        "tooltip": _str(200),
        "provenance": {"const": "model"},
        "accessible_name": _str(120, 1),
        "spoken": _str(300, 1),
        "compact": _str(60, 1),
    }
    properties.update(spec["properties"])
    required = ["type"] + list(spec.get("required", []))
    if actionable:
        properties["capability"] = {"$ref": "#/$defs/handle"}
        required += ["capability"]
    if actionable or spec.get("forms"):
        required += ["accessible_name", "spoken", "compact"]
    return _obj(properties, required)


def strict_schema() -> Dict[str, Any]:
    from astralprims import __version__
    from astralprims.base import _REGISTRY

    spec = _spec()
    shipped = {t for t, cls in _REGISTRY.items() if cls.__module__.startswith("astralprims.")}
    missing = shipped - set(spec) - set(EXCLUDED_TYPES)
    if missing:
        raise RuntimeError(f"strict profile does not cover shipped types: {sorted(missing)}")
    defs: Dict[str, Any] = {name: _definition(name, spec[name]) for name in sorted(spec)}
    defs["handle"] = _obj({"handle": _str(128, 1, HANDLE_PATTERN)}, ["handle"])
    defs["binding"] = _obj(
        {
            "bind": _obj(
                {"event": _str(128, 1, EVENT_PATTERN), "path": _str(200, 0, POINTER_PATTERN)},
                ["event", "path"],
            )
        },
        ["bind"],
    )
    defs["component"] = {"oneOf": [{"$ref": f"#/$defs/{name}"} for name in sorted(spec)]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROFILE_ID,
        "title": "AstralPrimitives strict generation profile",
        "description": (
            "Closed, bounded subset of the wire schema for model-generated trees. No object accepts "
            "unlisted properties, every string, list and number is bounded, images, audio and "
            "download targets are host-resolved handles, and every actionable component carries a "
            "capability handle, an accessible name, a spoken form and a compact form. "
            "Generated trees must stay within x-astralprims-limits, which a schema cannot express."
        ),
        "x-astralprims-version": __version__,
        "x-astralprims-limits": {"max_depth": MAX_DEPTH, "max_nodes": MAX_NODES},
        "x-astralprims-excluded": dict(sorted(EXCLUDED_TYPES.items())),
        "$ref": "#/$defs/component",
        "$defs": defs,
    }
