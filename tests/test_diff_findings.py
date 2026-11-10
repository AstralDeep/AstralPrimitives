"""Serialization tests for the review vocabulary: Diff (DiffFile, DiffHunk, DiffLine,
DiffAction) and Findings (Finding). They cover golden wire shapes, empty and binary
inputs, bounded truncation with flags, construction refusals, from_dict round-trips,
and adapter, container, response-envelope and wire-schema validation.
"""

import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from astralprims import (
    Container,
    Diff,
    DiffAction,
    DiffFile,
    DiffHunk,
    DiffLine,
    Finding,
    Findings,
    Primitive,
    create_ui_response,
    primitive_adapter,
    wire_schema,
)
from astralprims.primitives import (
    MAX_DIFF_FILES,
    MAX_DIFF_HUNKS_PER_FILE,
    MAX_DIFF_LINES_PER_HUNK,
    MAX_FINDINGS,
)


def _lines(count):
    return [{"kind": "context", "content": f"line {index}"} for index in range(count)]


def _file(index, hunk_count=1, line_count=0):
    return {
        "old_path": f"f{index}.py",
        "new_path": f"f{index}.py",
        "status": "modified",
        "hunks": [
            {"id": f"f{index}:h{hunk}", "lines": _lines(line_count)}
            for hunk in range(hunk_count)
        ],
    }


def _files_for(count):
    return [_file(index) for index in range(count)]


def test_diff_golden_wire_shape():
    diff = Diff(
        files=[
            DiffFile(
                old_path="src/app.py",
                new_path="src/app.py",
                status="modified",
                hunks=[
                    DiffHunk(
                        id="app.py:12",
                        old_start=12,
                        old_lines=3,
                        new_start=12,
                        new_lines=4,
                        lines=[
                            DiffLine(
                                kind="context",
                                content="def main():",
                                old_line=12,
                                new_line=12,
                            ),
                            DiffLine(kind="delete", content="    pass", old_line=13),
                            DiffLine(kind="add", content="    run()", new_line=13),
                        ],
                        actions=[
                            DiffAction(
                                action="revert_hunk",
                                payload={"hunk_id": "app.py:12"},
                            )
                        ],
                    )
                ],
            ),
            DiffFile(
                old_path="old.bin",
                new_path="data/new.bin",
                status="renamed",
                binary=True,
            ),
        ]
    )

    data = diff.to_dict()
    assert data == {
        "type": "diff",
        "files": [
            {
                "old_path": "src/app.py",
                "new_path": "src/app.py",
                "status": "modified",
                "binary": False,
                "hunks": [
                    {
                        "id": "app.py:12",
                        "old_start": 12,
                        "old_lines": 3,
                        "new_start": 12,
                        "new_lines": 4,
                        "lines": [
                            {
                                "kind": "context",
                                "content": "def main():",
                                "old_line": 12,
                                "new_line": 12,
                            },
                            {"kind": "delete", "content": "    pass", "old_line": 13},
                            {"kind": "add", "content": "    run()", "new_line": 13},
                        ],
                        "actions": [
                            {"action": "revert_hunk", "payload": {"hunk_id": "app.py:12"}}
                        ],
                        "truncated": False,
                    }
                ],
                "truncated": False,
            },
            {
                "old_path": "old.bin",
                "new_path": "data/new.bin",
                "status": "renamed",
                "binary": True,
                "hunks": [],
                "truncated": False,
            },
        ],
        "truncated": False,
    }
    assert list(data)[0] == "type"
    assert "style" not in data


def test_empty_diff_and_findings_default_wire():
    assert Diff().to_dict() == {"type": "diff", "files": [], "truncated": False}
    assert Findings().to_dict() == {
        "type": "findings",
        "findings": [],
        "truncated": False,
    }


def test_binary_file_marker_round_trips():
    diff = Diff(
        files=[
            {
                "old_path": "assets/logo.bin",
                "new_path": "assets/logo.bin",
                "status": "modified",
                "binary": True,
            }
        ]
    )
    wire = diff.to_dict()
    assert wire["files"][0]["binary"] is True
    assert wire["files"][0]["hunks"] == []
    restored = Primitive.from_dict(wire)
    assert type(restored) is Diff
    assert restored.to_dict() == wire


def test_diff_accepts_common_primitive_fields():
    diff = Diff(css={"max-height": "400px"}, class_name="review-diff")
    wire = diff.to_dict()
    assert wire["css"] == {"max-height": "400px"}
    assert wire["class"] == "review-diff"


