"""Covers the A2UI v1.0 catalog and the two translations: an outside agent's surface imports as untrusted
primitives with unsupported parts neutralised, and primitives export to both the Astral and basic catalogs.
"""

import copy

import pytest
from jsonschema import Draft202012Validator

import astralprims
from astralprims import (
    A2UIError,
    Button,
    Card,
    Container,
    Primitive,
    StaticResolver,
    Text,
    a2ui_catalog,
    from_a2ui,
    strict_schema,
    to_a2ui,
    validate_generated,
)
from astralprims.a2ui import CATALOG_ID, MAX_COMPONENTS
from astralprims.validate import _example

CATALOG = a2ui_catalog()


def _surface(components, data=None, extra=None):
    create = {"surfaceId": "s1", "catalogId": "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"}
    messages = [{"version": "1.0", "createSurface": create}]
    messages.append({"version": "1.0", "updateComponents": {"surfaceId": "s1", "components": components}})
    if data is not None:
        messages.append({"version": "1.0", "updateDataModel": {"surfaceId": "s1", "path": "/", "value": data}})
    return messages + (extra or [])


def _walk(node):
    yield node
    for key in ("children", "content", "buttons"):
        for child in node.get(key) or []:
            if isinstance(child, dict):
                yield from _walk(child)


def test_catalog_is_a_valid_schema_covering_the_strict_vocabulary():
    Draft202012Validator.check_schema(CATALOG)
    assert CATALOG["catalogId"] == CATALOG["$id"] == CATALOG_ID
    assert CATALOG["protocolVersion"] == "1.0"
    assert set(CATALOG) <= {
        "$schema", "$id", "protocolVersion", "title", "description", "catalogId", "instructions",
        "metadata", "components", "functions", "$defs",
    }
    strict_types = {e["$ref"].rsplit("/", 1)[1] for e in strict_schema()["$defs"]["component"]["oneOf"]}
    assert len(CATALOG["components"]) == len(strict_types)
    for name, schema in CATALOG["components"].items():
        assert schema["properties"]["component"] == {"const": name}
        assert {"component", "id"} <= set(schema["required"])
    assert CATALOG["metadata"]["astralprimsVersion"] == astralprims.__version__


def _catalog_validator(name):
    return Draft202012Validator(
        {"$ref": f"#/components/{name}", "components": CATALOG["components"], "$defs": CATALOG["$defs"]}
    )


def test_exported_components_validate_against_the_published_catalog():
    defs = strict_schema()["$defs"]
    tree = Container(children=[_example(defs[t], defs) and Primitive.from_dict(_example(defs[t], defs)) for t in
                               ("text", "button", "metric", "table", "image", "progress")])
    messages = to_a2ui(tree, "s1")
    assert messages[0]["createSurface"]["catalogId"] == CATALOG_ID
    for component in messages[1]["updateComponents"]["components"]:
        errors = list(_catalog_validator(component["component"]).iter_errors(component))
        assert errors == [], (component, [e.message for e in errors])


def test_astral_export_import_round_trip_is_untrusted_and_lossless_for_fields():
    tree = Container(
        direction="column",
        children=[
            Text(content="Hello", variant="h2"),
            Text(content={"bind": {"event": "ev1", "path": "/a/0"}}),
            Card(title="T", content=[Text(content="inner")]),
            Button(label="Go", capability={"handle": "cap1"}, accessible_name="Go", spoken="go", compact="Go"),
        ],
    )
    surface = from_a2ui(to_a2ui(tree, "s1"))
    assert surface.untrusted and surface.surface_id == "s1" and surface.catalog_id == CATALOG_ID
    wire = surface.root.to_dict()
    assert all(n["provenance"] == "external" for n in _walk(wire))
    assert wire["children"][0]["content"] == "Hello"
    assert wire["children"][1]["content"] == {"bind": {"event": "ev1", "path": "/a/0"}}
    assert wire["children"][2]["content"][0]["content"] == "inner"
    button = wire["children"][3]
    assert "capability" not in button and button["accessible_name"] == "Go"
    assert any("capability" in n for n in surface.notices)


def test_export_ids_are_valid_unique_and_root_comes_first():
    tree = Container(children=[Text(content="a", id="my-id"), Text(content="b", id="my-id"), Text(content="c")])
    components = to_a2ui(tree, "s1")[1]["updateComponents"]["components"]
    ids = [c["id"] for c in components]
    assert ids[0] == "root" and len(ids) == len(set(ids)) == 4
    assert "my_id" in ids


