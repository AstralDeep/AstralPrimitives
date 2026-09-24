"""Public API of astralprims: re-exports every primitive and builds the discriminated
union (AnyPrimitive, primitive_adapter) over base.py's registry. AstralDeep agents
build UI payloads through it.
"""

from .base import CSS, Primitive
from .primitives import (
    ActionGroup,
    Alert,
    Audio,
    Badge,
    BarChart,
    Button,
    Card,
    ChartDataset,
    ChatHistory,
    CodeBlock,
    Collapsible,
    ColorPicker,
    Container,
    Divider,
    DonutChart,
    FileDownload,
    FileUpload,
    Gauge,
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
    PipelineStepper,
    PlotlyChart,
    ProgressBar,
    RadarChart,
    Rating,
    StatGroup,
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

__version__ = "0.4.0"


def _build_union():
    members = tuple(_REGISTRY.values())
    union = Annotated[Union[members], _Field(discriminator="type")]
    return union, TypeAdapter(union)


AnyPrimitive, primitive_adapter = _build_union()


def rebuild_primitive_union():
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
    "Container",
    "Card",
    "Grid",
    "Grids",
    "Tabs",
    "TabItem",
    "Collapsible",
    "Divider",
    "Text",
    "Button",
    "ActionGroup",
    "Input",
    "ParamPicker",
    "Image",
    "CodeBlock",
    "Alert",
    "ProgressBar",
    "MetricCard",
    "List_",
    "Table",
    "BarChart",
    "LineChart",
    "PieChart",
    "PlotlyChart",
    "DonutChart",
    "RadarChart",
    "ChartDataset",
    "Audio",
    "FileUpload",
    "FileDownload",
    "Badge",
    "Hero",
    "KeyValue",
    "Timeline",
    "Rating",
    "StatGroup",
    "Gauge",
    "PipelineStepper",
    "ChatHistory",
    "ColorPicker",
    "ThemeApply",
]