def test_line_numbers_are_omitted_when_unset_and_kept_when_set():
    assert DiffLine().model_dump() == {"kind": "context", "content": ""}
    wire = DiffLine(kind="add", content="x", new_line=7).model_dump()
    assert wire == {"kind": "add", "content": "x", "new_line": 7}


@pytest.mark.parametrize("kind", ["moved", "insert", "", "CONTEXT", "modified"])
def test_unknown_line_kinds_are_refused(kind):
    with pytest.raises(ValidationError):
        DiffLine(kind=kind)


def test_unknown_line_kind_is_refused_nested_in_a_diff():
    with pytest.raises(ValidationError):
        Diff(files=[{"hunks": [{"id": "h1", "lines": [{"kind": "moved"}]}]}])


@pytest.mark.parametrize("status", ["moved", "copied", ""])
def test_unknown_file_statuses_are_refused(status):
    with pytest.raises(ValidationError):
        DiffFile(status=status)


def test_hunk_id_is_required_and_non_empty():
    with pytest.raises(ValidationError):
        DiffHunk()
    with pytest.raises(ValidationError):
        DiffHunk(id="")


def test_empty_action_ids_are_refused():
    with pytest.raises(ValidationError):
        DiffAction(action="")
    with pytest.raises(ValidationError):
        DiffHunk(id="h1", actions=[{"action": ""}])


def test_duplicate_hunk_ids_within_a_file_are_refused():
    with pytest.raises(ValidationError):
        Diff(files=[{"hunks": [{"id": "a"}, {"id": "a"}]}])


def test_duplicate_hunk_ids_across_files_are_refused():
    with pytest.raises(ValidationError):
        Diff(files=[{"hunks": [{"id": "shared"}]}, {"hunks": [{"id": "shared"}]}])


def test_oversized_files_are_truncated_with_the_flag_set():
    diff = Diff(files=_files_for(MAX_DIFF_FILES + 3))
    assert diff.truncated is True
    assert len(diff.files) == MAX_DIFF_FILES
    assert [item.new_path for item in diff.files] == [
        f"f{index}.py" for index in range(MAX_DIFF_FILES)
    ]


def test_oversized_hunks_are_truncated_with_the_flag_set():
    diff = Diff(files=[_file(0, hunk_count=MAX_DIFF_HUNKS_PER_FILE + 1)])
    item = diff.files[0]
    assert item.truncated is True
    assert len(item.hunks) == MAX_DIFF_HUNKS_PER_FILE
    assert diff.truncated is False


def test_oversized_lines_are_truncated_with_the_flag_set():
    diff = Diff(files=[_file(0, line_count=MAX_DIFF_LINES_PER_HUNK + 1)])
    hunk = diff.files[0].hunks[0]
    assert hunk.truncated is True
    assert len(hunk.lines) == MAX_DIFF_LINES_PER_HUNK
    assert diff.files[0].truncated is False
    assert diff.truncated is False


def test_hunk_and_line_truncation_flags_coexist():
    diff = Diff(
        files=[
            _file(
                0,
                hunk_count=MAX_DIFF_HUNKS_PER_FILE + 1,
                line_count=MAX_DIFF_LINES_PER_HUNK + 1,
            )
        ]
    )
    item = diff.files[0]
    assert item.truncated is True
    assert len(item.hunks) == MAX_DIFF_HUNKS_PER_FILE
    assert all(hunk.truncated for hunk in item.hunks)
    assert all(len(hunk.lines) == MAX_DIFF_LINES_PER_HUNK for hunk in item.hunks)


def test_truncation_flags_survive_the_wire_round_trip():
    diff = Diff(files=_files_for(MAX_DIFF_FILES + 1))
    wire = diff.to_dict()
    assert wire["truncated"] is True
    restored = Primitive.from_dict(wire)
    assert restored.truncated is True
    assert restored.to_dict() == wire


def test_maximum_file_bound_does_not_truncate_and_round_trips():
    diff = Diff(files=_files_for(MAX_DIFF_FILES))
    assert diff.truncated is False
    assert all(item.truncated is False for item in diff.files)
    assert Primitive.from_dict(diff.to_dict()).to_dict() == diff.to_dict()


def test_maximum_hunk_bound_does_not_truncate_and_round_trips():
    diff = Diff(files=[_file(0, hunk_count=MAX_DIFF_HUNKS_PER_FILE)])
    assert diff.files[0].truncated is False
    assert Primitive.from_dict(diff.to_dict()).to_dict() == diff.to_dict()


def test_maximum_line_bound_does_not_truncate_and_round_trips():
    diff = Diff(files=[_file(0, line_count=MAX_DIFF_LINES_PER_HUNK)])
    assert diff.files[0].hunks[0].truncated is False
    assert Primitive.from_dict(diff.to_dict()).to_dict() == diff.to_dict()


