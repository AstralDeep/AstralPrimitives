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
| Content   | `Text`, `Button`, `Input`, `ParamPicker`, `Image`, `CodeBlock`, `Alert`, `ProgressBar`, `MetricCard`, `List_`, `Table` |
| Charts    | `BarChart`, `LineChart`, `PieChart`, `PlotlyChart` (+ `ChartDataset`)      |
| Media/IO  | `Audio`, `FileUpload`, `FileDownload`                                      |
| Theming   | `ColorPicker`, `ThemeApply`                                                |

Every primitive also accepts `css`, `id`, `class_name` (serialized as `class`),
`tooltip`, and an `attributes` dict for arbitrary extra keys.

## Defining your own primitive

Subclassing auto-registers the new `type` for `from_dict` — no manual map:

```python
from dataclasses import dataclass
from typing import ClassVar, Optional
from astralprims import Primitive

@dataclass
class Badge(Primitive):
    type: ClassVar[str] = "badge"   # registered automatically
    label: str = ""
    count: Optional[int] = None
```

## Tests

```bash
pytest
```

## License

Apache-2.0