def test_export_to_the_basic_catalog_maps_and_falls_back_to_text():
    tree = Container(
        direction="row",
        children=[
            Text(content="Title", variant="h1"),
            Card(content=[Text(content="x")]),
            Button(label="Run", variant="secondary", capability={"handle": "cap1"}, accessible_name="Run"),
            Primitive.from_dict({"type": "gauge", "label": "Load", "value": 0.4}),
            Primitive.from_dict({"type": "input", "placeholder": "Name", "name": "n"}),
            Primitive.from_dict({"type": "divider"}),
        ],
    )
    messages = to_a2ui(tree, "s1", catalog="basic")
    assert messages[0]["createSurface"]["catalogId"].endswith("basic/catalog.json")
    by_id = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert by_id["root"]["component"] == "Row"
    kinds = [by_id[i]["component"] for i in by_id["root"]["children"]]
    assert kinds == ["Text", "Card", "Button", "Text", "TextField", "Divider"]
    button = by_id[by_id["root"]["children"][2]]
    assert button["variant"] == "borderless" and button["action"]["event"]["name"] == "cap1"
    assert by_id[button["child"]]["text"] == "Run"
    assert by_id[by_id["root"]["children"][3]]["text"] == "Load"


def test_export_rejects_bad_arguments():
    with pytest.raises(A2UIError):
        to_a2ui(Text(content="x"), "s1", catalog="other")
    with pytest.raises(A2UIError):
        to_a2ui(Text(content="x"), "bad id")
    assert to_a2ui({"type": "text", "content": "x"}, "s1")[1]["updateComponents"]["components"][0]["id"] == "root"


def test_import_of_basic_catalog_surface_with_data_binding():
    messages = _surface(
        [
            {"id": "root", "component": "Column", "children": ["title", "greet", "card", "btn", "field", "div"]},
            {"id": "title", "component": "Text", "text": "Hi", "variant": "h1"},
            {"id": "greet", "component": "Text", "text": {"@path": "/user/name"}},
            {"id": "card", "component": "Card", "child": "inner"},
            {"id": "inner", "component": "Text", "text": {"@call": "formatString", "args": {"value": "Hello, ${/user/name}!"}}},
            {"id": "btn", "component": "Button", "child": "btnlabel", "variant": "borderless",
             "action": {"event": {"name": "save", "context": {"who": {"@path": "/user/name"}}}}},
            {"id": "btnlabel", "component": "Text", "text": "Save"},
            {"id": "field", "component": "TextField", "label": "Name", "value": {"@path": "/user/name"}},
            {"id": "div", "component": "Divider"},
        ],
        data={"user": {"name": "Ada"}},
    )
    surface = from_a2ui(messages)
    wire = surface.root.to_dict()
    kids = wire["children"]
    assert wire["direction"] == "column" and wire["provenance"] == "external"
    assert [k["type"] for k in kids] == ["text", "text", "card", "button", "input", "divider"]
    assert kids[0]["variant"] == "h1" and kids[1]["content"] == "Ada"
    assert kids[2]["content"][0]["content"] == "Hello, Ada!"
    assert kids[3]["label"] == "Save" and kids[3]["action"] == "save" and kids[3]["payload"] == {"who": "Ada"}
    assert kids[3]["variant"] == "secondary" and kids[4]["value"] == "Ada"
    assert all(n["provenance"] == "external" for n in _walk(wire))
    assert surface.root.id == "root"


def test_data_model_updates_apply_in_order_and_null_removes():
    messages = _surface(
        [{"id": "root", "component": "Text", "text": {"@path": "/a/b"}}],
        data={"a": {"b": "one"}},
        extra=[
            {"version": "1.0", "updateDataModel": {"surfaceId": "s1", "path": "/a/b", "value": "two"}},
        ],
    )
    assert from_a2ui(messages).root.content == "two"
    messages.append({"version": "1.0", "updateDataModel": {"surfaceId": "s1", "path": "/a/b", "value": None}})
    assert from_a2ui(messages).root.content == ""


@pytest.mark.parametrize("name", ["Video", "Image", "Modal", "Tabs", "Slider", "Mystery"])
def test_unsupported_components_become_safe_text(name):
    surface = from_a2ui(_surface([
        {"id": "root", "component": "Column", "children": ["x"]},
        {"id": "x", "component": name, "url": "https://evil.example/a.png", "text": "<script>"},
    ]))
    node = surface.root.to_dict()["children"][0]
    assert node["type"] == "text" and node["variant"] == "muted" and node["provenance"] == "external"
    assert "evil" not in str(node) and "script" not in str(node)
    assert surface.notices


def test_hostile_component_names_are_sanitised_in_placeholder_text():
    surface = from_a2ui(_surface([{"id": "root", "component": "<b>[x](http://e)</b>"}]))
    assert surface.root.content == "[unsupported component: bxhttpe]" or "http://" not in surface.root.content


def test_dynamic_values_that_cannot_be_resolved_are_dropped_with_a_notice():
    surface = from_a2ui(_surface([
        {"id": "root", "component": "Text", "text": {"@call": "openUrl", "args": {"url": "http://e"}}},
    ]))
    assert surface.root.content == "" and any("dynamic" in n for n in surface.notices)
    escaped = from_a2ui(_surface([{"id": "root", "component": "Text", "text": "@@literal"}]))
    assert escaped.root.content == "@literal"


