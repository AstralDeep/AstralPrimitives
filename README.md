# Astral Primitives

Composable, serializable UI primitives for Python. Describe UI as plain Python
objects, then serialize them to a `dict`/JSON for storage or for a server-driven
UI to render.

## Install

```bash
pip install -e ".[dev]"   # editable install with test deps
```

## Quick start

```python
from astralprims import Button

button = Button(
    label="the button text",
    action="open",
    css={"background-color": "white", "color": "#000000"},
)

button.to_dict()
# {
#   "type": "button",
#   "css": {"background-color": "white", "color": "#000000"},
#   "label": "the button text",
#   "action": "open",
#   "payload": {},
#   "variant": "primary",
# }

button.to_json()  # -> JSON string
```

`None` and empty `css` are dropped from the output, so payloads stay clean.

### Composing layouts

```python
from astralprims import Card, Container, Text, Button

page = Container(css={"display": "flex"}, direction="column").add(
    Text(content="Welcome", variant="h1"),
    Card(title="Sign up").add(
        Text(content="Enter your details below."),
        Button(label="Get started", action="signup"),
    ),
)
page.to_dict()  # children/content serialize recursively
```

### Round-tripping from data

Already have a primitive as a `dict` (from storage or an API)? Rebuild it —
including the full nested tree:

```python
from astralprims import Primitive

spec = {"type": "button", "label": "Buy", "action": "checkout"}
button = Primitive.from_dict(spec)   # -> Button(...)
```

### Shipping a response

```python
from astralprims import create_ui_response, Text, Button

create_ui_response([Text(content="hi"), Button(label="ok", action="go")])
# {"_ui_components": [{...}, {...}], "_data": None}
```

A FastAPI endpoint can return `primitive.to_dict()` or `create_ui_response(...)`
directly.

## Wire schema

`wire_schema()` returns a JSON Schema (draft 2020-12) describing the canonical
`to_dict()` output of every built-in primitive in this release. Each wire type
gets an entry under `$defs`, and the root schema validates any serialized
component directly:

```python
from astralprims import wire_schema

schema = wire_schema()
schema["x-astralprims-version"]  # matches astralprims.__version__
schema["$defs"]["button"]        # the wire shape of Button output
```

Fields set to `None` are omitted from wire output entirely — canonical wire JSON
never contains `null` — and the same applies to an empty `css` block;
non-`None` defaults are always emitted and appear as the schema `default` of
their property. `attributes` is a trusted escape hatch
merged last into the top-level object: extra keys are always accepted, but
overriding a declared key, including `type`, may intentionally produce output
outside this baseline schema. Custom registered primitives stay supported
through `Primitive.from_dict()` but are not part of this versioned baseline.

## Built-in primitives

| Group     | Primitives                                                                 |
|-----------|----------------------------------------------------------------------------|
| Layout    | `Container`, `Card`, `Grid`/`Grids`, `Tabs` (+ `TabItem`), `Collapsible`, `Divider` |
| Content   | `Text`, `Button`, `ActionGroup`, `Input`, `ParamPicker`, `Image`, `CodeBlock`, `Alert`, `ProgressBar`, `MetricCard`, `List_`, `Table` |
| Charts    | `BarChart`, `LineChart`, `PieChart`, `DonutChart`, `RadarChart`, `PlotlyChart` (+ `ChartDataset`) |
| Media/IO  | `Audio`, `FileUpload`, `FileDownload`                                      |
| Dashboard | `Badge`, `Hero`, `KeyValue`, `Timeline`, `Rating`, `StatGroup`, `Gauge`, `PipelineStepper`, `ChatHistory` |
| Theming   | `ColorPicker`, `ThemeApply`                                                |

### Composite readouts

Six types describe a whole readout rather than a single value, so a server can
send the shape it means instead of assembling it from loose parts.

| Primitive         | Wire type          | What it carries |
|-------------------|--------------------|-----------------|
| `ActionGroup`     | `action_group`     | `buttons` (nested `Button` primitives), `align` (start/center/end/between), `label` for the group's accessible name |
| `StatGroup`       | `stat_group`       | `title`, `items` of `{label, value, delta?, trend?, hint?, variant?}`, `columns` (clamped 1-6) |
| `Gauge`           | `gauge`            | `label`, `value` on the same 0-1 scale as `ProgressBar`, `display_value`, ascending `thresholds` of `{at, variant}`, `subtitle` |
| `PipelineStepper` | `pipeline_stepper` | `title`, `steps` of `{label, status, detail?}` where status is done/active/pending/error, `orientation` |
| `DonutChart`      | `donut_chart`      | `title`, parallel `labels`/`data`, and `center_label`/`center_value` for the hole |
| `RadarChart`      | `radar_chart`      | `title`, `axes`, `datasets` of `{label, data}` parallel to the axes, optional `max_value` |

