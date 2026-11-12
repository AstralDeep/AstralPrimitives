"""Translates between primitives and A2UI v1.0: it publishes the vocabulary as an A2UI catalog, imports an
outside agent's surface as untrusted primitives, and exports primitives as an A2UI surface. The catalog is
derived from strict.py, and imported nodes are marked external so hosts and clients can tell them apart.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from pydantic import ValidationError

from .base import _REGISTRY, Primitive
from .primitives import Button, Card, Container, Divider, Input, Text
from .strict import ID_PATTERN, POINTER_PATTERN, strict_schema

A2UI_VERSION = "1.0"
CATALOG_ID = "urn:astralprims:a2ui:catalog:1"
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
MAX_COMPONENTS = 500
MAX_DEPTH = 16
MAX_TEXT = 4000

_COMPONENT_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CHILD_LISTS = ("children", "content", "buttons")
_DROPPED = ("url", "src", "css", "class", "capability", "provenance", "attributes", "id", "type")
_BASIC_UNSUPPORTED = (
    "Icon",
    "Video",
    "AudioPlayer",
    "Tabs",
    "Modal",
    "CheckBox",
    "DateTimeInput",
    "ChoicePicker",
    "Slider",
    "Image",
)
_INSTRUCTIONS = (
    "Every component has an id and a component name from this catalog. Children are referenced by id. "
    "Images, audio and downloads take a handle the host resolves, never a URL. Actionable components "
    "name a capability handle created with the surface and carry accessible_name, spoken and compact. "
    "A value read from a tool result is bound with an @path of /events/<event id><JSON pointer>."
)


class A2UIError(ValueError):
    pass


def _pascal(wire_type: str) -> str:
    return "Astral" + "".join(part.capitalize() for part in wire_type.split("_"))


def _convert(node: Any) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref is not None:
            name = ref.rsplit("/", 1)[1]
            target = {"binding": "Binding", "handle": "Handle"}.get(name, "ComponentId")
            return {"$ref": f"#/$defs/{target}"}
        return {key: _convert(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_convert(item) for item in node]
    return node


def a2ui_catalog() -> Dict[str, Any]:
    from astralprims import __version__

    profile = strict_schema()
    components: Dict[str, Any] = {}
    for wire_type in sorted(entry["$ref"].rsplit("/", 1)[1] for entry in profile["$defs"]["component"]["oneOf"]):
        definition = profile["$defs"][wire_type]
        properties = {
            key: _convert(value) for key, value in definition["properties"].items() if key not in ("type", "id")
        }
        properties["provenance"] = {"enum": ["model", "tool", "host", "external"]}
        name = _pascal(wire_type)
        components[name] = {
            "type": "object",
            "description": f"AstralPrimitives {wire_type} component.",
            "properties": {"component": {"const": name}, "id": {"$ref": "#/$defs/ComponentId"}, **properties},
            "required": ["component", "id"] + [k for k in definition["required"] if k not in ("type", "id")],
            "patternProperties": {"^@(accessibility|catalogId|metadata|checks)$": {}},
            "additionalProperties": False,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CATALOG_ID,
        "protocolVersion": A2UI_VERSION,
        "title": "AstralPrimitives catalog",
        "description": "The AstralPrimitives strict generation vocabulary as an A2UI catalog.",
        "catalogId": CATALOG_ID,
        "metadata": {"extensions": {"astralprimsVersion": __version__}},
        "instructions": _INSTRUCTIONS,
        "components": components,
        "$defs": {
            "ComponentId": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$", "maxLength": 64},
            "Binding": {
                "type": "object",
                "properties": {"@path": {"type": "string", "pattern": POINTER_PATTERN, "maxLength": 330}},
                "required": ["@path"],
                "additionalProperties": False,
            },
            "Handle": profile["$defs"]["handle"],
            "anyComponent": {"oneOf": [{"$ref": f"#/components/{name}"} for name in components]},
            "anyFunction": False,
        },
    }


@lru_cache(maxsize=None)
def _catalog_properties(wire_type: str) -> frozenset:
    return frozenset(a2ui_catalog()["components"][_pascal(wire_type)]["properties"])


@dataclass
class ImportedSurface:
    surface_id: str
    catalog_id: Optional[str]
    root: Primitive
    notices: List[str] = field(default_factory=list)

    @property
    def untrusted(self) -> bool:
        return True


def _pointer_get(data: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return data
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(data, dict) and token in data:
            data = data[token]
        elif isinstance(data, list) and token.isdigit() and int(token) < len(data):
            data = data[int(token)]
        else:
            return None
    return data


def _pointer_set(data: Any, pointer: str, value: Any) -> Any:
    if pointer in ("", "/"):
        return {} if value is None else value
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer.split("/")[1:]]
    if not isinstance(data, dict):
        data = {}
    cursor = data
    for token in tokens[:-1]:
        if not isinstance(cursor.get(token), dict):
            cursor[token] = {}
        cursor = cursor[token]
    if value is None:
        cursor.pop(tokens[-1], None)
    else:
        cursor[tokens[-1]] = value
    return data


class _Importer:
    def __init__(self, components: Dict[str, Dict[str, Any]], model: Any) -> None:
        self.components = components
        self.model = model
        self.notices: List[str] = []
        self.astral = {_pascal(t): t for t, cls in _REGISTRY.items() if cls.__module__.startswith("astralprims.")}

    def notice(self, text: str) -> None:
        if len(self.notices) < 50:
            self.notices.append(text)

    def value(self, raw: Any) -> Any:
        if isinstance(raw, dict):
            if "@path" in raw and isinstance(raw["@path"], str):
                return _pointer_get(self.model, raw["@path"]) if raw["@path"].startswith("/") else None
            if raw.get("@call") == "formatString" and isinstance(raw.get("args"), dict):
                template = raw["args"].get("value")
                if isinstance(template, str):
                    return re.sub(r"\$\{(/[^}]*)\}", lambda m: _text(_pointer_get(self.model, m.group(1))), template)
            self.notice("dynamic value not supported and dropped")
            return None
        if isinstance(raw, str) and raw.startswith("@@"):
            return raw[1:]
        return raw

    def text(self, raw: Any) -> str:
        return _text(self.value(raw))[:MAX_TEXT]

    def build(self, component_id: str, depth: int, stack: tuple) -> Primitive:
        if depth > MAX_DEPTH:
            raise A2UIError(f"surface is nested deeper than {MAX_DEPTH} levels at {component_id!r}")
        if component_id in stack:
            raise A2UIError(f"component {component_id!r} contains itself")
        component = self.components.get(component_id)
        if component is None:
            raise A2UIError(f"component {component_id!r} is referenced but not defined")
        name = component.get("component")
        stack = stack + (component_id,)
        kids = lambda value: self.children(value, depth, stack)  # noqa: E731
        node: Primitive
        if name == "Text":
            variant = component.get("variant")
            node = Text(content=self.text(component.get("text")), variant=variant if variant in _TEXT_VARIANTS else "body")
        elif name in ("Row", "Column", "List"):
            node = Container(direction="row" if name == "Row" else "column", children=kids(component.get("children")))
        elif name == "Card":
            child = component.get("child")
            node = Card(content=[self.build(child, depth + 1, stack)] if isinstance(child, str) else [])
        elif name == "Divider":
            node = Divider()
        elif name == "Button":
            node = self.button(component, depth, stack)
        elif name == "TextField":
            node = Input(
                placeholder=self.text(component.get("label")),
                name=component_id,
                value=self.text(component.get("value")),
            )
        elif name in self.astral:
            node = self.astral_component(name, component, depth, stack)
        else:
            self.notice(f"component {_safe(name)} is not supported and was replaced by text")
            node = Text(content=f"[unsupported component: {_safe(name)}]", variant="muted")
        node.id = component_id if len(component_id) <= 64 and re.match(ID_PATTERN, component_id) else None
        node.provenance = "external"
        label = component.get("@accessibility", {}).get("label") if isinstance(component.get("@accessibility"), dict) else None
        if isinstance(label, str) and label:
            node.accessible_name = label[:120]
        return node

    def children(self, raw: Any, depth: int, stack: tuple) -> List[Primitive]:
        if isinstance(raw, list):
            return [self.build(item, depth + 1, stack) for item in raw if isinstance(item, str)]
        if raw is not None:
            self.notice("template children are not supported and were dropped")
        return []

    def button(self, component: Dict[str, Any], depth: int, stack: tuple) -> Button:
        label = ""
        child = component.get("child")
        if isinstance(child, str) and isinstance(self.components.get(child), dict):
            label = self.text(self.components[child].get("text"))
        variant = "secondary" if component.get("variant") == "borderless" else "primary"
        action, payload = "", {}
        spec = component.get("action")
        event = spec.get("event") if isinstance(spec, dict) else None
        if isinstance(event, dict) and isinstance(event.get("name"), str):
            action = event["name"]
            context = event.get("context")
            if isinstance(context, dict):
                payload = {str(k): self.value(v) for k, v in context.items()}
        elif spec is not None:
            self.notice("local function actions are not supported and were dropped")
        return Button(label=label, action=action, payload=payload, variant=variant)

    def astral_component(self, name: str, component: Dict[str, Any], depth: int, stack: tuple) -> Primitive:
        wire_type = self.astral[name]
        cls = _REGISTRY[wire_type]
        allowed = {(f.alias or n) for n, f in cls.model_fields.items()} - set(_DROPPED)
        data: Dict[str, Any] = {"type": wire_type}
        for key, raw in component.items():
            if key in ("component", "id") or key.startswith("@"):
                continue
            if key in _DROPPED or key not in allowed:
                self.notice(f"property {_safe(key)} of {name} was dropped")
                continue
            data[key] = self.convert_astral(key, raw, depth, stack)
        try:
            return Primitive.from_dict(data)
        except (ValidationError, ValueError):
            self.notice(f"{name} had invalid properties and was replaced by text")
            return Text(content=f"[invalid component: {_safe(name)}]", variant="muted")

    def convert_astral(self, key: str, raw: Any, depth: int, stack: tuple) -> Any:
        if key in _CHILD_LISTS and isinstance(raw, list) and all(isinstance(i, str) for i in raw):
            return [self.build(i, depth + 1, stack).to_dict() for i in raw]
        if key == "tabs" and isinstance(raw, list):
            return [
                {**tab, "content": [self.build(i, depth + 1, stack).to_dict() for i in tab.get("content", [])]}
                if isinstance(tab, dict)
                else tab
                for tab in raw
            ]
        return self.binding(raw)

    def binding(self, raw: Any) -> Any:
        if isinstance(raw, dict):
            path = raw.get("@path")
            if isinstance(path, str) and set(raw) == {"@path"}:
                match = re.match(r"^/events/([^/]+)(/.*)?$", path)
                if match:
                    return {"bind": {"event": match.group(1), "path": match.group(2) or ""}}
                self.notice("data model binding outside /events was replaced by its current value")
                return self.value(raw)
            return {k: self.binding(v) for k, v in raw.items()}
        if isinstance(raw, list):
            return [self.binding(v) for v in raw]
        return raw


_TEXT_VARIANTS = {"body", "h1", "h2", "h3", "h4", "h5", "h6", "caption", "muted", "label"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)[:200]


def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(value))[:40] or "unknown"


def from_a2ui(messages: Sequence[Mapping[str, Any]]) -> ImportedSurface:
    if not isinstance(messages, (list, tuple)) or not messages:
        raise A2UIError("expected a non-empty list of A2UI messages")
    surface_id: Optional[str] = None
    catalog_id: Optional[str] = None
    components: Dict[str, Dict[str, Any]] = {}
    model: Any = {}
    deleted = False
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping) or message.get("version") != A2UI_VERSION:
            raise A2UIError(f"message {index} is not an A2UI {A2UI_VERSION} message")
        keys = [k for k in message if k != "version"]
        if len(keys) != 1 or keys[0] not in ("createSurface", "updateComponents", "updateDataModel", "deleteSurface"):
            raise A2UIError(f"message {index} must carry exactly one of createSurface, updateComponents, updateDataModel, deleteSurface")
        body = message[keys[0]]
        if not isinstance(body, Mapping) or not isinstance(body.get("surfaceId"), str) or not body["surfaceId"]:
            raise A2UIError(f"message {index} needs a surfaceId")
        if surface_id is not None and body["surfaceId"] != surface_id:
            raise A2UIError("messages for more than one surface are not supported")
        surface_id = body["surfaceId"]
        if keys[0] == "deleteSurface":
            deleted = True
            components, model = {}, {}
            continue
        deleted = False
        if keys[0] == "createSurface":
            catalog_id = body.get("catalogId") if isinstance(body.get("catalogId"), str) else None
            if "dataModel" in body:
                model = body["dataModel"]
        if keys[0] == "updateDataModel":
            if "value" not in body:
                raise A2UIError(f"message {index} needs a value")
            model = _pointer_set(model, body.get("path", "/"), body["value"])
        for item in body.get("components", []) if keys[0] != "updateDataModel" else []:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not _COMPONENT_ID.match(item["id"]):
                raise A2UIError(f"message {index} has a component without a valid id")
            if not isinstance(item.get("component"), str):
                raise A2UIError(f"component {item['id']!r} has no component name")
            components[item["id"]] = dict(item)
            if len(components) > MAX_COMPONENTS:
                raise A2UIError(f"surface has more than {MAX_COMPONENTS} components")
    if deleted or "root" not in components:
        raise A2UIError("surface has no root component")
    importer = _Importer(components, model)
    root = importer.build("root", 0, ())
    return ImportedSurface(surface_id or "", catalog_id, root, importer.notices)


_VALID_ID = re.compile(r"[^A-Za-z0-9_]")


class _Exporter:
    def __init__(self) -> None:
        self.components: List[Dict[str, Any]] = []
        self.used = {"root"}
        self.counter = 0

    def new_id(self, preferred: Optional[str] = None) -> str:
        if preferred:
            candidate = _VALID_ID.sub("_", preferred)
            if _COMPONENT_ID.match(candidate) and candidate not in self.used:
                self.used.add(candidate)
                return candidate
        while True:
            self.counter += 1
            candidate = f"n{self.counter}"
            if candidate not in self.used:
                self.used.add(candidate)
                return candidate

    @staticmethod
    def dynamic(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"bind"}:
            ref = value["bind"]
            return {"@path": f"/events/{ref['event']}{ref['path']}"}
        return value

    def astral(self, node: Dict[str, Any], component_id: str) -> str:
        out: Dict[str, Any] = {"id": component_id, "component": _pascal(node["type"])}
        for key, value in node.items():
            if key in ("type", "id") or key not in _catalog_properties(node["type"]):
                continue
            if key in _CHILD_LISTS and isinstance(value, list) and all(isinstance(i, dict) and "type" in i for i in value):
                out[key] = [self.astral(i, self.new_id(i.get("id"))) for i in value]
            elif key == "tabs" and isinstance(value, list):
                out[key] = [
                    {**tab, "content": [self.astral(i, self.new_id(i.get("id"))) for i in tab.get("content", [])]}
                    for tab in value
                ]
            else:
                out[key] = _bind_all(value)
        if node.get("accessible_name"):
            out["@accessibility"] = {"label": node["accessible_name"]}
        self.components.append(out)
        return component_id

    def basic(self, node: Dict[str, Any], component_id: str) -> str:
        wire_type = node["type"]
        out: Dict[str, Any]
        if wire_type == "text":
            out = {"component": "Text", "text": self.dynamic(node.get("content", ""))}
            if node.get("variant") in ("caption", "body"):
                out["variant"] = node["variant"]
        elif wire_type in ("container", "grid"):
            kids = [self.basic(c, self.new_id(c.get("id"))) for c in node.get("children", [])]
            out = {"component": "Row" if node.get("direction") == "row" else "Column", "children": kids}
        elif wire_type == "card":
            kids = [self.basic(c, self.new_id(c.get("id"))) for c in node.get("content", [])]
            column = self.new_id()
            self.components.append({"id": column, "component": "Column", "children": kids})
            out = {"component": "Card", "child": column}
        elif wire_type == "divider":
            out = {"component": "Divider"}
        elif wire_type == "button":
            label = self.new_id()
            self.components.append({"id": label, "component": "Text", "text": node.get("label", "")})
            handle = node.get("capability", {}).get("handle") if isinstance(node.get("capability"), dict) else None
            out = {
                "component": "Button",
                "child": label,
                "variant": "borderless" if node.get("variant") == "secondary" else "primary",
                "action": {"event": {"name": handle or node.get("action", ""), "context": {}}},
            }
        elif wire_type == "input":
            out = {"component": "TextField", "label": node.get("placeholder", ""), "value": node.get("value", "")}
        else:
            out = {"component": "Text", "text": self.fallback(node)}
        if node.get("accessible_name"):
            out["@accessibility"] = {"label": node["accessible_name"]}
        out["id"] = component_id
        self.components.append(out)
        return component_id

    def fallback(self, node: Dict[str, Any]) -> Any:
        for key in ("spoken", "accessible_name", "title", "label", "message", "content"):
            value = self.dynamic(node.get(key))
            if isinstance(value, (str, dict)) and value:
                return value
        return node["type"]


def _bind_all(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"bind"} and isinstance(value["bind"], dict):
            return _Exporter.dynamic(value)
        return {k: _bind_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_bind_all(v) for v in value]
    return value


def to_a2ui(
    tree: Union[Primitive, Mapping[str, Any]], surface_id: str, catalog: str = "astral"
) -> List[Dict[str, Any]]:
    if catalog not in ("astral", "basic"):
        raise A2UIError("catalog must be 'astral' or 'basic'")
    if not _COMPONENT_ID.match(surface_id or ""):
        raise A2UIError("surface_id must be a valid identifier")
    node = tree.to_dict() if isinstance(tree, Primitive) else Primitive.from_dict(dict(tree)).to_dict()
    exporter = _Exporter()
    (exporter.astral if catalog == "astral" else exporter.basic)(node, "root")
    exporter.components.reverse()
    return [
        {
            "version": A2UI_VERSION,
            "createSurface": {
                "surfaceId": surface_id,
                "catalogId": CATALOG_ID if catalog == "astral" else BASIC_CATALOG_ID,
            },
        },
        {
            "version": A2UI_VERSION,
            "updateComponents": {"surfaceId": surface_id, "components": exporter.components},
        },
    ]
