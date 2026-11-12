"""Checks a model-produced component tree against the strict generation profile and the rules a schema
cannot state, returning precise errors with a valid example for each. It reads the profile from
strict.py and resolves bindings, capabilities and handles through a caller-supplied Resolver.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Set

from markdown_it import MarkdownIt

from .strict import (
    HANDLE_PATTERN,
    EXCLUDED_TYPES,
    MAX_DEPTH,
    MAX_NODES,
    strict_schema,
)

_SAMPLES = {
    "^[A-Za-z][A-Za-z0-9_-]{0,63}$": "node1",
    "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$": "handle1",
    "^(/[^/~]*(~[01][^/~]*)*)*$": "/value",
    "^[A-Za-z][A-Za-z0-9_]{0,47}$": "field",
    "^[A-Za-z0-9_+#.-]+$": "text",
    "^[A-Za-z0-9_-]*$": "icon",
    "^[A-Za-z0-9*/.,+ -]+$": "*/*",
    "^#[0-9A-Fa-f]{3,8}$": "#000000",
}
_LINK_TOKENS = frozenset({"link_open", "image", "html_inline", "html_block"})
_SCHEME_OR_WWW = re.compile(
    r"\b[a-z][a-z0-9+.-]{0,31}://|\b(?:javascript|vbscript|data|file|tel|sms|blob|ftp|ftps|intent|callto):\S|\bwww\.\S", re.IGNORECASE
)
_MARKDOWN = MarkdownIt("commonmark", {"linkify": True, "html": True}).enable("linkify")
_MARKDOWN.linkify.set({"fuzzy_link": False, "fuzzy_email": False})


def _contains_link(text: str) -> bool:
    env: Dict[str, Any] = {}
    stack = list(_MARKDOWN.parse(text, env))
    if env.get("references"):
        return True
    while stack:
        token = stack.pop()
        if token.type in _LINK_TOKENS:
            return True
        stack.extend(token.children or ())
    return bool(_SCHEME_OR_WWW.search(text))


class Resolver(Protocol):
    def binding_resolves(self, event: str, path: str) -> bool: ...

    def knows_capability(self, handle: str) -> bool: ...

    def knows_handle(self, handle: str) -> bool: ...


class StaticResolver:
    def __init__(
        self,
        events: Optional[Mapping[str, Any]] = None,
        capabilities: Iterable[str] = (),
        handles: Iterable[str] = (),
    ) -> None:
        self._events = dict(events or {})
        self._capabilities = set(capabilities)
        self._handles = set(handles)

    def binding_resolves(self, event: str, path: str) -> bool:
        if event not in self._events:
            return False
        value = self._events[event]
        if path == "":
            return True
        for token in path.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, Mapping) and token in value:
                value = value[token]
            elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
                value = value[int(token)]
            else:
                return False
        return True

    def knows_capability(self, handle: str) -> bool:
        return handle in self._capabilities

    def knows_handle(self, handle: str) -> bool:
        return handle in self._handles


@dataclass(frozen=True)
class GenerationError:
    path: str
    problem: str
    example: Any = None

    def __str__(self) -> str:
        return f"{self.path or '$'}: {self.problem}"


def _example(schema: Dict[str, Any], defs: Dict[str, Any]) -> Any:
    if "$ref" in schema:
        return _example(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
    if "oneOf" in schema:
        return _example(defs["text"], defs)
    if "anyOf" in schema:
        return _example(schema["anyOf"][0], defs)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        sample = _SAMPLES.get(schema.get("pattern", ""), "x")
        return sample if len(sample) >= schema.get("minLength", 0) else "x" * schema["minLength"]
    if kind in ("number", "integer"):
        value = max(schema.get("minimum", 0), 0)
        return min(value, schema.get("maximum", value))
    if kind == "boolean":
        return False
    if kind == "array":
        return [_example(schema["items"], defs) for _ in range(schema.get("minItems", 0))]
    if kind == "object":
        return {key: _example(schema["properties"][key], defs) for key in schema["required"]}
    return None


def _json_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def _branch_accepts(branch: Dict[str, Any], kind: str) -> bool:
    if "$ref" in branch:
        return kind == "object"
    expected = branch.get("type")
    return expected == kind or (expected == "number" and kind == "integer")


def _describe(branches: List[Dict[str, Any]]) -> str:
    return " or ".join("binding" if "$ref" in b else str(b.get("type")) for b in branches)


def _type_matches(expected: str, value: Any) -> bool:
    kind = _json_kind(value)
    return kind == expected or (expected == "number" and kind == "integer")


class _Walker:
    def __init__(self, schema: Dict[str, Any], resolver: Resolver) -> None:
        self.defs = schema["$defs"]
        self.resolver = resolver
        self.errors: List[GenerationError] = []
        self.ids: Set[str] = set()
        self.nodes = 0
        self.depth_reported = False
        self.texts: List[str] = []
        self.link_found = False

    def fail(self, path: str, problem: str, schema: Optional[Dict[str, Any]] = None) -> None:
        example = _example(schema, self.defs) if schema is not None else None
        self.errors.append(GenerationError(path, problem, example))

    def check(self, schema: Dict[str, Any], value: Any, path: str, key: str = "", depth: int = 0) -> None:
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[1]
            if name == "component":
                self.component(value, path, depth)
            elif "type" in self.defs[name].get("properties", {}) and name not in ("handle", "binding"):
                self.component(value, path, depth, expect=name)
            elif name == "handle":
                self.handle(schema, value, path, key, depth)
            elif name == "binding":
                self.binding(schema, value, path, depth)
            else:
                self.check(self.defs[name], value, path, key, depth)
            return
        if "anyOf" in schema:
            self.any_of(schema, value, path, key, depth)
            return
        if "const" in schema:
            if value != schema["const"]:
                self.fail(path, f"must be {schema['const']!r}", schema)
            return
        if "enum" in schema:
            if value not in schema["enum"]:
                self.fail(path, f"{value!r} is not one of {schema['enum']}", schema)
            return
        expected = schema.get("type")
        if expected and not _type_matches(expected, value):
            self.fail(path, f"expected {expected}, got {_json_kind(value)}", schema)
            return
        if expected == "string":
            self.string(schema, value, path)
        elif expected in ("number", "integer"):
            self.number(schema, value, path)
        elif expected == "array":
            self.array(schema, value, path, depth)
        elif expected == "object":
            self.object(schema, value, path, depth)

    def string(self, schema: Dict[str, Any], value: str, path: str) -> None:
        if len(value) < schema.get("minLength", 0):
            self.fail(path, f"shorter than {schema['minLength']} characters", schema)
        elif len(value) > schema["maxLength"]:
            self.fail(path, f"longer than {schema['maxLength']} characters", schema)
        elif "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            self.fail(path, f"does not match pattern {schema['pattern']}", schema)
        if schema.get("pattern") == HANDLE_PATTERN and re.fullmatch(HANDLE_PATTERN, value):
            return
        self.texts.append(value)
        if _contains_link(value):
            self.link_found = True
            self.fail(path, "contains a link, URL, HTML or reference definition, which a model may not write. Use a handle", schema)

    def number(self, schema: Dict[str, Any], value: Any, path: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            self.fail(path, "must be a finite number", schema)
        elif value < schema["minimum"] or value > schema["maximum"]:
            self.fail(path, f"{value} is outside {schema['minimum']} to {schema['maximum']}", schema)

    def array(self, schema: Dict[str, Any], value: List[Any], path: str, depth: int) -> None:
        if len(value) < schema["minItems"]:
            self.fail(path, f"needs at least {schema['minItems']} items", schema)
        if len(value) > schema["maxItems"]:
            self.fail(path, f"has {len(value)} items, at most {schema['maxItems']} allowed", schema)
            value = value[: schema["maxItems"]]
        for index, item in enumerate(value):
            self.check(schema["items"], item, f"{path}[{index}]", "", depth)

    def object(self, schema: Dict[str, Any], value: Dict[str, Any], path: str, depth: int) -> None:
        properties = schema["properties"]
        for name in schema["required"]:
            if name not in value:
                self.fail(f"{path}.{name}" if path else name, f"missing required property {name!r}", properties[name])
        for name, item in value.items():
            child = f"{path}.{name}" if path else name
            if name not in properties:
                self.fail(child, f"property {name!r} is not allowed here", schema)
            else:
                self.check(properties[name], item, child, name, depth)

    def any_of(self, schema: Dict[str, Any], value: Any, path: str, key: str, depth: int) -> None:
        branches = schema["anyOf"]
        kind = _json_kind(value)
        chosen = next((b for b in branches if _branch_accepts(b, kind)), None)
        if chosen is None:
            self.fail(path, f"expected {_describe(branches)}, got {kind}", schema)
            return
        self.check(chosen, value, path, key, depth)

    def binding(self, schema: Dict[str, Any], value: Any, path: str, depth: int) -> None:
        self.check(self.defs["binding"], value, path, "", depth)
        if not isinstance(value, dict) or not isinstance(value.get("bind"), dict):
            return
        event, pointer = value["bind"].get("event"), value["bind"].get("path")
        if isinstance(event, str) and isinstance(pointer, str) and not self.resolver.binding_resolves(event, pointer):
            self.fail(path, f"binding to event {event!r} path {pointer!r} does not resolve", schema)

    def handle(self, schema: Dict[str, Any], value: Any, path: str, key: str, depth: int) -> None:
        self.check(self.defs["handle"], value, path, "", depth)
        if not isinstance(value, dict) or not isinstance(value.get("handle"), str):
            return
        handle = value["handle"]
        if key == "capability":
            if not self.resolver.knows_capability(handle):
                self.fail(path, f"capability {handle!r} was not created with this surface", schema)
        elif not self.resolver.knows_handle(handle):
            self.fail(path, f"handle {handle!r} cannot be resolved by the host", schema)

    def component(self, value: Any, path: str, depth: int, expect: str = "") -> None:
        if not isinstance(value, dict):
            self.fail(path, f"expected a component object, got {_json_kind(value)}", self.defs["component"])
            return
        wire_type = value.get("type")
        if expect and wire_type != expect:
            self.fail(path, f"expected a {expect!r} component, got type {wire_type!r}", self.defs[expect])
            return
        if wire_type in EXCLUDED_TYPES:
            self.fail(path, f"type {wire_type!r} cannot be generated: {EXCLUDED_TYPES[wire_type]}", self.defs["text"])
            return
        if not isinstance(wire_type, str) or wire_type not in self.defs or wire_type in ("component", "handle", "binding"):
            known = sorted(entry["$ref"].rsplit("/", 1)[1] for entry in self.defs["component"]["oneOf"])
            self.fail(path, f"unknown component type {wire_type!r}. Valid types: {', '.join(known)}", self.defs["text"])
            return
        self.nodes += 1
        if self.nodes == MAX_NODES + 1:
            self.fail(path, f"tree has more than {MAX_NODES} nodes", None)
        if depth + 1 > MAX_DEPTH:
            if not self.depth_reported:
                self.depth_reported = True
                self.fail(path, f"nesting is deeper than {MAX_DEPTH} levels", None)
            return
        node_id = value.get("id")
        if isinstance(node_id, str):
            if node_id in self.ids:
                self.fail(f"{path}.id" if path else "id", f"id {node_id!r} is used more than once", self.defs[wire_type]["properties"]["id"])
            self.ids.add(node_id)
        self.object(self.defs[wire_type], value, path, depth + 1)


@lru_cache(maxsize=1)
def _profile() -> Dict[str, Any]:
    return strict_schema()


def validate_generated(tree: Any, resolver: Resolver) -> List[GenerationError]:
    schema = _profile()
    walker = _Walker(schema, resolver)
    walker.component(tree, "", 0)
    if not walker.link_found and _contains_link("\n\n".join(walker.texts)):
        walker.fail("", "free text fields combine into a link or reference definition", None)
    return walker.errors
