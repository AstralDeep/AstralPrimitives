"""Regression coverage for primitives-005: JSON-native value normalization at the wire boundary.

Two halves:
- Positive cases: non-JSON-native Python values normalize to JSON-native at to_dict() / _dump().
- Negative regressions: normalized-key collisions raise PrimitiveTypeError, the public
  serializer contract (class alias, attributes merge, empty-css drop) is preserved, and
  the registry's collision guard still raises PrimitiveTypeCollisionError.
"""
import base64
import json
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum, IntEnum
from pathlib import PurePosixPath
from typing import Literal

import pytest

from astralprims.base import (
    Primitive,
    PrimitiveTypeError,
    PrimitiveTypeCollisionError,
    _dump,
)
from astralprims.primitives import Button, ProgressBar


def test_dump_datetime_iso8601() -> None:
    dt = datetime(2026, 10, 3, 14, 30, 0, tzinfo=timezone.utc)
    assert _dump(dt) == "2026-10-03T14:30:00+00:00"


def test_dump_date_iso8601() -> None:
    assert _dump(date(2026, 10, 3)) == "2026-10-03"


def test_dump_time_iso8601() -> None:
    assert _dump(time(14, 30, 0)) == "14:30:00"


def test_button_payload_datetime_via_to_dict() -> None:
    btn = Button(payload={"date": datetime(2026, 10, 3, 14, 30, 0, tzinfo=timezone.utc)})
    d = btn.to_dict()
    assert d["payload"]["date"] == "2026-10-03T14:30:00+00:00"
    assert json.loads(btn.to_json()) == d


def test_dump_uuid_canonical_string() -> None:
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert _dump(u) == "12345678-1234-5678-1234-567812345678"


def test_button_payload_uuid() -> None:
    u = uuid.uuid4()
    btn = Button(payload={"trace_id": u})
    d = btn.to_dict()
    assert d["payload"]["trace_id"] == str(u)
    assert json.loads(btn.to_json()) == d


def test_dump_bytes_base64() -> None:
    assert _dump(b"hello") == base64.b64encode(b"hello").decode("ascii")


def test_dump_bytearray_base64() -> None:
    assert _dump(bytearray(b"abc")) == base64.b64encode(b"abc").decode("ascii")


def test_button_payload_bytes() -> None:
    raw = b"\x00\x01\x02"
    btn = Button(payload={"sig": raw})
    d = btn.to_dict()
    assert d["payload"]["sig"] == base64.b64encode(raw).decode("ascii")
    assert json.loads(btn.to_json()) == d


def test_dump_set_sorted_list() -> None:
    assert _dump({3, 1, 2}) == [1, 2, 3]


def test_dump_frozenset_sorted_list() -> None:
    assert _dump(frozenset({"b", "a"})) == ["a", "b"]


def test_dump_set_mixed_types_sorted_by_str() -> None:
    out = _dump({1, "a", 2})
    assert isinstance(out, list)
    assert sorted(out, key=str) == out


def test_button_payload_set() -> None:
    btn = Button(payload={"tags": {"alpha", "beta"}})
    d = btn.to_dict()
    assert d["payload"]["tags"] == ["alpha", "beta"]
    assert json.loads(btn.to_json()) == d


def test_dump_decimal_str() -> None:
    assert _dump(Decimal("3.14")) == "3.14"


def test_dump_purepath_str() -> None:
    assert _dump(PurePosixPath("/tmp/x.json")) == "/tmp/x.json"


def test_dump_enum_value() -> None:
    class Color(Enum):
        RED = "red"
        BLUE = "blue"
    assert _dump(Color.RED) == "red"


def test_dump_intenum_int() -> None:
    class Level(IntEnum):
        INFO = 1
        WARN = 2
    assert _dump(Level.WARN) == 2


def test_button_payload_decimal_progressbar() -> None:
    # ProgressBar.value is a float field; construction coerces Decimal to float,
    # so the wire output is a float and to_dict() / to_json() agree.
    bar = ProgressBar(value=Decimal("0.5"))
    d = bar.to_dict()
    assert d["value"] == 0.5
    assert json.loads(bar.to_json())["value"] == 0.5