```python
from astralprims import ActionGroup, Button, Gauge, StatGroup

Gauge(label="Humidity", value=0.62, display_value="62%",
      thresholds=[{"at": 0.0, "variant": "success"},
                  {"at": 0.8, "variant": "warning"}])

StatGroup(title="This week", columns=3, items=[
    {"label": "Requests", "value": "1,284", "delta": "+12%", "trend": "up"},
    {"label": "Errors", "value": "3", "trend": "down", "variant": "success"},
    {"label": "p95", "value": "412 ms"},
])

ActionGroup(label="Result actions", align="end", buttons=[
    Button(label="Save", action="save_result"),
    Button(label="Export", action="export_result", variant="secondary"),
])
```

None of these carry a color. Variant strings name a semantic role and the
renderer resolves it from the active theme.

## Primitive reference

Every primitive serializes to a dict with its wire `type` first, then the common
fields, then its own fields. Fields left at `None` and an empty `css` are
dropped; every other default is emitted and is part of the wire contract. The
wire `type` does not always match the class name: `CodeBlock` is `code`,
`ProgressBar` is `progress`, `MetricCard` is `metric`, `List_` is `list`,
`KeyValue` is `keyvalue`, and `Grid` is an alias of `Grids`, which is `grid`.
In a type, `Primitive` means any nested primitive; a nested dict is rebuilt as
the class registered for its `type`.

<!-- primitive-reference:start -->

### Common fields

| Field | Type | Default |
| --- | --- | --- |
| `css` | `Optional[Dict[str, str]]` | `None` |
| `id` | `Optional[str]` | `None` |
| `class_name` (wire `class`) | `Optional[str]` | `None` |
| `tooltip` | `Optional[str]` | `None` |
| `attributes` | `Dict[str, Any]` | `{}` |

### Primitives