def test_template_children_and_function_actions_are_dropped():
    surface = from_a2ui(_surface([
        {"id": "root", "component": "List", "children": {"path": "/items", "componentId": "t"}},
    ]))
    assert surface.root.children == [] and any("template" in n for n in surface.notices)
    surface = from_a2ui(_surface([
        {"id": "root", "component": "Button", "child": "l", "action": {"functionCall": {"@call": "openUrl", "args": {}}}},
        {"id": "l", "component": "Text", "text": "Open"},
    ]))
    assert surface.root.action == "" and any("function" in n for n in surface.notices)


def test_astral_catalog_import_strips_urls_styles_capabilities_and_unknown_keys():
    surface = from_a2ui(_surface([
        {"id": "root", "component": "AstralContainer", "children": ["img", "b"], "css": {"x": "y"}, "extra": 1},
        {"id": "img", "component": "AstralImage", "url": "https://evil.example/a.png", "source": {"handle": "h"}, "alt": "a"},
        {"id": "b", "component": "AstralButton", "label": "Go", "capability": {"handle": "c"}, "provenance": "host"},
    ]))
    wire = surface.root.to_dict()
    assert "css" not in wire and "extra" not in wire
    image, button = wire["children"]
    assert image.get("url", "") == "" and image["source"] == {"handle": "h"}
    assert "capability" not in button and button["provenance"] == "external"
    assert wire["provenance"] == "external"


def test_invalid_astral_properties_fall_back_to_text():
    surface = from_a2ui(_surface([
        {"id": "root", "component": "AstralText", "content": 5},
    ]))
    assert surface.root.to_dict()["type"] == "text" and surface.root.content.startswith("[invalid")


def test_astral_tabs_and_events_bindings_import():
    surface = from_a2ui(_surface([
        {"id": "root", "component": "AstralTabs", "tabs": [{"label": "A", "content": ["t"]}]},
        {"id": "t", "component": "AstralText", "content": {"@path": "/events/e1/x"}},
    ]))
    tab = surface.root.to_dict()["tabs"][0]
    assert tab["content"][0]["content"] == {"bind": {"event": "e1", "path": "/x"}}
    other = from_a2ui(_surface(
        [{"id": "root", "component": "AstralText", "content": {"@path": "/user"}}], data={"user": "u"}
    ))
    assert other.root.content == "u" and any("outside /events" in n for n in other.notices)


@pytest.mark.parametrize(
    "messages, fragment",
    [
        ([], "non-empty"),
        ("x", "non-empty"),
        ([{"version": "0.9", "createSurface": {"surfaceId": "s"}}], "1.0 message"),
        ([{"version": "1.0"}], "exactly one"),
        ([{"version": "1.0", "createSurface": {"surfaceId": "s"}, "deleteSurface": {"surfaceId": "s"}}], "exactly one"),
        ([{"version": "1.0", "createSurface": {}}], "surfaceId"),
        ([{"version": "1.0", "createSurface": {"surfaceId": "s"}}], "no root"),
        ([{"version": "1.0", "updateDataModel": {"surfaceId": "s"}}], "value"),
        ([{"version": "1.0", "updateComponents": {"surfaceId": "s", "components": [{"id": "bad-id", "component": "Text"}]}}], "valid id"),
        ([{"version": "1.0", "updateComponents": {"surfaceId": "s", "components": [{"id": "root"}]}}], "component name"),
        ([{"version": "1.0", "updateComponents": {"surfaceId": "s", "components": ["x"]}}], "valid id"),
        ([{"version": "1.0", "updateComponents": {"surfaceId": "s", "components": [{"id": "root", "component": "Column", "children": ["gone"]}]}}], "not defined"),
        ([{"version": "1.0", "updateComponents": {"surfaceId": "s", "components": [{"id": "root", "component": "Column", "children": ["root"]}]}}], "contains itself"),
    ],
)
def test_malformed_surfaces_are_refused(messages, fragment):
    with pytest.raises(A2UIError, match=fragment):
        from_a2ui(messages)


def test_other_failure_modes_are_refused():
    base = _surface([{"id": "root", "component": "Divider"}])
    other = copy.deepcopy(base[1])
    other["updateComponents"]["surfaceId"] = "s2"
    with pytest.raises(A2UIError, match="more than one surface"):
        from_a2ui(base + [other])
    with pytest.raises(A2UIError, match="no root"):
        from_a2ui(base + [{"version": "1.0", "deleteSurface": {"surfaceId": "s1"}}])
    many = [{"id": f"c{i}", "component": "Divider"} for i in range(MAX_COMPONENTS + 1)]
    with pytest.raises(A2UIError, match="more than"):
        from_a2ui(_surface(many))
    chain = [{"id": "root", "component": "Card", "child": "c0"}]
    chain += [{"id": f"c{i}", "component": "Card", "child": f"c{i + 1}"} for i in range(30)]
    chain.append({"id": "c30", "component": "Divider"})
    with pytest.raises(A2UIError, match="deeper"):
        from_a2ui(_surface(chain))


def test_imported_trees_are_not_accepted_as_generated_trees():
    surface = from_a2ui(_surface([{"id": "root", "component": "Text", "text": "x"}]))
    errors = validate_generated(surface.root.to_dict(), StaticResolver())
    assert any(e.path == "provenance" for e in errors)
