"""Verifies the strict generation profile is closed and bounded, covers the shipped vocabulary, and that
validate_generated agrees with a stock JSON Schema validator while adding the resolver and tree rules.
"""

import copy

import pytest
from jsonschema import Draft202012Validator

import astralprims
from astralprims import Primitive, StaticResolver, strict_schema, validate_generated
from astralprims.base import _REGISTRY
from astralprims.strict import EXCLUDED_TYPES, MAX_DEPTH, MAX_NODES
from astralprims.validate import _example

SCHEMA = strict_schema()
DEFS = SCHEMA["$defs"]
TYPES = sorted(entry["$ref"].rsplit("/", 1)[1] for entry in DEFS["component"]["oneOf"])
RESOLVER = StaticResolver(
    events={"event1": {"value": 1, "rows": [1, 2]}}, capabilities={"handle1"}, handles={"handle1"}
)


def _walk(schema, path="$"):
    yield path, schema
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in ("properties",):
                for name, sub in value.items():
                    yield from _walk(sub, f"{path}.{name}")
            elif key in ("items",):
                yield from _walk(value, f"{path}[]")
            elif key in ("anyOf", "oneOf"):
                for index, sub in enumerate(value):
                    yield from _walk(sub, f"{path}|{index}")


def _covers(actual, expected):
    if isinstance(expected, dict):
        return all(k in actual and _covers(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_covers(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _node(wire_type):
    return _example(DEFS[wire_type], DEFS)


def test_profile_is_valid_draft_2020_12_and_versioned():
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["x-astralprims-version"] == astralprims.__version__
    assert SCHEMA["x-astralprims-limits"] == {"max_depth": MAX_DEPTH, "max_nodes": MAX_NODES}


def test_every_shipped_type_is_either_generatable_or_excluded_with_a_reason():
    shipped = {t for t, cls in _REGISTRY.items() if cls.__module__.startswith("astralprims.")}
    assert shipped == set(TYPES) | set(EXCLUDED_TYPES)
    assert not set(TYPES) & set(EXCLUDED_TYPES)
    assert all(EXCLUDED_TYPES.values())


def test_nothing_is_open_ended():
    for path, node in _walk(SCHEMA["$defs"]):
        if path == "$" or not isinstance(node, dict) or node.get("oneOf"):
            continue
        if "$ref" in node or "anyOf" in node or "const" in node:
            continue
        kind = node.get("type")
        assert kind in ("string", "integer", "number", "boolean", "array", "object"), path
        if "enum" in node:
            continue
        if kind == "object":
            assert node["additionalProperties"] is False, path
            assert "properties" in node and "required" in node, path
        if kind == "string":
            assert "maxLength" in node, path
        if kind == "array":
            assert "maxItems" in node and "minItems" in node and "items" in node, path
        if kind in ("integer", "number"):
            assert "minimum" in node and "maximum" in node, path


def test_no_free_form_fields_or_urls_exist():
    for wire_type in TYPES:
        properties = DEFS[wire_type]["properties"]
        for banned in ("attributes", "css", "class", "url", "src", "payload", "action", "style"):
            assert banned not in properties, (wire_type, banned)


@pytest.mark.parametrize("wire_type", TYPES)
def test_each_example_is_valid_under_both_validators_and_loads_as_a_primitive(wire_type):
    node = _node(wire_type)
    Draft202012Validator(SCHEMA).validate(node)
    assert validate_generated(node, RESOLVER) == []
    assert _covers(Primitive.from_dict(copy.deepcopy(node)).to_dict(), node)


@pytest.mark.parametrize("wire_type", TYPES)
def test_every_required_property_missing_or_unknown_property_is_rejected_by_both(wire_type):
    node = _node(wire_type)
    mutants = [{**node, "surprise": 1}]
    mutants += [{k: v for k, v in node.items() if k != required} for required in DEFS[wire_type]["required"]]
    validator = Draft202012Validator(SCHEMA)
    for mutant in mutants:
        assert not validator.is_valid(mutant)
        assert validate_generated(mutant, RESOLVER)


def _form_types():
    return [t for t in TYPES if {"spoken", "compact", "accessible_name"} <= set(DEFS[t]["required"])]


def test_actionable_components_require_all_three_forms_and_a_capability():
    actionable = {"button", "input", "param_picker", "file_upload", "color_picker"}
    assert actionable | {"action_group"} == set(_form_types())
    for wire_type in actionable:
        assert "capability" in DEFS[wire_type]["required"]
    assert "capability" not in DEFS["action_group"]["properties"]


@pytest.mark.parametrize("missing", ["accessible_name", "spoken", "compact", "capability"])
def test_a_button_without_a_form_or_capability_is_rejected_with_an_example(missing):
    node = _node("button")
    del node[missing]
    errors = validate_generated(node, RESOLVER)
    assert [e.path for e in errors] == [missing]
    assert "missing" in errors[0].problem
    assert errors[0].example is not None


def test_an_unknown_capability_is_rejected():
    node = _node("button")
    node["capability"] = {"handle": "nope"}
    (error,) = validate_generated(node, RESOLVER)
    assert error.path == "capability" and "not created with this surface" in error.problem


def test_a_binding_must_resolve():
    ok = {"type": "text", "content": {"bind": {"event": "event1", "path": "/rows/1"}}}
    assert validate_generated(ok, RESOLVER) == []
    for bad in (
        {"event": "ghost", "path": ""},
        {"event": "event1", "path": "/rows/9"},
        {"event": "event1", "path": "/missing"},
    ):
        (error,) = validate_generated({"type": "text", "content": {"bind": bad}}, RESOLVER)
        assert "does not resolve" in error.problem and error.path == "content"


def test_a_malformed_binding_reports_structure_not_resolution():
    errors = validate_generated({"type": "text", "content": {"bind": {"event": "event1"}}}, RESOLVER)
    assert [e.path for e in errors] == ["content.bind.path"]


def test_images_and_links_must_be_resolvable_handles():
    image = {"type": "image", "source": {"handle": "handle1"}, "alt": "chart"}
    assert validate_generated(image, RESOLVER) == []
    (error,) = validate_generated({**image, "source": {"handle": "other"}}, RESOLVER)
    assert "cannot be resolved" in error.problem
    errors = validate_generated({"type": "image", "url": "https://x.example/a.png", "alt": "a"}, RESOLVER)
    assert {e.path for e in errors} == {"url", "source"}
    (error,) = validate_generated({"type": "image", "source": "https://x.example/a.png", "alt": "a"}, RESOLVER)
    assert "expected object" in error.problem


LINK_BYPASSES = [
    "see https://evil.example/x?d=1",
    "[click](javascript:x)",
    "![img](a.png)",
    "mailto:a@b.c",
    "[x][1]\n\n[1]: http://evil.example",
    "[1]: evil.example/page",
    "   [ref]: //evil.example",
    "<https://evil.example>",
    "<a@b.c>",
    "<mailto:a@b.c>",
    "go to //evil.example/path",
    "(//evil.example)",
    "visit www.evil.example",
    "data:text/html;base64,AAAA",
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "tel:+15555550100",
    "ftp://host/file",
    "see ftp:files",
    "s3://bucket/key",
    "vbscript:x",
    "file:///etc/passwd",
    "> [1]: https://evil.example",
    "- [1]: https://evil.example",
    "1. [1]: https://evil.example",
    "> - 1. > [1]: https://evil.example",
    "text\n\n  > [x]: //evil.example",
    "<a href=\"https://evil.example\">x</a>",
    "<img src=x onerror=y>",
    "<div>block</div>",
    "plain https://evil.example/path?q=1 inside",
    "www.evil.com",
    "<script>x</script>",
]
PROSE_THAT_PASSES = [
    "Note: take with food",
    "Meeting at 10:30 and 11:45",
    "Ratio 3:1 and a/b or and/or",
    "Data: 5 samples, Time: now",
    "Dose is 5 mg [see label] daily",
    "Use a // comment in code",
    "Items: [a], [b]",
    "a < b and c > d",
    "metadata:value",
    "Result (see table) www is not a link",
    "Edit main.py and readme.md then run script.sh",
    "Call 555-0100 at 9:15 [ext: 12], then (re)check",
    "Values: x[1], y[2] and 1. first 2. second",
    "Risk > 5% and benefit < 3%",
]


@pytest.mark.parametrize("text", LINK_BYPASSES)
def test_text_may_not_carry_links(text):
    (error,) = validate_generated({"type": "text", "content": text}, RESOLVER)
    assert "link" in error.problem


@pytest.mark.parametrize("text", PROSE_THAT_PASSES)
def test_ordinary_prose_is_not_mistaken_for_a_link(text):
    assert validate_generated({"type": "text", "content": text}, RESOLVER) == []


def test_link_scan_runs_on_every_free_text_field():
    for node in (
        {"type": "alert", "message": "www.evil.example"},
        {"type": "card", "title": "[x](http://e.example)"},
        {"type": "list", "items": [{"title": "ok", "description": "<https://a.example>"}]},
        {"type": "table", "headers": ["h"], "rows": [["tel:123"]]},
    ):
        assert any("link" in e.problem for e in validate_generated(node, RESOLVER)), node


def test_a_definition_in_one_field_and_a_usage_in_another_cannot_combine():
    tree = {
        "type": "container",
        "children": [
            {"type": "text", "content": "see [click here][1]"},
            {"type": "card", "title": "ok", "content": [{"type": "text", "content": "fine"}]},
        ],
    }
    assert validate_generated(tree, RESOLVER) == []
    tree["children"][1]["title"] = "[1]: x"
    errors = validate_generated(tree, RESOLVER)
    assert errors and all("link" in e.problem or "reference" in e.problem for e in errors)


def test_fields_that_only_form_a_link_together_are_rejected_as_a_whole(monkeypatch):
    from astralprims import validate

    seen = []
    real = validate._contains_link
    monkeypatch.setattr(validate, "_contains_link", lambda text: seen.append(text) or (False if "\n\n" not in text else True))
    errors = validate_generated(
        {"type": "container", "children": [{"type": "text", "content": "a"}, {"type": "text", "content": "b"}]},
        RESOLVER,
    )
    assert errors[0].path == "" and "combine" in errors[0].problem
    assert seen[-1] == "a\n\nb" and real("a") is False


def test_link_scan_also_runs_when_a_pattern_field_fails_its_pattern():
    errors = validate_generated({"type": "text", "content": "x", "id": "bad id https://e.example"}, RESOLVER)
    assert errors


def test_a_trailing_newline_cannot_pass_an_anchored_pattern():
    assert validate_generated({"type": "text", "content": "x", "id": "ok\n"}, RESOLVER)
    assert validate_generated({"type": "input", "name": "field\n"}, RESOLVER)
    ok = {"type": "image", "source": {"handle": "handle1\n"}, "alt": "a"}
    assert validate_generated(ok, RESOLVER)


def test_provenance_can_only_claim_model():
    (error,) = validate_generated({"type": "text", "content": "x", "provenance": "host"}, RESOLVER)
    assert error.path == "provenance"
    assert validate_generated({"type": "text", "content": "x", "provenance": "model"}, RESOLVER) == []


def test_excluded_and_unknown_types_are_refused_with_guidance():
    (error,) = validate_generated({"type": "plotly_chart"}, RESOLVER)
    assert "cannot be generated" in error.problem
    (error,) = validate_generated({"type": "marquee"}, RESOLVER)
    assert "Valid types" in error.problem and error.example == {"type": "text", "content": "x"}
    assert validate_generated("text", RESOLVER)[0].problem.startswith("expected a component object")
    assert validate_generated({}, RESOLVER)


def test_nested_paths_and_duplicate_ids_are_reported():
    tree = {
        "type": "container",
        "children": [
            {"type": "text", "content": "a", "id": "same"},
            {"type": "card", "content": [{"type": "text", "content": 5, "id": "same"}]},
        ],
    }
    errors = {e.path: e for e in validate_generated(tree, RESOLVER)}
    assert set(errors) == {"children[1].content[0].content", "children[1].content[0].id"}
    assert "expected" in errors["children[1].content[0].content"].problem
    assert "more than once" in errors["children[1].content[0].id"].problem


def test_action_group_buttons_are_checked_as_buttons():
    group = {
        "type": "action_group",
        "accessible_name": "Actions",
        "spoken": "actions",
        "compact": "Acts",
        "buttons": [_node("button"), {"type": "text", "content": "x"}],
    }
    (error,) = validate_generated(group, RESOLVER)
    assert error.path == "buttons[1]" and "'button'" in error.problem


def test_bounds_are_enforced():
    cases = [
        {"type": "text", "content": "x" * 4001},
        {"type": "progress", "value": 1.5},
        {"type": "progress", "value": float("nan")},
        {"type": "progress", "value": True},
        {"type": "grid", "columns": 99},
        {"type": "divider", "variant": "wavy"},
        {"type": "list", "items": ["x"] * 101},
        {"type": "container", "children": [{"type": "divider"}] * 51},
        {"type": "table", "headers": [], "rows": []},
        {"type": "text", "content": "x", "id": "bad id"},
    ]
    for case in cases:
        assert validate_generated(case, RESOLVER), case


def test_depth_and_node_limits():
    deep = {"type": "divider"}
    for _ in range(MAX_DEPTH):
        deep = {"type": "container", "children": [deep]}
    (error,) = validate_generated(deep, RESOLVER)
    assert "deeper" in error.problem
    wide = {"type": "container", "children": [{"type": "container", "children": [{"type": "divider"}] * 50}] * 7}
    assert any("more than" in e.problem for e in validate_generated(wide, RESOLVER))


def test_union_fields_accept_each_branch_and_name_the_mismatch():
    assert validate_generated({"type": "list", "items": ["a", {"title": "b"}]}, RESOLVER) == []
    (error,) = validate_generated({"type": "list", "items": [5]}, RESOLVER)
    assert "expected string or object, got integer" in error.problem
    (error,) = validate_generated({"type": "text", "content": 5}, RESOLVER)
    assert "string or binding" in error.problem


def test_a_realistic_surface_validates_and_round_trips():
    tree = {
        "type": "container",
        "direction": "column",
        "children": [
            {"type": "text", "variant": "h2", "content": "Blood pressure"},
            {"type": "metric", "title": "Systolic", "value": {"bind": {"event": "event1", "path": "/value"}}},
            _node("button"),
        ],
    }
    assert validate_generated(tree, RESOLVER) == []
    assert Primitive.from_dict(copy.deepcopy(tree)).to_dict()["children"][2]["capability"] == {"handle": "handle1"}


def test_static_resolver_handles_escapes_and_roots():
    resolver = StaticResolver(events={"e": {"a/b": {"~": [0]}}})
    assert resolver.binding_resolves("e", "")
    assert resolver.binding_resolves("e", "/a~1b/~0/0")
    assert not resolver.binding_resolves("e", "/a~1b/~0/1")
    assert not resolver.knows_capability("x") and not resolver.knows_handle("x")