| Class | Wire type | Field | Type | Default |
| --- | --- | --- | --- | --- |
| `Container` | `container` | `children` | `List[Primitive]` | `[]` |
|  |  | `direction` | `Optional[str]` | `None` |
| `Card` | `card` | `title` | `str` | `""` |
|  |  | `content` | `List[Primitive]` | `[]` |
|  |  | `variant` | `str` | `"default"` |
| `Grids` (alias `Grid`) | `grid` | `columns` | `int` | `2` |
|  |  | `children` | `List[Primitive]` | `[]` |
|  |  | `gap` | `int` | `20` |
| `Tabs` | `tabs` | `tabs` | `List[TabItem]` | `[]` |
|  |  | `variant` | `str` | `"default"` |
| `Collapsible` | `collapsible` | `title` | `str` | `""` |
|  |  | `content` | `List[Primitive]` | `[]` |
|  |  | `default_open` | `bool` | `False` |
| `Divider` | `divider` | `variant` | `str` | `"solid"` |
| `Text` | `text` | `content` | `str` | `""` |
|  |  | `variant` | `str` | `"body"` |
| `Button` | `button` | `label` | `str` | `""` |
|  |  | `action` | `str` | `""` |
|  |  | `payload` | `Dict[str, Any]` | `{}` |
|  |  | `variant` | `str` | `"primary"` |
| `ActionGroup` | `action_group` | `buttons` | `List[Primitive]` | `[]` |
|  |  | `align` | `str` | `"start"` |
|  |  | `label` | `Optional[str]` | `None` |
| `Input` | `input` | `placeholder` | `str` | `""` |
|  |  | `name` | `str` | `""` |
|  |  | `value` | `str` | `""` |
| `ParamPicker` | `param_picker` | `title` | `str` | `""` |
|  |  | `description` | `str` | `""` |
|  |  | `fields` | `List[Dict[str, Any]]` | `[]` |
|  |  | `submit_label` | `str` | `"Submit"` |
|  |  | `submit_message_template` | `str` | `""` |
| `Image` | `image` | `url` | `str` | `""` |
|  |  | `alt` | `Optional[str]` | `None` |
|  |  | `width` | `Optional[str]` | `None` |
|  |  | `height` | `Optional[str]` | `None` |
| `CodeBlock` | `code` | `code` | `str` | `""` |
|  |  | `language` | `str` | `"text"` |
|  |  | `show_line_numbers` | `bool` | `False` |
| `Alert` | `alert` | `message` | `str` | `""` |
|  |  | `variant` | `str` | `"info"` |
|  |  | `title` | `Optional[str]` | `None` |
| `ProgressBar` | `progress` | `value` | `float` | `0.0` |
|  |  | `label` | `Optional[str]` | `None` |
|  |  | `variant` | `str` | `"default"` |
|  |  | `show_percentage` | `bool` | `True` |
| `MetricCard` | `metric` | `title` | `str` | `""` |
|  |  | `value` | `str` | `""` |
|  |  | `subtitle` | `Optional[str]` | `None` |
|  |  | `icon` | `Optional[str]` | `None` |
|  |  | `variant` | `str` | `"default"` |
|  |  | `progress` | `Optional[float]` | `None` |
| `List_` | `list` | `items` | `List[Union[str, Dict[str, Any]]]` | `[]` |
|  |  | `ordered` | `bool` | `False` |
|  |  | `variant` | `str` | `"default"` |
| `Table` | `table` | `headers` | `List[str]` | `[]` |
|  |  | `rows` | `List[List[Any]]` | `[]` |
|  |  | `variant` | `str` | `"default"` |
|  |  | `total_rows` | `Optional[int]` | `None` |
|  |  | `page_size` | `Optional[int]` | `None` |
|  |  | `page_offset` | `Optional[int]` | `None` |
|  |  | `page_sizes` | `List[int]` | `[]` |
|  |  | `source_tool` | `Optional[str]` | `None` |
|  |  | `source_agent` | `Optional[str]` | `None` |
|  |  | `source_params` | `Dict[str, Any]` | `{}` |
| `BarChart` | `bar_chart` | `title` | `str` | `""` |
|  |  | `labels` | `List[str]` | `[]` |
|  |  | `datasets` | `List[Dict[str, Any]]` | `[]` |
| `LineChart` | `line_chart` | `title` | `str` | `""` |
|  |  | `labels` | `List[str]` | `[]` |
|  |  | `datasets` | `List[Dict[str, Any]]` | `[]` |
| `PieChart` | `pie_chart` | `title` | `str` | `""` |
|  |  | `labels` | `List[str]` | `[]` |
|  |  | `data` | `List[float]` | `[]` |
|  |  | `colors` | `List[str]` | `[]` |
| `DonutChart` | `donut_chart` | `title` | `str` | `""` |
|  |  | `labels` | `List[str]` | `[]` |
|  |  | `data` | `List[float]` | `[]` |
|  |  | `center_label` | `Optional[str]` | `None` |
|  |  | `center_value` | `Optional[str]` | `None` |
| `RadarChart` | `radar_chart` | `title` | `str` | `""` |
|  |  | `axes` | `List[str]` | `[]` |
|  |  | `datasets` | `List[Dict[str, Any]]` | `[]` |
|  |  | `max_value` | `Optional[float]` | `None` |
| `PlotlyChart` | `plotly_chart` | `title` | `str` | `""` |
|  |  | `data` | `List[Dict[str, Any]]` | `[]` |
|  |  | `layout` | `Dict[str, Any]` | `{}` |
|  |  | `config` | `Dict[str, Any]` | `{}` |
| `Audio` | `audio` | `src` | `str` | `""` |
|  |  | `contentType` | `Optional[str]` | `None` |
|  |  | `autoplay` | `bool` | `False` |
|  |  | `loop` | `bool` | `False` |
|  |  | `label` | `Optional[str]` | `None` |
|  |  | `showControls` | `bool` | `True` |
|  |  | `description` | `Optional[str]` | `None` |
| `FileUpload` | `file_upload` | `label` | `str` | `"Upload File"` |
|  |  | `accept` | `str` | `"*/*"` |
|  |  | `action` | `str` | `""` |
| `FileDownload` | `file_download` | `label` | `str` | `"Download File"` |
|  |  | `url` | `str` | `""` |
|  |  | `filename` | `Optional[str]` | `None` |
| `Badge` | `badge` | `label` | `str` | `""` |
|  |  | `variant` | `str` | `"default"` |
|  |  | `icon` | `Optional[str]` | `None` |
| `Hero` | `hero` | `title` | `str` | `""` |
|  |  | `subtitle` | `Optional[str]` | `None` |
|  |  | `eyebrow` | `Optional[str]` | `None` |
|  |  | `icon` | `Optional[str]` | `None` |
|  |  | `variant` | `str` | `"default"` |
|  |  | `badges` | `List[str]` | `[]` |
| `KeyValue` | `keyvalue` | `title` | `Optional[str]` | `None` |
|  |  | `items` | `List[Dict[str, Any]]` | `[]` |
|  |  | `columns` | `int` | `2` |
| `Timeline` | `timeline` | `title` | `Optional[str]` | `None` |
|  |  | `items` | `List[Dict[str, Any]]` | `[]` |
|  |  | `variant` | `str` | `"default"` |
| `StatGroup` | `stat_group` | `title` | `Optional[str]` | `None` |
|  |  | `items` | `List[Dict[str, Any]]` | `[]` |
|  |  | `columns` | `int` | `4` |
| `Gauge` | `gauge` | `label` | `str` | `""` |
|  |  | `value` | `float` | `0.0` |
|  |  | `display_value` | `Optional[str]` | `None` |
|  |  | `thresholds` | `List[Dict[str, Any]]` | `[]` |
|  |  | `subtitle` | `Optional[str]` | `None` |
| `PipelineStepper` | `pipeline_stepper` | `title` | `Optional[str]` | `None` |
|  |  | `steps` | `List[Dict[str, Any]]` | `[]` |
|  |  | `orientation` | `str` | `"horizontal"` |
| `Rating` | `rating` | `value` | `float` | `0.0` |
|  |  | `max_value` | `int` | `5` |
|  |  | `label` | `Optional[str]` | `None` |
|  |  | `subtitle` | `Optional[str]` | `None` |
|  |  | `show_value` | `bool` | `True` |
| `ChatHistory` | `chat_history` | `title` | `Optional[str]` | `"Recent chats"` |
|  |  | `items` | `List[Dict[str, Any]]` | `[]` |
| `ColorPicker` | `color_picker` | `label` | `str` | `""` |
|  |  | `color_key` | `str` | `""` |
|  |  | `value` | `str` | `"#000000"` |
| `ThemeApply` | `theme_apply` | `preset` | `Optional[str]` | `None` |
|  |  | `colors` | `Optional[Dict[str, str]]` | `None` |
|  |  | `color_key` | `Optional[str]` | `None` |
|  |  | `color_value` | `Optional[str]` | `None` |
|  |  | `message` | `str` | `""` |

