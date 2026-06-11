import json

import pytest
from pydantic import ValidationError

from astralprims import (
    Audio,
    Badge,
    BarChart,
    Button,
    Card,
    Collapsible,
    Container,
    Grids,
    Hero,
    KeyValue,
    ParamPicker,
    Primitive,
    ProgressBar,
    Rating,
    Table,
    TabItem,
    Tabs,
    Text,
    Timeline,
    create_ui_response,
    primitive_adapter,
)


# -- base behaviors ------------------------------------------------------


def test_button_to_dict_shape():
    btn = Button(
        label="the button text",
        action="open",
        css={"background-color": "white", "color": "#000000"},
    )
    out = btn.to_dict()
    assert out["type"] == "button"
    assert out["css"] == {"background-color": "white", "color": "#000000"}
    assert out["label"] == "the button text"
    assert out["action"] == "open"


def test_none_fields_are_dropped():
    # tooltip/id default to None and must not appear.
    out = Text(content="hi").to_dict()
    assert "tooltip" not in out
    assert "id" not in out


def test_empty_css_is_omitted():
    assert "css" not in Text(content="hello").to_dict()


def test_to_json_roundtrips_with_to_dict():
    btn = Button(label="x", action="go")
    assert json.loads(btn.to_json()) == btn.to_dict()


def test_extra_attributes_are_merged():
    btn = Button(label="x", attributes={"data-testid": "buy"})
    assert btn.to_dict()["data-testid"] == "buy"


def test_class_name_is_remapped():
    assert Text(content="x", class_name="muted").to_dict()["class"] == "muted"


# -- nesting -------------------------------------------------------------


def test_container_nests_children():
    out = Container(css={"display": "flex"}).add(
        Text(content="hi"), Button(label="ok", action="go")
    ).to_dict()
    assert [c["type"] for c in out["children"]] == ["text", "button"]


def test_card_nests_content():
    out = Card(title="t").add(Button(label="ok", action="go")).to_dict()
    assert out["content"][0]["type"] == "button"


def test_grid_nests_children():
    out = Grids(columns=3).add(Text(content="a"), Text(content="b")).to_dict()
    assert out["columns"] == 3
    assert len(out["children"]) == 2


def test_collapsible_nests_content():
    out = Collapsible(title="more", content=[Text(content="hidden")]).to_dict()
    assert out["content"][0]["content"] == "hidden"


def test_tabs_serialize_tabitems_and_their_content():
    tabs = Tabs(tabs=[TabItem(label="One", content=[Text(content="body")])])
    out = tabs.to_dict()
    assert out["tabs"][0]["label"] == "One"
    assert out["tabs"][0]["content"][0]["type"] == "text"
    # None value on the TabItem is dropped by the generic dataclass serializer.
    assert "value" not in out["tabs"][0]


# -- leaf primitives -----------------------------------------------------


def test_table_pagination_fields():
    out = Table(headers=["a"], rows=[[1]], total_rows=100, page_size=10).to_dict()
    assert out["total_rows"] == 100
    assert out["page_size"] == 10
    assert "source_tool" not in out  # None dropped


def test_audio_defaults():
    out = Audio(src="data:audio/wav;base64,xxx").to_dict()
    assert out["src"].startswith("data:audio")
    assert out["showControls"] is True
    assert "contentType" not in out


def test_param_picker_fields():
    out = ParamPicker(
        title="Train",
        fields=[{"name": "epochs", "kind": "number", "default": 3}],
    ).to_dict()
    assert out["fields"][0]["name"] == "epochs"


def test_bar_chart():
    out = BarChart(title="t", labels=["a", "b"], datasets=[{"label": "s", "data": [1, 2]}]).to_dict()
    assert out["labels"] == ["a", "b"]
    assert out["datasets"][0]["data"] == [1, 2]


def test_badge_shape():
    out = Badge(label="Confirmed", variant="success").to_dict()
    assert out["type"] == "badge"
    assert out["label"] == "Confirmed"
    assert out["variant"] == "success"
    assert "icon" not in out  # None dropped


def test_hero_shape():
    out = Hero(title="Paws & Bubbles", eyebrow="Dashboard",
               subtitle="Today at a glance", badges=["Open", "8 bookings"]).to_dict()
    assert out["type"] == "hero"
    assert out["title"] == "Paws & Bubbles"
    assert out["eyebrow"] == "Dashboard"
    assert out["badges"] == ["Open", "8 bookings"]
    assert "icon" not in out


