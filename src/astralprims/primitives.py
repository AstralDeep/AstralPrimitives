"""Concrete Pydantic UI primitive models (layout, content, charts, media, dashboard,
theming) that extend Primitive from astralprims/base.py; re-exported via
astralprims/__init__.py for building SDUI component trees.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, field_validator

from .base import SerModel, _coerce_children
from .base import Primitive


class Container(Primitive):
    type: Literal["container"] = "container"
    children: List[Primitive] = Field(default_factory=list)
    direction: Optional[str] = None

    def add(self, *children: Primitive) -> "Container":
        self.children.extend(children)
        return self


class Card(Primitive):
    type: Literal["card"] = "card"
    title: str = ""
    content: List[Primitive] = Field(default_factory=list)
    variant: str = "default"

    def add(self, *content: Primitive) -> "Card":
        self.content.extend(content)
        return self


class Grids(Primitive):
    type: Literal["grid"] = "grid"
    columns: int = 2
    children: List[Primitive] = Field(default_factory=list)
    gap: int = 20

    def add(self, *children: Primitive) -> "Grids":
        self.children.extend(children)
        return self


Grid = Grids


class TabItem(SerModel):
    label: str = ""
    content: List[Primitive] = Field(default_factory=list)
    value: Optional[str] = None

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, v: Any) -> Any:
        return _coerce_children(v)


class Tabs(Primitive):
    type: Literal["tabs"] = "tabs"
    tabs: List[TabItem] = Field(default_factory=list)
    variant: str = "default"

    @field_validator("tabs", mode="before")
    @classmethod
    def _coerce_tabs(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [TabItem.model_validate(t) if isinstance(t, dict) else t for t in v]
        return v


class Collapsible(Primitive):
    type: Literal["collapsible"] = "collapsible"
    title: str = ""
    content: List[Primitive] = Field(default_factory=list)
    default_open: bool = False


class Divider(Primitive):
    type: Literal["divider"] = "divider"
    variant: str = "solid"


class Text(Primitive):
    type: Literal["text"] = "text"
    content: str = ""
    variant: str = "body"


class Button(Primitive):
    type: Literal["button"] = "button"
    label: str = ""
    action: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    variant: str = "primary"


class ActionGroup(Primitive):
    type: Literal["action_group"] = "action_group"
    buttons: List[Primitive] = Field(default_factory=list)
    align: str = "start"
    label: Optional[str] = None

    @field_validator("buttons", mode="before")
    @classmethod
    def _coerce_buttons(cls, v: Any) -> Any:
        return _coerce_children(v)


class Input(Primitive):
    type: Literal["input"] = "input"
    placeholder: str = ""
    name: str = ""
    value: str = ""


class ParamPicker(Primitive):
    type: Literal["param_picker"] = "param_picker"
    title: str = ""
    description: str = ""
    fields: List[Dict[str, Any]] = Field(default_factory=list)
    submit_label: str = "Submit"
    submit_message_template: str = ""


class Image(Primitive):
    type: Literal["image"] = "image"
    url: str = ""
    alt: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None


class CodeBlock(Primitive):
    type: Literal["code"] = "code"
    code: str = ""
    language: str = "text"
    show_line_numbers: bool = False


class Alert(Primitive):
    type: Literal["alert"] = "alert"
    message: str = ""
    variant: str = "info"
    title: Optional[str] = None


class ProgressBar(Primitive):
    type: Literal["progress"] = "progress"
    value: float = 0.0
    label: Optional[str] = None
    variant: str = "default"
    show_percentage: bool = True


class MetricCard(Primitive):
    type: Literal["metric"] = "metric"
    title: str = ""
    value: str = ""
    subtitle: Optional[str] = None
    icon: Optional[str] = None
    variant: str = "default"
    progress: Optional[float] = None


class List_(Primitive):
    type: Literal["list"] = "list"
    items: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    ordered: bool = False
    variant: str = "default"


class Table(Primitive):
    type: Literal["table"] = "table"
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    variant: str = "default"
    total_rows: Optional[int] = None
    page_size: Optional[int] = None
    page_offset: Optional[int] = None
    page_sizes: List[int] = Field(default_factory=list)
    source_tool: Optional[str] = None
    source_agent: Optional[str] = None
    source_params: Dict[str, Any] = Field(default_factory=dict)


class ChartDataset(SerModel):
    label: str = ""
    data: List[float] = Field(default_factory=list)
    color: Optional[str] = None


class BarChart(Primitive):
    type: Literal["bar_chart"] = "bar_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)


class LineChart(Primitive):
    type: Literal["line_chart"] = "line_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)


class PieChart(Primitive):
    type: Literal["pie_chart"] = "pie_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    data: List[float] = Field(default_factory=list)
    colors: List[str] = Field(default_factory=list)


class DonutChart(Primitive):
    type: Literal["donut_chart"] = "donut_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    data: List[float] = Field(default_factory=list)
    center_label: Optional[str] = None
    center_value: Optional[str] = None


class RadarChart(Primitive):
    type: Literal["radar_chart"] = "radar_chart"
    title: str = ""
    axes: List[str] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)
    max_value: Optional[float] = None


class PlotlyChart(Primitive):
    type: Literal["plotly_chart"] = "plotly_chart"
    title: str = ""
    data: List[Dict[str, Any]] = Field(default_factory=list)
    layout: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class Audio(Primitive):
    type: Literal["audio"] = "audio"
    src: str = ""
    contentType: Optional[str] = None
    autoplay: bool = False
    loop: bool = False
    label: Optional[str] = None
    showControls: bool = True
    description: Optional[str] = None


class FileUpload(Primitive):
    type: Literal["file_upload"] = "file_upload"
    label: str = "Upload File"
    accept: str = "*/*"
    action: str = ""


class FileDownload(Primitive):
    type: Literal["file_download"] = "file_download"
    label: str = "Download File"
    url: str = ""
    filename: Optional[str] = None


class Badge(Primitive):
    type: Literal["badge"] = "badge"
    label: str = ""
    variant: str = "default"
    icon: Optional[str] = None


class Hero(Primitive):
    type: Literal["hero"] = "hero"
    title: str = ""
    subtitle: Optional[str] = None
    eyebrow: Optional[str] = None
    icon: Optional[str] = None
    variant: str = "default"
    badges: List[str] = Field(default_factory=list)


class KeyValue(Primitive):
    type: Literal["keyvalue"] = "keyvalue"
    title: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    columns: int = 2


class Timeline(Primitive):
    type: Literal["timeline"] = "timeline"
    title: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    variant: str = "default"


class StatGroup(Primitive):
    type: Literal["stat_group"] = "stat_group"
    title: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    columns: int = 4


class Gauge(Primitive):
    type: Literal["gauge"] = "gauge"
    label: str = ""
    value: float = 0.0
    display_value: Optional[str] = None
    thresholds: List[Dict[str, Any]] = Field(default_factory=list)
    subtitle: Optional[str] = None


class PipelineStepper(Primitive):
    type: Literal["pipeline_stepper"] = "pipeline_stepper"
    title: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    orientation: str = "horizontal"


class Rating(Primitive):
    type: Literal["rating"] = "rating"
    value: float = 0.0
    max_value: int = 5
    label: Optional[str] = None
    subtitle: Optional[str] = None
    show_value: bool = True


class ChatHistory(Primitive):
    type: Literal["chat_history"] = "chat_history"
    title: Optional[str] = "Recent chats"
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ColorPicker(Primitive):
    type: Literal["color_picker"] = "color_picker"
    label: str = ""
    color_key: str = ""
    value: str = "#000000"


class ThemeApply(Primitive):
    type: Literal["theme_apply"] = "theme_apply"
    preset: Optional[str] = None
    colors: Optional[Dict[str, str]] = None
    color_key: Optional[str] = None
    color_value: Optional[str] = None
    message: str = ""