### Nested models

| Class | Field | Type | Default |
| --- | --- | --- | --- |
| `TabItem` | `label` | `str` | `""` |
|  | `content` | `List[Primitive]` | `[]` |
|  | `value` | `Optional[str]` | `None` |
| `ChartDataset` | `label` | `str` | `""` |
|  | `data` | `List[float]` | `[]` |
|  | `color` | `Optional[str]` | `None` |

<!-- primitive-reference:end -->

`attributes` is never emitted as a key: its entries are merged into the top
level last and can overwrite any field, including `type`, so it must carry only
trusted keys, never user or model input.

This reference is generated from the models. After changing a primitive, run
`uv run --frozen python tooling/python-ci/primitive_reference.py` to regenerate
it; `tests/test_readme_reference.py` fails while it is stale.

## Defining your own primitive

Primitives are pydantic models; declare the wire `type` as a `Literal` default
and subclassing auto-registers it for `from_dict` — no manual map. Pick a type
string that does not collide with a built-in:

```python
from typing import Literal, Optional
from astralprims import Primitive, rebuild_primitive_union

class Ribbon(Primitive):
    type: Literal["ribbon"] = "ribbon"   # registered automatically
    label: str = ""
    count: Optional[int] = None

rebuild_primitive_union()  # refresh AnyPrimitive/primitive_adapter
```

### Collision errors and validation

Every primitive subclass must declare a `type` field with a non-empty string default
that matches any `Literal` annotation choices. Wire types must be globally unique across
built-in and custom primitives. Attempting to register a wire `type` that is already bound
to another class raises `PrimitiveTypeCollisionError` before modifying the registry.
Failed registrations abort cleanly without altering `_REGISTRY` or existing `primitive_adapter`
instances.

### Unregistering and rebuild ordering

To remove an extension primitive or prepare for a replacement, unregister the wire type name
using `unregister_primitive()` and then call `rebuild_primitive_union()`:

```python
from astralprims import unregister_primitive, rebuild_primitive_union

unregister_primitive("ribbon")
rebuild_primitive_union()
```

### Reload policy

Re-registering the exact same class object (for example, in interactive environments) is
permitted. However, module reloads create a new, distinct class object for the same wire
type, which triggers `PrimitiveTypeCollisionError`. To reload a module defining custom
primitives, call `unregister_primitive()` on the custom wire types before reloading the
module, then call `rebuild_primitive_union()`.

## Tests

```bash
pytest
```

## License

Apache-2.0