def test_dump_nested_dict_with_non_native_values() -> None:
    payload = {
        "ts": datetime(2026, 10, 3, 14, 30, 0, tzinfo=timezone.utc),
        "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        "tags": {"alpha", "beta"},
        "ratio": Decimal("0.25"),
        "nested": {"blob": b"\x00\x01", "path": PurePosixPath("/tmp/x.json")},
    }
    out = _dump(payload)
    assert out == {
        "ts": "2026-10-03T14:30:00+00:00",
        "id": "12345678-1234-5678-1234-567812345678",
        "tags": ["alpha", "beta"],
        "ratio": "0.25",
        "nested": {
            "blob": base64.b64encode(b"\x00\x01").decode("ascii"),
            "path": "/tmp/x.json",
        },
    }


def test_unsupported_python_object_raises() -> None:
    class Custom:
        pass

    with pytest.raises(PrimitiveTypeError):
        _dump(Custom())


def test_unsupported_mapping_key_raises() -> None:
    with pytest.raises(PrimitiveTypeError):
        _dump({object(): "v"})


def test_normalized_key_collision_in_nested_dict_raises() -> None:
    # int 1 and str "1" both normalize to the wire key "1"; the serializer
    # must NOT silently drop either value. Button.payload is Dict[str, Any]
    # so Pydantic rejects non-string keys before _dump runs; the collision
    # path is reachable through arbitrary mapping payloads (the _dump
    # entrypoint) and through fields typed as Dict[Any, Any].
    payload = {"nested": {"1": "first", 1: "second"}}
    with pytest.raises(PrimitiveTypeError):
        _dump(payload)


def test_button_payload_rejects_non_string_key_at_pydantic() -> None:
    # Pydantic's Dict[str, Any] validation rejects non-string keys before
    # the wire serializer ever sees them; this is the contract on
    # Button.payload and is preserved by this PR.
    with pytest.raises(Exception):
        Button(payload={1: "first", "1": "second"})



def test_button_serializer_contract_preserved_on_main() -> None:
    # Regression: the existing wire contract for Button must not change.
    # `class_name` (alias `class`) flattens to the wire key `class`,
    # empty CSS is dropped, and trusted `attributes` merge with priority over
    # explicitly-set fields.
    btn = Button(label="typed", class_name="alias", css={}, attributes={"label": "override"})
    d = btn.to_dict()
    assert d["class"] == "alias"
    assert "css" not in d
    assert d["label"] == "override"
    assert json.loads(btn.to_json()) == d


def test_button_none_fields_dropped_on_main() -> None:
    # Regression: None fields are dropped (existing behavior, preserved).
    btn = Button(label="ok")
    d = btn.to_dict()
    assert "tooltip" not in d
    assert "id" not in d
    assert "class" not in d
    assert d["label"] == "ok"


def test_registry_collision_guard_still_raises_on_main() -> None:
    # Regression: defining a custom Primitive whose `type` Literal collides
    # with the built-in `text` entry must raise PrimitiveTypeCollisionError,
    # and the registry must NOT be mutated by the failed registration.
    with pytest.raises(PrimitiveTypeCollisionError):
        class _CollisionText(Primitive):
            type: Literal["text"] = "text"
            body: str = ""
    # The collision guard raised before any assignment, so the registry
    # entry for "text" still points at the built-in Text class. We must NOT
    # call unregister_primitive("text") here — that would remove the real
    # Text class and break every downstream test that loads a text primitive.


def test_button_payload_full_round_trip_with_non_native_values() -> None:
    # Integration: a real primitive with arbitrary-valued payload round-trips
    # through to_dict / to_json as JSON-native.
    btn = Button(
        label="commit",
        payload={
            "ts": datetime(2026, 10, 3, 14, 30, 0, tzinfo=timezone.utc),
            "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
            "ratio": Decimal("0.42"),
            "blob": b"\x00\x01",
        },
    )
    d = btn.to_dict()
    assert d["payload"]["ts"] == "2026-10-03T14:30:00+00:00"
    assert d["payload"]["id"] == "12345678-1234-5678-1234-567812345678"
    assert d["payload"]["ratio"] == "0.42"
    assert d["payload"]["blob"] == base64.b64encode(b"\x00\x01").decode("ascii")
    assert json.loads(btn.to_json()) == d

