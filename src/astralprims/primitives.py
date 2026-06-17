"""Concrete UI primitives.

Each primitive is a Pydantic model that inherits ``css``, ``id``, ``class_name``,
``tooltip`` and ``attributes`` from :class:`Primitive` and adds its own fields.
Nesting (children / content / tabs) is reconstructed and serialized by the base
class. Import the ones you need::

    from astralprims import Button, Container, Card

    Container().add(
        Card(title="Welcome", content=[Button(label="Get started", action="go")])
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, field_validator

from .base import SerModel, _coerce_children
from .base import Primitive

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class Container(Primitive):
    """A layout container holding child primitives."""

    type: Literal["container"] = "container"
    children: List[Primitive] = Field(default_factory=list)
    direction: Optional[str] = None  # e.g. "row" | "column"

    def add(self, *children: Primitive) -> "Container":
        """Append one or more children and return self (chainable)."""
        self.children.extend(children)
        return self


class Card(Primitive):
    """A titled card wrapping child primitives."""

    type: Literal["card"] = "card"
    title: str = ""
    content: List[Primitive] = Field(default_factory=list)
    variant: str = "default"

    def add(self, *content: Primitive) -> "Card":
        self.content.extend(content)
        return self


class Grids(Primitive):
    """A grid layout with a fixed column count."""

    type: Literal["grid"] = "grid"
    columns: int = 2
    children: List[Primitive] = Field(default_factory=list)
    gap: int = 20

    def add(self, *children: Primitive) -> "Grids":
        self.children.extend(children)
        return self


# Backwards-compatible alias.
Grid = Grids


class TabItem(SerModel):
    """A single tab. Not a primitive itself (no ``type``); nested in ``Tabs``."""

    label: str = ""
    content: List[Primitive] = Field(default_factory=list)
    value: Optional[str] = None

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, v: Any) -> Any:
        return _coerce_children(v)


class Tabs(Primitive):
    """A tabbed container."""

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
    """A collapsible / accordion section."""

    type: Literal["collapsible"] = "collapsible"
    title: str = ""
    content: List[Primitive] = Field(default_factory=list)
    default_open: bool = False


class Divider(Primitive):
    """A horizontal rule / visual separator."""

    type: Literal["divider"] = "divider"
    variant: str = "solid"


# ---------------------------------------------------------------------------
# Content & controls
# ---------------------------------------------------------------------------


class Text(Primitive):
    """A run of text. ``variant`` is one of h1, h2, h3, body, caption."""

    type: Literal["text"] = "text"
    content: str = ""
    variant: str = "body"


class Button(Primitive):
    """A clickable button that dispatches an action with an optional payload."""

    type: Literal["button"] = "button"
    label: str = ""
    action: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    variant: str = "primary"


class Input(Primitive):
    """A single-line form input."""

    type: Literal["input"] = "input"
    placeholder: str = ""
    name: str = ""
    value: str = ""


class ParamPicker(Primitive):
    """Interactive parameter form rendered as a card with form fields.

    Each entry in ``fields`` is a dict of the shape::

        {"name": "models_to_train",
         "label": "Models to train",
         "kind": "boolean"|"number"|"text"|"checklist"|"select",
         "default": <starting value>,
         "options": [...]  # for checklist/select
         "help": "...",
         "step": 1  # optional, for number kind
        }

    On submit the renderer interpolates ``submit_message_template`` with the
    user's field values. Two placeholder forms are supported:

    * ``{field_name}`` — replaced with that field's value (JSON-encoded for
      lists/dicts/bools).
    * ``{__values_json__}`` — replaced with the JSON of the entire form state.
    """

    type: Literal["param_picker"] = "param_picker"
    title: str = ""
    description: str = ""
    fields: List[Dict[str, Any]] = Field(default_factory=list)
    submit_label: str = "Submit"
    submit_message_template: str = ""


class Image(Primitive):
    """An image."""

    type: Literal["image"] = "image"
    url: str = ""
    alt: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None


class CodeBlock(Primitive):
    """A syntax-highlighted code block."""

    type: Literal["code"] = "code"
    code: str = ""
    language: str = "text"
    show_line_numbers: bool = False


class Alert(Primitive):
    """A callout / banner. ``variant`` is info, success, warning, or error."""

    type: Literal["alert"] = "alert"
    message: str = ""
    variant: str = "info"
    title: Optional[str] = None


class ProgressBar(Primitive):
    """A progress bar."""

    type: Literal["progress"] = "progress"
    value: float = 0.0
    label: Optional[str] = None
    variant: str = "default"
    show_percentage: bool = True


class MetricCard(Primitive):
    """A single KPI / metric tile."""

    type: Literal["metric"] = "metric"
    title: str = ""
    value: str = ""
    subtitle: Optional[str] = None
    icon: Optional[str] = None
    variant: str = "default"
    progress: Optional[float] = None


class List_(Primitive):
    """An ordered or unordered list of strings or dict items."""

    type: Literal["list"] = "list"
    items: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    ordered: bool = False
    variant: str = "default"


class Table(Primitive):
    """A data table with optional pagination and re-invocation context."""

    type: Literal["table"] = "table"
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    variant: str = "default"
    # Pagination (optional — when present, the renderer shows controls).
    total_rows: Optional[int] = None
    page_size: Optional[int] = None
    page_offset: Optional[int] = None
    page_sizes: List[int] = Field(default_factory=list)
    # Tool re-invocation context (lets the renderer request different pages).
    source_tool: Optional[str] = None
    source_agent: Optional[str] = None
    source_params: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


class ChartDataset(SerModel):
    """A named series of values. Not a primitive itself."""

    label: str = ""
    data: List[float] = Field(default_factory=list)
    color: Optional[str] = None


class BarChart(Primitive):
    """A bar chart."""

    type: Literal["bar_chart"] = "bar_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)


class LineChart(Primitive):
    """A line chart."""

    type: Literal["line_chart"] = "line_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    datasets: List[Dict[str, Any]] = Field(default_factory=list)


class PieChart(Primitive):
    """A pie chart."""

    type: Literal["pie_chart"] = "pie_chart"
    title: str = ""
    labels: List[str] = Field(default_factory=list)
    data: List[float] = Field(default_factory=list)
    colors: List[str] = Field(default_factory=list)


class PlotlyChart(Primitive):
    """An arbitrary Plotly figure (data + layout + config)."""

    type: Literal["plotly_chart"] = "plotly_chart"
    title: str = ""
    data: List[Dict[str, Any]] = Field(default_factory=list)
    layout: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Media & I/O
# ---------------------------------------------------------------------------


class Audio(Primitive):
    """Audio player primitive.

    Supports inline base64 data, URLs, generated speech, and MIDI.
    """

    type: Literal["audio"] = "audio"
    src: str = ""
    contentType: Optional[str] = None  # audio/mpeg, audio/wav, audio/midi, ...
    autoplay: bool = False
    loop: bool = False
    label: Optional[str] = None  # optional title above the player
    showControls: bool = True
    description: Optional[str] = None  # optional caption/description


class FileUpload(Primitive):
    """A file upload control."""

    type: Literal["file_upload"] = "file_upload"
    label: str = "Upload File"
    accept: str = "*/*"
    action: str = ""


class FileDownload(Primitive):
    """A file download link/button."""

    type: Literal["file_download"] = "file_download"
    label: str = "Download File"
    url: str = ""
    filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Dashboard & status
# ---------------------------------------------------------------------------


class Badge(Primitive):
    """A small inline status chip.

    ``variant`` is one of default, success, warning, error, info, or accent.
    """

    type: Literal["badge"] = "badge"
    label: str = ""
    variant: str = "default"
    icon: Optional[str] = None


class Hero(Primitive):
    """A page-level header band: eyebrow, title, subtitle, optional badges.

    Gives dashboards and reports an anchoring masthead. ``variant`` is one of
    default, gradient, or subtle.
    """

    type: Literal["hero"] = "hero"
    title: str = ""
    subtitle: Optional[str] = None
    eyebrow: Optional[str] = None
    icon: Optional[str] = None
    variant: str = "default"
    badges: List[str] = Field(default_factory=list)


class KeyValue(Primitive):
    """A compact label/value fact sheet.

    Each entry in ``items`` is a dict of the shape::

        {"label": "Owner", "value": "Paws & Bubbles", "hint": "since 2021"}

    ``hint`` is optional. ``columns`` controls how many label/value pairs sit
    side by side (1-4).
    """

    type: Literal["keyvalue"] = "keyvalue"
    title: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    columns: int = 2


class Timeline(Primitive):
    """A vertical sequence of events, appointments, or steps.

    Each entry in ``items`` is a dict of the shape::

        {"time": "9:00 AM", "title": "Bella — Full Groom",
         "description": "Golden Retriever, de-shed add-on",
         "variant": "success"}

    ``time``, ``description`` and ``variant`` (default | success | warning |
    error | info) are optional.
    """

    type: Literal["timeline"] = "timeline"
    title: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    variant: str = "default"


class Rating(Primitive):
    """A star-rating readout (e.g. customer satisfaction)."""

    type: Literal["rating"] = "rating"
    value: float = 0.0
    max_value: int = 5
    label: Optional[str] = None
    subtitle: Optional[str] = None
    show_value: bool = True


class ChatHistory(Primitive):
    """A scannable list of recent conversations the user can reopen.

    Each entry in ``items`` is a dict of the shape::

        {"chat_id": "c1", "title": "Weather this weekend",
         "preview": "Saturday looks clear, high of 81°F…", "time": "2h",
         "icon": "🌤️", "saved": True}

    Only ``chat_id`` and ``title`` are required to render an openable row;
    ``preview`` (a last-message snippet), ``time`` (a pre-formatted relative
    time such as ``"2h"``/``"3d"``), ``icon`` (a decorative per-agent glyph) and
    ``saved`` (truthy → a saved-components marker) are optional. Selecting a row
    dispatches a ``load_chat`` action carrying ``{"chat_id": …}``. With no items
    the surface shows an empty state. ``title`` is the surface heading.
    """

    type: Literal["chat_history"] = "chat_history"
    title: Optional[str] = "Recent chats"
    items: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Theming
# ---------------------------------------------------------------------------


class ColorPicker(Primitive):
    """A color picker bound to a theme color key."""

    type: Literal["color_picker"] = "color_picker"
    label: str = ""
    color_key: str = ""
    value: str = "#000000"


class ThemeApply(Primitive):
    """Applies a theme preset or individual color change."""

    type: Literal["theme_apply"] = "theme_apply"
    preset: Optional[str] = None
    colors: Optional[Dict[str, str]] = None
    color_key: Optional[str] = None
    color_value: Optional[str] = None
    message: str = ""
