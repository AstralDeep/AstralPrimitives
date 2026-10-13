"""Pytest configuration and shared fixtures for the AstralPrimitives test suite.
Registers CLI flags including idempotency enforcement across round-trip tests.
Provides environment isolation and option fixtures for test executions.
"""

from __future__ import annotations

import gc
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--enforce-idempotency",
        action="store_true",
        default=False,
    )


@pytest.fixture
def enforce_idempotency(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--enforce-idempotency"))


@pytest.fixture(autouse=True)
def environment_isolation():
    gc.collect()
    yield
    gc.collect()
