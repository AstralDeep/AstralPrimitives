"""Verify the JSON-native wire value policy for arbitrary primitive payload slots.
These regressions cover accepted conversions, typed rejections, non-string mapping
keys, nested occurrences, and to_dict/to_json agreement across the wire APIs.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
from pydantic import BaseModel

from astralprims import (
    Button,
    ChartDataset,
    Container,
    ParamPicker,
    Primitive,
    Table,
    Tabs,
    primitive_adapter,
)


INSTANT = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)
UUID_VALUE = UUID("12345678-1234-5678-1234-567812345678")
CONVERTED_INPUT = {
    "when": INSTANT,
    "day": date(2026, 3, 4),
    "clock": time(5, 6, 7),
    "uid": UUID_VALUE,
    "amount": Decimal("1.5"),
    "raw": "héllo".encode("utf-8"),
}
CONVERTED_WIRE = {
    "when": "2026-01-02T03:04:05.123456+00:00",
    "day": "2026-03-04",
    "clock": "05:06:07",
    "uid": "12345678-1234-5678-1234-567812345678",
    "amount": "1.5",
    "raw": "héllo",
}


class Plain(Enum):
    A = "a"


class Arbitrary:
    pass


@dataclass
class WhenDataclass:
    when: object


class WhenModel(BaseModel):
    when: object


def _wire_slot(wire: dict, field: str, key: str):
    return wire[key] if field == "attributes" else wire["payload"][key]


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_accepted_conversions_are_json_native(field):
    primitive = Button(**{field: dict(CONVERTED_INPUT)})
    wire = primitive.to_dict()

    assert {key: _wire_slot(wire, field, key) for key in CONVERTED_WIRE} == CONVERTED_WIRE
    assert json.loads(primitive.to_json()) == wire
    assert primitive.model_dump() == wire


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_collections_become_json_arrays(field):
    primitive = Button(**{field: {"tags": {"b", "a"}, "pair": (1, 2), "frozen": frozenset([1.5])}})
    wire = primitive.to_dict()

    assert sorted(_wire_slot(wire, field, "tags")) == ["a", "b"]
    assert _wire_slot(wire, field, "pair") == [1, 2]
    assert _wire_slot(wire, field, "frozen") == [1.5]
    assert json.loads(primitive.to_json()) == wire


@pytest.mark.parametrize("field", ["payload", "attributes"])
@pytest.mark.parametrize("method", ["to_dict", "model_dump", "to_json"])
def test_unsupported_values_are_rejected_with_field_paths(field, method):
    primitive = Button(**{field: {"thing": object()}})

    with pytest.raises(ValueError, match=rf"{field}\.thing"):
        getattr(primitive, method)()


@pytest.mark.parametrize("value", [complex(1, 2), timedelta(hours=1), Plain.A, range(3), Arbitrary()])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_unsupported_value_types_are_rejected(value, field):
    primitive = Button(**{field: {"thing": value}})

    with pytest.raises(ValueError, match=rf"{field}\.thing"):
        primitive.to_dict()


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_from_dict_rejects_unsupported_values(field):
    wire = {"type": "button", field: {"thing": object()}}

    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.thing"):
        Primitive.from_dict(wire)
    with pytest.raises(ValueError, match=rf"{field}\.thing"):
        primitive_adapter.validate_python(wire).to_dict()


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_non_utf8_bytes_are_rejected(field):
    primitive = Button(**{field: {"thing": b"\xff"}})

    with pytest.raises(ValueError, match=rf"Non-UTF-8 bytes.*{field}\.thing"):
        primitive.to_dict()
    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.thing"):
        Primitive.from_dict({"type": "button", field: {"thing": b"\xff"}})


@pytest.mark.parametrize(
    "key, expected",
    [(2, "2"), (2.5, "2.5"), (True, "true"), (False, "false"), (None, "null")],
)
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_json_scalar_mapping_keys_are_stringified(key, expected, field):
    primitive = Button(**{field: {"thing": {key: "v"}}})
    wire = primitive.to_dict()

    assert _wire_slot(wire, field, "thing") == {expected: "v"}
    assert json.loads(primitive.to_json()) == wire


@pytest.mark.parametrize("key", [INSTANT, (1, 2), frozenset([1]), Decimal("1.5")])
@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_unsupported_mapping_keys_are_rejected(key, field):
    primitive = Button(**{field: {"thing": {key: "v"}}})

    with pytest.raises(ValueError, match=rf"{field}\.thing\.<key>"):
        primitive.to_dict()
    with pytest.raises(ValueError, match=rf"wire_payload\.{field}\.thing\.<key>"):
        Primitive.from_dict({"type": "button", field: {"thing": {key: "v"}}})


def test_nested_trees_and_tables_are_normalized():
    button = Button(payload={"when": INSTANT})
    tabs = Tabs(tabs=[{"label": "tab", "content": [button]}])
    table = Table(rows=[[INSTANT, "x"], [date(2026, 3, 4)]], source_params={"when": INSTANT})
    picker = ParamPicker(fields=[{"when": INSTANT}])
    wire = Container(children=[tabs, table, picker]).to_dict()
    children = wire["children"]

    assert children[0]["tabs"][0]["content"][0]["payload"]["when"] == "2026-01-02T03:04:05.123456+00:00"
    assert children[1]["rows"] == [["2026-01-02T03:04:05.123456+00:00", "x"], ["2026-03-04"]]
    assert children[1]["source_params"]["when"] == "2026-01-02T03:04:05.123456+00:00"
    assert children[2]["fields"][0]["when"] == "2026-01-02T03:04:05.123456+00:00"
    assert json.loads(json.dumps(wire, allow_nan=False)) == wire


@pytest.mark.parametrize("factory", [WhenModel, WhenDataclass])
def test_expanded_models_and_dataclasses_are_normalized(factory):
    primitive = Button(payload={"nested": [factory(when=INSTANT)]}, attributes={"extra": [factory(when=INSTANT)]})
    wire = primitive.to_dict()

    assert wire["payload"]["nested"] == [{"when": "2026-01-02T03:04:05.123456+00:00"}]
    assert wire["extra"] == [{"when": "2026-01-02T03:04:05.123456+00:00"}]
    assert json.loads(primitive.to_json()) == wire


@pytest.mark.parametrize("field", ["payload", "attributes"])
def test_from_dict_normalizes_wire_input(field):
    wire = {"type": "button", field: {"when": INSTANT, "nums": {2: "v"}}}

    primitive = Primitive.from_dict(wire)

    assert _wire_slot(primitive.to_dict(), field, "when") == "2026-01-02T03:04:05.123456+00:00"
    assert _wire_slot(primitive.to_dict(), field, "nums") == {"2": "v"}


def test_wire_round_trip_is_idempotent_for_normalized_values():
    wire = Button(payload=dict(CONVERTED_INPUT, tags={"a"}, nums={2: "v"})).to_dict()

    reparsed = Primitive.from_dict(wire)

    assert reparsed.to_dict() == wire
    assert primitive_adapter.validate_python(wire).to_dict() == wire
    assert json.loads(reparsed.to_json()) == wire


def test_trusted_attributes_merge_precedence_is_preserved():
    primitive = Button(
        label="declared",
        payload={"when": INSTANT, "label": "payload"},
        attributes={"label": "trusted", "when": "trusted"},
    )
    wire = primitive.to_dict()

    assert wire["label"] == "trusted"
    assert wire["when"] == "trusted"
    assert list(wire)[0] == "type"
    assert Container(children=[primitive]).to_dict()["children"][0]["label"] == "trusted"


def test_reported_button_datetime_payload_profile_is_reproduced():
    primitive = Button(payload={"date": INSTANT})

    dumped = primitive.to_dict()
    assert dumped["payload"]["date"] == "2026-01-02T03:04:05.123456+00:00"
    assert not isinstance(dumped["payload"]["date"], datetime)
    decoded = json.loads(primitive.to_json())
    assert decoded == dumped


def test_kitchen_sink_wire_values_agree_across_json_and_dict():
    primitive = Button(
        payload=dict(
            CONVERTED_INPUT,
            tags={"a", "b"},
            pair=(1, 2),
            nested={"deep": [{"when": INSTANT}, (Decimal("2"),)]},
            nums={2: "int", None: "none", True: "bool"},
        ),
        attributes={"chart": ChartDataset(label="x", data=[1.0, -2.5])},
    )
    wire = primitive.to_dict()

    assert json.loads(primitive.to_json()) == wire
    assert json.loads(json.dumps(wire, allow_nan=False)) == wire
    assert wire["chart"] == {"label": "x", "data": [1.0, -2.5]}
    assert wire["payload"]["nested"]["deep"] == [{"when": "2026-01-02T03:04:05.123456+00:00"}, ["2"]]
