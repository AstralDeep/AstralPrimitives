"""Check independently authored released wire fixtures and boundary acceptance cases.
The bounded regression gate mutates known guards and runs these same public APIs.
"""

import json
from datetime import date
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

import astralprims
from astralprims import (
    BarChart,
    Button,
    ChartDataset,
    Container,
    LineChart,
    Primitive,
    PrimitiveTypeCollisionError,
    Text,
    create_ui_response,
)


FIXTURES = Path(__file__).parent / "fixtures" / "released_wire.json"


def test_released_wire_fixtures():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert cases
    for case in cases:
        primitive = Primitive.from_dict(case["input"])
        assert primitive.to_dict() == case["expected"]
        assert primitive.model_dump() == case["expected"]
        assert json.loads(primitive.to_json()) == case["expected"]
        assert list(primitive.to_dict())[0] == "type"


def test_trusted_attributes_override_declared_fields():
    assert Button(
        label="declared", attributes={"label": "trusted", "type": "trusted_type"}
    ).to_dict() == {
        "type": "trusted_type",
        "label": "trusted",
        "action": "",
        "payload": {},
        "variant": "primary",
    }


def test_registry_collision_keeps_original_and_adapter():
    adapter = astralprims.primitive_adapter
    with pytest.raises(PrimitiveTypeCollisionError):

        class Collision(Primitive):
            type: Literal["text"] = "text"

    assert type(Primitive.from_dict({"type": "text"})) is Text
    assert astralprims.primitive_adapter is adapter
    assert type(adapter.validate_python({"type": "text"})) is Text


def test_mixed_chart_helpers_have_literal_wire():
    expected = {
        "type": "bar_chart",
        "title": "",
        "labels": [],
        "datasets": [
            {"label": "Helper", "data": [1.0, -2.5]},
            {"nested": {"day": "2026-01-02", "pair": [1, None]}},
        ],
    }
    for collection in (list, tuple, iter):
        try:
            chart = BarChart(
                datasets=collection(
                    [
                        ChartDataset(label="Helper", data=[1, -2.5]),
                        {"nested": {"day": date(2026, 1, 2), "pair": (1, None)}},
                    ]
                )
            )
        except ValidationError:
            pytest.fail("declared chart helpers must be accepted in mixed datasets")
        assert chart.to_dict() == expected
        assert create_ui_response([chart]) == {
            "_ui_components": [expected],
            "_data": None,
        }


def test_unrelated_chart_models_are_rejected_without_serializing():
    class Unrelated(BaseModel):
        data: list[float] = [1.0]

        def model_dump(self, **kwargs):
            pytest.fail("unrelated authoring model must not be serialized")

    for collection in (list, tuple, iter):
        for chart_type in (BarChart, LineChart):
            with pytest.raises(ValidationError):
                chart_type(datasets=collection([ChartDataset(), Unrelated()]))


def test_nested_nonfinite_values_never_reach_json():
    for number in (float("nan"), float("inf"), float("-inf")):
        button = Button(payload={"nested": [{"score": number}]})
        for method in (button.to_dict, button.model_dump, button.to_json):
            with pytest.raises(ValueError, match="Non-finite"):
                method()
        with pytest.raises(ValueError, match="Non-finite"):
            Primitive.from_dict(
                {"type": "button", "payload": {"nested": [{"score": number}]}}
            )


def test_json_nonfinite_literals_are_rejected_after_adapter_validation():
    for token in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="Non-finite"):
            astralprims.primitive_adapter.validate_json(
                '{"type":"button","payload":{"nested":[' + token + "]}}"
            ).to_dict()


def test_child_collections_reject_missing_types():
    for collection in (list, tuple, iter):
        with pytest.raises(ValueError):
            Container(children=collection([{"content": "untagged"}]))
    with pytest.raises(ValueError):
        Container().add({"content": "untagged"})


def test_nested_primitives_and_unrelated_payload_models_keep_wire():
    class Payload(BaseModel):
        day: date

    expected = {
        "type": "container",
        "children": [
            {
                "type": "button",
                "label": "",
                "action": "",
                "payload": {"models": [{"day": "2026-01-02"}], "pair": [False, None]},
                "variant": "primary",
            }
        ],
    }
    for collection in (list, tuple, iter):
        primitive = Container(
            children=collection(
                [
                    Button(
                        payload={
                            "models": [Payload(day=date(2026, 1, 2))],
                            "pair": (False, None),
                        }
                    )
                ]
            )
        )
        assert primitive.to_dict() == expected
        assert json.loads(primitive.to_json()) == expected