def test_diff_round_trips_through_from_dict_adapter_and_json():
    diff = Diff(files=[_file(0, hunk_count=2, line_count=2)])
    wire = diff.to_dict()
    restored = Primitive.from_dict(wire)
    assert type(restored) is Diff
    assert restored.to_dict() == wire
    adapted = primitive_adapter.validate_python(wire)
    assert type(adapted) is Diff
    assert adapted.to_dict() == wire
    assert json.loads(diff.to_json()) == wire


def test_findings_golden_wire_shape():
    findings = Findings(
        findings=[
            Finding(
                title="Missing null check",
                body="Dereferencing config raises when the key is absent.",
                file="src/config.py",
                start_line=42,
                end_line=45,
                priority="P1",
                category="correctness",
                diff_ref="config.py:42",
            ),
            Finding(title="Naming nit"),
        ]
    )
    data = findings.to_dict()
    assert data == {
        "type": "findings",
        "findings": [
            {
                "title": "Missing null check",
                "body": "Dereferencing config raises when the key is absent.",
                "file": "src/config.py",
                "start_line": 42,
                "end_line": 45,
                "priority": "P1",
                "category": "correctness",
                "diff_ref": "config.py:42",
            },
            {
                "title": "Naming nit",
                "body": "",
                "file": "",
                "start_line": 0,
                "end_line": 0,
                "priority": "P3",
                "category": "",
            },
        ],
        "truncated": False,
    }
    assert list(data)[0] == "type"


@pytest.mark.parametrize("priority", ["P4", "p0", "critical", ""])
def test_unknown_priorities_are_refused(priority):
    with pytest.raises(ValidationError):
        Finding(priority=priority)


def test_unknown_priority_is_refused_nested_in_findings():
    with pytest.raises(ValidationError):
        Findings(findings=[{"title": "t", "priority": "P9"}])


@pytest.mark.parametrize("start,end", [(5, 4), (1, 0)])
def test_inverted_line_ranges_are_refused(start, end):
    with pytest.raises(ValidationError):
        Finding(start_line=start, end_line=end)


def test_negative_line_numbers_are_refused():
    with pytest.raises(ValidationError):
        Finding(start_line=-1)
    with pytest.raises(ValidationError):
        Finding(end_line=-1)


def test_findings_truncation_sets_the_flag_and_keeps_the_prefix():
    findings = Findings(
        findings=[{"title": f"t{index}"} for index in range(MAX_FINDINGS + 2)]
    )
    assert findings.truncated is True
    assert len(findings.findings) == MAX_FINDINGS
    assert [item.title for item in findings.findings] == [
        f"t{index}" for index in range(MAX_FINDINGS)
    ]


def test_maximum_finding_bound_does_not_truncate_and_round_trips():
    findings = Findings(findings=[{"title": f"t{index}"} for index in range(MAX_FINDINGS)])
    assert findings.truncated is False
    assert Primitive.from_dict(findings.to_dict()).to_dict() == findings.to_dict()


def test_findings_round_trip_preserves_diff_ref_and_omits_none():
    findings = Findings(findings=[{"title": "t", "diff_ref": "h1"}, {"title": "u"}])
    wire = findings.to_dict()
    assert wire["findings"][0]["diff_ref"] == "h1"
    assert "diff_ref" not in wire["findings"][1]
    restored = Primitive.from_dict(wire)
    assert type(restored) is Findings
    assert restored.to_dict() == wire
    assert json.loads(findings.to_json()) == wire


def test_review_primitives_nest_in_containers_and_response_envelope():
    diff = Diff(files=[_file(0)])
    findings = Findings(findings=[{"title": "t"}])
    container = Container().add(diff, findings)
    wire = container.to_dict()
    assert [child["type"] for child in wire["children"]] == ["diff", "findings"]
    assert Primitive.from_dict(wire).to_dict() == wire
    response = create_ui_response([diff, findings])
    assert [component["type"] for component in response["_ui_components"]] == [
        "diff",
        "findings",
    ]
    assert response["_data"] is None


def test_wire_schema_covers_and_validates_the_review_vocabulary():
    schema = wire_schema()
    for name in (
        "diff",
        "findings",
        "diff_file",
        "diff_hunk",
        "diff_line",
        "diff_action",
        "finding",
    ):
        assert name in schema["$defs"]
    validator = Draft202012Validator(schema)
    validator.validate(Diff(files=[_file(0, line_count=1)]).to_dict())
    validator.validate(
        Findings(findings=[{"title": "t", "priority": "P0"}]).to_dict()
    )
    assert "id" in schema["$defs"]["diff_hunk"]["required"]
