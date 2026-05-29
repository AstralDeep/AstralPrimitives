"""Helpers for shipping primitives over the wire."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Primitive


def create_ui_response(components: List[Primitive]) -> Dict[str, Any]:
    """Wrap a list of primitives in the standard UI response envelope."""
    return {
        "_ui_components": [c.to_dict() for c in components],
        "_data": None,
    }
