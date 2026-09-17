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

Every primitive also accepts `css`, `id`, `class_name` (serialized as `class`),
`tooltip`, and an `attributes` dict for arbitrary extra keys.

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

## Tests

```bash
pytest
```

## License

Apache-2.0
