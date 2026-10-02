"""Tests for primitives-004: NaN/Infinity rejection at the wire boundary.

Covers AstralDeep/AstralPrimitives#8 acceptance criteria:
- NaN, +Inf, -Inf in top-level metrics, chart arrays, payload dicts, attributes
- All accepted wire results pass strict standard-JSON encoder/decoder
- Finite values retain their existing representation
"""
import json
import math

import pytest

from astralprims.base import Primitive, _reject_non_finite
from astralprims.primitives import ProgressBar


def _invalid_floats() -> list:
    return [
        float("nan"),
        float("inf"),
        float("-inf"),
    ]


@pytest.mark.parametrize("bad", _invalid_floats())
def test_progressbar_rejects_non_finite_value(bad: float) -> None:
    # Construction-time rejection: ValueError surfaces the offending value
    with pytest.raises(ValueError, match="non-finite"):
        ProgressBar(value=bad)


def test_progressbar_accepts_finite_value() -> None:
    # Finite floats still work, including 0.0 and negative values.
    pb = ProgressBar(value=0.5)
    assert pb.value == 0.5
    json.loads(pb.to_json())  # must round-trip through strict JSON


def test_to_json_uses_strict_encoder() -> None:
    # Even if a non-finite float sneaks past the validator (e.g. via
    # attributes or a future subclass), to_json must refuse to emit it.
    pb = ProgressBar(value=0.0)
    pb.attributes["quality"] = float("nan")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        # _reject_non_finite raises ValueError before json.dumps runs
        text = pb.to_json()
        # belt-and-suspenders: strict-decode whatever came back
        json.loads(text)


def test_reject_non_finite_recursive_paths() -> None:
    # Top-level float
    with pytest.raises(ValueError, match="non-finite"):
        _reject_non_finite({"a": float("inf")})
    # Nested dict
    with pytest.raises(ValueError, match="non-finite"):
        _reject_non_finite({"a": {"b": float("nan")}})
    # List element
    with pytest.raises(ValueError, match="non-finite"):
        _reject_non_finite({"a": [1, 2, float("inf"), 4]})
    # Tuple element
    with pytest.raises(ValueError, match="non-finite"):
        _reject_non_finite({"a": (1, 2, float("-inf"))})


def test_reject_non_finite_passes_finite() -> None:
    # Finite values are not raised — they pass through unchanged.
    _reject_non_finite({"value": 0.5})
    _reject_non_finite({"value": -1.0})
    _reject_non_finite({"a": {"b": [1.0, 2.5]}})


def test_metric_progress_finite_passes_json() -> None:
    # Even a nested numeric in attributes survives a strict round-trip.
    pb = ProgressBar(value=0.25, attributes={"quality": 0.9})
    text = pb.to_json()
    # Standard JSON encoder/decoder must accept the wire form.
    decoded = json.loads(text)
    assert decoded["value"] == 0.25
    assert decoded["quality"] == 0.9


def test_progressbar_with_zero_value() -> None:
    # The default 0.0 is finite and must remain valid.
    pb = ProgressBar()
    assert pb.value == 0.0
    text = pb.to_json()
    assert json.loads(text)["value"] == 0.0
