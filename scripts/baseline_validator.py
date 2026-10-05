"""Validates baseline serialization, round-trip, and adapter contracts across primitives.
Executes registry-derived verification and representative nested structures deterministically.
Ensures repository contracts hold without defects across supported configurations.
"""

from __future__ import annotations

import json

from astralprims import (
    ActionGroup,
    Button,
    Card,
    Collapsible,
    Container,
    Grid,
    Grids,
    Primitive,
    TabItem,
    Tabs,
    Text,
    primitive_adapter,
)
from astralprims.base import _REGISTRY


def validate_registry_matrix() -> int:
    built_ins = sorted(
        (wire_type, cls)
        for wire_type, cls in _REGISTRY.items()
        if cls.__module__.startswith("astralprims.")
    )
    for wire_type, cls in built_ins:
        inst = cls()
        data = inst.to_dict()
        assert data["type"] == wire_type
        json_str = inst.to_json()
        assert json.loads(json_str) == data
        restored = Primitive.from_dict(data)
        assert type(restored) is cls
        assert restored.to_dict() == data
        validated = primitive_adapter.validate_python(data)
        assert isinstance(validated, cls)
        second = cls()
        for field_name in cls.model_fields:
            val1 = getattr(inst, field_name)
            val2 = getattr(second, field_name)
            if isinstance(val1, list):
                assert val1 is not val2
            elif isinstance(val1, dict):
                assert val1 is not val2
        assert Primitive.from_dict(restored.to_dict()).to_dict() == data
    return len(built_ins)


def validate_representative_tree() -> None:
    tree = Container(
        class_name="layout-root",
        css={},
        attributes={"data-testid": "root-layout", "layout": "stacked"},
        children=[
            Grid(
                columns=2,
                class_name="dashboard-grid",
                children=[
                    Card(
                        title="Overview",
                        content=[
                            Collapsible(
                                title="Metrics Details",
                                content=[
                                    Text(
                                        content="Inner details",
                                        class_name="muted-label",
                                    ),
                                ],
                            ),
                            Tabs(
                                tabs=[
                                    TabItem(
                                        label="Controls",
                                        content=[
                                            ActionGroup(
                                                buttons=[
                                                    Button(
                                                        label="Submit",
                                                        action="commit_action",
                                                        payload={},
                                                        css={},
                                                        class_name="btn-submit",
                                                        attributes={
                                                            "label": "Overridden Action",
                                                            "data-button-id": "btn-01",
                                                        },
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    data = tree.to_dict()
    assert "css" not in data
    assert data["class"] == "layout-root"
    assert data["layout"] == "stacked"
    assert data["data-testid"] == "root-layout"

    grid_wire = data["children"][0]
    assert grid_wire["type"] == "grid"
    assert grid_wire["class"] == "dashboard-grid"

    card_wire = grid_wire["children"][0]
    assert card_wire["type"] == "card"
    assert card_wire["title"] == "Overview"

    collapsible_wire = card_wire["content"][0]
    assert collapsible_wire["type"] == "collapsible"
    text_wire = collapsible_wire["content"][0]
    assert text_wire["type"] == "text"
    assert text_wire["content"] == "Inner details"
    assert text_wire["class"] == "muted-label"

    tabs_wire = card_wire["content"][1]
    assert tabs_wire["type"] == "tabs"
    tab_item_wire = tabs_wire["tabs"][0]
    assert tab_item_wire["label"] == "Controls"

    action_group_wire = tab_item_wire["content"][0]
    assert action_group_wire["type"] == "action_group"

    btn_wire = action_group_wire["buttons"][0]
    assert btn_wire["type"] == "button"
    assert btn_wire["class"] == "btn-submit"
    assert btn_wire["action"] == "commit_action"
    assert btn_wire["payload"] == {}
    assert "css" not in btn_wire
    assert btn_wire["label"] == "Overridden Action"
    assert btn_wire["data-button-id"] == "btn-01"

    restored = Primitive.from_dict(data)
    assert isinstance(restored, Container)
    assert restored.to_dict() == data

    json_str = tree.to_json()
    assert json.loads(json_str) == data

    validated = primitive_adapter.validate_python(data)
    assert isinstance(validated, Container)
    assert isinstance(validated.children[0], Grids)
    assert isinstance(validated.children[0].children[0], Card)
    assert isinstance(validated.children[0].children[0].content[0], Collapsible)
    assert isinstance(validated.children[0].children[0].content[0].content[0], Text)
    assert isinstance(validated.children[0].children[0].content[1], Tabs)
    assert isinstance(
        validated.children[0].children[0].content[1].tabs[0].content[0], ActionGroup
    )
    assert isinstance(
        validated.children[0].children[0].content[1].tabs[0].content[0].buttons[0],
        Button,
    )
    assert Primitive.from_dict(restored.to_dict()).to_dict() == data


def main() -> None:
    count = validate_registry_matrix()
    validate_representative_tree()
    print(f"Validated baseline contracts across {count} primitives.")


if __name__ == "__main__":
    main()
