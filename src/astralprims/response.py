"""Wraps a list of primitives (astralprims/base.py) in the standard UI response
envelope; exposed via astralprims/__init__.py for callers shipping SDUI responses
over the wire.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Primitive


def create_ui_response(components: List[Primitive]) -> Dict[str, Any]:
    return {
        "_ui_components": [c.to_dict() for c in components],
        "_data": None,
    }
