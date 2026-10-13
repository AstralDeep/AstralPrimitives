"""Verify ChartDataset authoring helpers for BarChart and LineChart.
Exercise collection validation and the existing dictionary wire contract across
serialization, adapters, and UI response envelopes.
"""

import json
from collections import deque
from datetime import date

import pytest
from pydantic import BaseModel, ValidationError

from astralprims import (
    BarChart,
    ChartDataset,
    Container,
    LineChart,
    Primitive,
    Text,
    create_ui_response,
    primitive_adapter,
)


class UnrelatedDataset(BaseModel):
    label: str = "unrelated"
    data: list[float] = [1.0]

    def model_dump(self, **kwargs):
        raise AssertionError("unrelated dataset serializers must not be called")


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
def test_chart_defaults_and_mutable_fields_are_independent(chart_type):
    first = chart_type()
    second = chart_type()

    assert first.to_dict() == {
        "type": chart_type.model_fields["type"].default,
        "title": "",
        "labels": [],
        "datasets": [],
    }
    first.labels.append("Quarter")
    first.datasets.append({"label": "Sales", "data": [1]})
    assert second.labels == []
    assert second.datasets == []


def test_chart_dataset_defaults_and_data_are_independent():
    first = ChartDataset()
    second = ChartDataset()

    assert first.model_dump() == {"label": "", "data": []}
    first.data.append(1.0)
    assert second.data == []


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
@pytest.mark.parametrize("collection", [list, tuple, iter, deque])
def test_chart_helpers_and_arbitrary_dicts_keep_the_dictionary_wire(chart_type, collection):
    helper = ChartDataset(label="Sales", data=[10, 20], color="#ff0000")
    direct = {"label": "Direct", "data": [5, None], "borderWidth": 2, "custom": {"step": True}}
    chart = chart_type(
        title="Revenue",
        labels=["Q1", "Q2"],
        datasets=collection([helper, direct, ChartDataset()]),
    )
    expected = {
        "type": chart_type.model_fields["type"].default,
        "title": "Revenue",
        "labels": ["Q1", "Q2"],
        "datasets": [
            {"label": "Sales", "data": [10.0, 20.0], "color": "#ff0000"},
            direct,
            {"label": "", "data": []},
        ],
    }

    assert all(isinstance(dataset, dict) for dataset in chart.datasets)
    assert chart.to_dict() == expected
    assert chart.model_dump() == expected
    assert json.loads(chart.to_json()) == expected
    assert chart_type(datasets=[helper.model_dump(), direct, ChartDataset().model_dump()]).datasets == chart.datasets
    helper.data.append(30.0)
    assert chart.datasets[0]["data"] == [10.0, 20.0]


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
def test_chart_helpers_round_trip_through_wire_adapters_and_responses(chart_type):
    chart = chart_type(
        datasets=(ChartDataset(label="Sales", data=[1]), {"custom": date(2026, 1, 2)}),
        class_name="plot",
        tooltip="Annual",
    )
    wire = {
        "type": chart_type.model_fields["type"].default,
        "class": "plot",
        "tooltip": "Annual",
        "title": "",
        "labels": [],
        "datasets": [{"label": "Sales", "data": [1.0]}, {"custom": "2026-01-02"}],
    }

    assert chart.to_dict() == wire
    assert Primitive.from_dict(wire).to_dict() == wire
    assert chart_type.from_dict(wire).to_dict() == wire
    assert primitive_adapter.validate_python(wire).to_dict() == wire
    assert primitive_adapter.validate_json(chart.to_json()).to_dict() == wire
    assert primitive_adapter.validate_python(
        {"type": chart.type, "datasets": (ChartDataset(),)}
    ).datasets == [{"label": "", "data": []}]
    response = create_ui_response([Container(children=[chart])])
    assert response == {
        "_ui_components": [{"type": "container", "children": [wire]}],
        "_data": None,
    }
    assert json.loads(json.dumps(response, allow_nan=False)) == response
    assert Primitive.from_dict(response["_ui_components"][0]).to_dict() == response["_ui_components"][0]


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
@pytest.mark.parametrize("dataset", [UnrelatedDataset(), Text(content="not a dataset"), None, 1, "sales", [1, 2]])
def test_chart_rejects_non_dict_non_helper_items(chart_type, dataset):
    with pytest.raises(ValidationError, match=r"datasets\.0"):
        chart_type(datasets=[dataset])
    with pytest.raises(ValidationError, match=r"datasets\.0"):
        primitive_adapter.validate_python({"type": chart_type.model_fields["type"].default, "datasets": [dataset]})


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
@pytest.mark.parametrize("datasets", [None, 1, "sales", b"sales", {"label": "Sales"}, ChartDataset()])
def test_chart_rejects_malformed_collections(chart_type, datasets):
    with pytest.raises(ValidationError, match="datasets"):
        chart_type(datasets=datasets)


@pytest.mark.parametrize("data", [None, 1, "sales", ["invalid"], [{}]])
def test_chart_dataset_rejects_malformed_data(data):
    with pytest.raises(ValidationError, match="data"):
        ChartDataset(data=data)


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_chart_helper_nonfinite_data_is_rejected_before_wire_conversion(chart_type, number):
    dataset = ChartDataset(data=[number])

    with pytest.raises(ValueError, match=r"Non-finite.*data\[0\]"):
        chart_type(datasets=[dataset])
    with pytest.raises(ValueError, match=r"Non-finite.*data\[0\]"):
        primitive_adapter.validate_python({"type": chart_type.model_fields["type"].default, "datasets": (dataset,)})


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_chart_dict_nonfinite_data_keeps_existing_serialization_rejections(chart_type, number):
    chart = chart_type(datasets=[{"data": [number]}])

    for method in (chart.to_dict, chart.model_dump, chart.to_json):
        with pytest.raises(ValueError, match=r"Non-finite.*datasets\[0\]\.data\[0\]"):
            method()
    with pytest.raises(ValueError, match=r"wire_payload\.datasets\[0\]\.data\[0\]"):
        Primitive.from_dict({"type": chart.type, "datasets": [{"data": [number]}]})


@pytest.mark.parametrize("chart_type", [BarChart, LineChart])
def test_chart_dict_unsupported_values_remain_rejected(chart_type):
    chart = chart_type(datasets=[{"custom": object()}])

    with pytest.raises(ValueError, match=r"datasets\[0\]\.custom"):
        chart.to_dict()