def test_keyvalue_shape():
    out = KeyValue(title="Business facts",
                   items=[{"label": "Owner", "value": "Sam", "hint": "since 2021"}],
                   columns=3).to_dict()
    assert out["type"] == "keyvalue"
    assert out["columns"] == 3
    assert out["items"][0]["label"] == "Owner"
    assert "title" in out


def test_timeline_shape():
    out = Timeline(items=[{"time": "9:00 AM", "title": "Bella — Full Groom",
                           "variant": "success"}]).to_dict()
    assert out["type"] == "timeline"
    assert out["items"][0]["time"] == "9:00 AM"
    assert "title" not in out  # None dropped


def test_rating_shape():
    out = Rating(value=4.8, label="Customer satisfaction").to_dict()
    assert out["type"] == "rating"
    assert out["value"] == 4.8
    assert out["max_value"] == 5
    assert out["show_value"] is True
    assert "subtitle" not in out


# -- from_dict round-trips ----------------------------------------------


def test_from_dict_unknown_type_raises():
    with pytest.raises(ValueError):
        Primitive.from_dict({"type": "definitely-not-real"})


def test_from_dict_unknown_keys_become_attributes():
    btn = Primitive.from_dict({"type": "button", "label": "x", "data-id": "5"})
    assert btn.attributes == {"data-id": "5"}


def test_from_dict_nested_roundtrip():
    tree = Container().add(
        Card(title="t", content=[Button(label="ok", action="go")])
    )
    restored = Primitive.from_dict(tree.to_dict())
    assert isinstance(restored, Container)
    assert restored.to_dict() == tree.to_dict()


def test_from_dict_tabs_roundtrip():
    tabs = Tabs(tabs=[TabItem(label="One", content=[Text(content="body")])])
    restored = Primitive.from_dict(tabs.to_dict())
    assert isinstance(restored, Tabs)
    assert restored.to_dict() == tabs.to_dict()


def test_from_dict_dashboard_types_roundtrip():
    for prim in (
        Badge(label="New", variant="info"),
        Hero(title="Report", subtitle="Q2", badges=["draft"]),
        KeyValue(items=[{"label": "a", "value": "1"}]),
        Timeline(title="Today", items=[{"time": "9:00", "title": "Open"}]),
        Rating(value=3.5, label="Avg"),
    ):
        restored = Primitive.from_dict(prim.to_dict())
        assert type(restored) is type(prim)
        assert restored.to_dict() == prim.to_dict()


# -- response envelope ---------------------------------------------------


def test_create_ui_response_shape():
    resp = create_ui_response([Text(content="hi"), Button(label="ok", action="go")])
    assert resp["_data"] is None
    assert [c["type"] for c in resp["_ui_components"]] == ["text", "button"]


# -- pydantic validation & schema ---------------------------------------


def test_invalid_field_type_raises():
    with pytest.raises(ValidationError):
        ProgressBar(value="not-a-number")


def test_numeric_string_is_coerced():
    assert ProgressBar(value="42").value == 42.0


def test_button_json_schema_has_const_type():
    prop = Button.model_json_schema()["properties"]["type"]
    assert prop.get("const") == "button" or prop.get("enum") == ["button"]


def test_adapter_validates_to_concrete_type():
    inst = primitive_adapter.validate_python({"type": "button", "label": "x", "action": "go"})
    assert isinstance(inst, Button)
    assert inst.label == "x"


def test_adapter_rejects_unknown_type():
    with pytest.raises(ValidationError):
        primitive_adapter.validate_python({"type": "definitely-not-real"})


def test_adapter_validates_dashboard_types():
    for payload, cls in (
        ({"type": "badge", "label": "x"}, Badge),
        ({"type": "hero", "title": "x"}, Hero),
        ({"type": "keyvalue", "items": [{"label": "a", "value": "1"}]}, KeyValue),
        ({"type": "timeline", "items": [{"title": "x"}]}, Timeline),
        ({"type": "rating", "value": 4}, Rating),
    ):
        assert isinstance(primitive_adapter.validate_python(payload), cls)


def test_adapter_validates_nested_tree():
    data = Container().add(Card(title="t", content=[Button(label="ok", action="go")])).to_dict()
    inst = primitive_adapter.validate_python(data)
    assert isinstance(inst, Container)
    assert isinstance(inst.children[0], Card)
    assert isinstance(inst.children[0].content[0], Button)
    assert inst.to_dict() == data
