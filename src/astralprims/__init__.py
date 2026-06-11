"""Astral Primitives — composable, serializable UI primitives for Python.

    >>> from astralprims import Button
    >>> Button(label="Click me", action="open",
    ...        css={"background-color": "white", "color": "#000000"}).to_dict()
    {'type': 'button', 'css': {'background-color': 'white', 'color': '#000000'}, 'label': 'Click me', 'action': 'open', 'payload': {}, 'variant': 'primary'}
"""

from .base import CSS, Primitive
from .primitives import (
    Alert,
    Audio,
    Badge,
    BarChart,
    Button,
    Card,
    ChartDataset,
    CodeBlock,
    Collapsible,
    ColorPicker,
    Container,
    Divider,
    FileDownload,
    FileUpload,
    Grid,
    Grids,
    Hero,
    Image,
    Input,
    KeyValue,
    LineChart,
    List_,
    MetricCard,
    ParamPicker,
    PieChart,
    PlotlyChart,
    ProgressBar,
    Rating,
    Table,
    Tabs,
    TabItem,
    Text,
    ThemeApply,
    Timeline,
)
from .response import create_ui_response

from typing import Annotated, Union

from pydantic import Field as _Field, TypeAdapter

from .base import _REGISTRY

__version__ = "0.2.0"


def _build_union():
    """Build a discriminated union + TypeAdapter over all registered primitives.

    Used for validating/parsing arbitrary primitive payloads and for generating
    a combined JSON Schema (e.g. for FastAPI request bodies / OpenAPI docs).
    """
    members = tuple(_REGISTRY.values())
    union = Annotated[Union[members], _Field(discriminator="type")]
    return union, TypeAdapter(union)


AnyPrimitive, primitive_adapter = _build_union()


def rebuild_primitive_union():
    """Rebuild :data:`AnyPrimitive`/:data:`primitive_adapter` after registering
    custom primitives. Returns the refreshed adapter."""
    global AnyPrimitive, primitive_adapter
    AnyPrimitive, primitive_adapter = _build_union()
    return primitive_adapter


__all__ = [
    "CSS",
    "Primitive",
    "AnyPrimitive",
    "primitive_adapter",
    "rebuild_primitive_union",
    "create_ui_response",
    # Layout
    "Container",
    "Card",
    "Grid",
    "Grids",
    "Tabs",
    "TabItem",
    "Collapsible",
    "Divider",
    # Content & controls
    "Text",
    "Button",
    "Input",
    "ParamPicker",
    "Image",
    "CodeBlock",
    "Alert",
    "ProgressBar",
    "MetricCard",
    "List_",
    "Table",
    # Charts
    "BarChart",
    "LineChart",
    "PieChart",
    "PlotlyChart",
    "ChartDataset",
    # Media & I/O
    "Audio",
    "FileUpload",
    "FileDownload",
    # Dashboard & status
    "Badge",
    "Hero",
    "KeyValue",
    "Timeline",
    "Rating",
    # Theming
    "ColorPicker",
    "ThemeApply",
]
