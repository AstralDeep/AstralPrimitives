"""Validate emitted catalogs and messages against pinned stable A2UI schemas without network access.
The fixtures retain their upstream identity, with a Unicode regex engine for upstream UAX31 patterns.
"""

import copy
import json
from pathlib import Path

import pytest
import regex
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from astralprims import Button, Card, Container, Divider, Input, Text, a2ui_catalog, to_a2ui
from astralprims.a2ui import BASIC_CATALOG_ID, CATALOG_ID

FIXTURES = Path(__file__).parent / "fixtures" / "a2ui-v1.0"
BASE = "https://a2ui.org/specification/v1_0/"


@pytest.fixture(autouse=True)
def upstream_unicode_patterns(monkeypatch):
    monkeypatch.setattr("jsonschema._keywords.re", regex)
    monkeypatch.setattr("jsonschema._utils.re", regex)


def _schema(name):
    return json.loads((FIXTURES / name).read_text())


def _registry(catalog):
    schemas = [_schema(name) for name in ("common_types.json", "catalog_definition.json", "agent_to_renderer.json")]
    resources = [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    resources.append((BASE + "catalog.json", Resource.from_contents(catalog)))
    resources.append((catalog["$id"], Resource.from_contents(catalog)))
    resources.extend((uri, Resource.from_contents(Draft202012Validator.META_SCHEMA)) for uri in (
        "https://json-schema.org/draft/2020-12/schema",
    ))
    return Registry().with_resources(resources)


def test_catalog_conforms_to_the_stable_upstream_metaschema():
    catalog = a2ui_catalog()
    validator = Draft202012Validator(_schema("catalog_definition.json"), registry=_registry(catalog))
    assert [error.message for error in validator.iter_errors(catalog)] == []
    assert catalog["$defs"]["anyFunction"] is False
    assert catalog.get("functions", {}) == {}


@pytest.mark.parametrize("catalog_name", ["astral", "basic"])
def test_exports_conform_to_the_stable_upstream_protocol_and_catalog(catalog_name):
    catalog = a2ui_catalog() if catalog_name == "astral" else _schema("basic_catalog.json")
    registry = _registry(catalog)
    message_validator = Draft202012Validator(_schema("agent_to_renderer.json"), registry=registry)
    tree = Container(children=[
        Text(content="Heading", variant="h2"),
        Card(content=[Text(content="Content")]),
        Button(label="Confirm", capability={"handle": "cap1"}, accessible_name="Confirm", spoken="Confirm", compact="Confirm"),
        Input(name="query", placeholder="Search", value="Current", capability={"handle": "cap2"}, accessible_name="Search", spoken="Search", compact="Search"),
        Divider(),
    ])
    messages = to_a2ui(tree, "surface1", catalog=catalog_name)
    assert messages[0]["createSurface"]["catalogId"] == (CATALOG_ID if catalog_name == "astral" else BASIC_CATALOG_ID)
    for message in messages:
        errors = [error.message for error in message_validator.iter_errors(message)]
        assert errors == [], errors


def test_upstream_validation_rejects_old_theme_and_dynamic_keys():
    catalog = a2ui_catalog()
    validator = Draft202012Validator(_schema("agent_to_renderer.json"), registry=_registry(catalog))
    create, update = to_a2ui(Text(content="Safe"), "surface1")
    legacy = copy.deepcopy(create)
    legacy["createSurface"]["theme"] = {"primaryColor": "red"}
    assert not validator.is_valid(legacy)
    legacy = copy.deepcopy(update)
    legacy["updateComponents"]["components"][0]["@unknown"] = True
    assert not validator.is_valid(legacy)
