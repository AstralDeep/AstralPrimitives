"""Run six maintained broken guards against focused public-package acceptance tests.
Each isolated mutation must fail its named case without collection or import errors.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


MUTATIONS = (
    (
        "registry-collision",
        "base.py",
        "if existing is not None and existing is not cls:",
        "if False:",
        "test_registry_collision_keeps_original_and_adapter",
    ),
    (
        "nonfinite-float",
        "base.py",
        "        _assert_finite_float(value, path)\n        return value",
        "        return value",
        "test_nested_nonfinite_values_never_reach_json",
    ),
    (
        "attributes-precedence",
        "base.py",
        "            out.update(attributes)",
        "            out = {**attributes, **out}",
        "test_trusted_attributes_override_declared_fields",
    ),
    (
        "chart-helper-coercion",
        "primitives.py",
        "return [item.model_dump() if isinstance(item, ChartDataset) else item for item in datasets]",
        "return datasets",
        "test_mixed_chart_helpers_have_literal_wire",
    ),
    (
        "unrelated-chart-model",
        "primitives.py",
        "isinstance(item, ChartDataset)",
        'hasattr(item, "model_dump")',
        "test_unrelated_chart_models_are_rejected_without_serializing",
    ),
    (
        "empty-payload",
        "base.py",
        'if name == "css" and not value:',
        'if name in ("css", "payload") and not value:',
        "test_released_wire_fixtures",
    ),
)


def classify_result(returncode: int, report: Path, test_name: str, mutant: bool) -> str:
    try:
        document = ET.parse(report)
    except (OSError, ET.ParseError) as error:
        raise ValueError("missing or malformed focused-test report") from error
    cases = document.findall(".//testcase")
    if len(cases) != 1 or cases[0].get("name") != test_name:
        raise ValueError("focused test was not collected exactly once")
    if document.findall(".//error") or document.findall(".//skipped"):
        raise ValueError("collection, execution error, or skip is not a mutation kill")
    failures = document.findall(".//failure")
    if any(
        any(
            word in ET.tostring(failure, encoding="unicode")
            for word in (
                "ImportError",
                "ModuleNotFoundError",
                "SyntaxError",
                "NameError",
                "AttributeError",
            )
        )
        for failure in failures
    ):
        raise ValueError("broken imports or execution are not a mutation kill")
    if not mutant:
        if returncode or failures:
            raise ValueError("unmodified acceptance control failed")
        return "passed"
    if returncode != 1 or len(failures) != 1:
        raise ValueError(
            "mutation survived or pytest did not report a behavioral failure"
        )
    return "killed"


def run_case(root: Path, mutation, mutant: bool) -> str:
    name, source, original, replacement, test_name = mutation
    with tempfile.TemporaryDirectory(prefix="astralprims-mutation-") as directory:
        target = Path(directory)
        shutil.copytree(root / "src", target / "src")
        (target / "tests").mkdir()
        shutil.copy(root / "tests/test_release_acceptance.py", target / "tests")
        shutil.copytree(root / "tests/fixtures", target / "tests/fixtures")
        source_path = target / "src/astralprims" / source
        text = source_path.read_text(encoding="utf-8")
        if text.count(original) != 1:
            raise ValueError(
                f"mutation {name} needs one maintained target, found {text.count(original)}"
            )
        if mutant:
            source_path.write_text(
                text.replace(original, replacement), encoding="utf-8"
            )
        report = target / "result.xml"
        environment = dict(
            os.environ,
            PYTHONPATH=str(target / "src"),
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        )
        environment.pop("PYTEST_ADDOPTS", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"tests/test_release_acceptance.py::{test_name}",
                f"--junitxml={report}",
            ],
            cwd=target,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        try:
            return classify_result(result.returncode, report, test_name, mutant)
        except ValueError as error:
            raise ValueError(
                f"{name}: {error}\n{result.stdout}\n{result.stderr}"
            ) from error


def main() -> int:
    results = []
    try:
        for mutation in MUTATIONS:
            control = run_case(Path.cwd(), mutation, mutant=False)
            killed = run_case(Path.cwd(), mutation, mutant=True)
            results.append(
                {
                    "mutation": mutation[0],
                    "test": mutation[4],
                    "control": control,
                    "mutation_result": killed,
                }
            )
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(
            json.dumps(
                {"status": "error", "reason": str(error), "results": results}, indent=2
            )
        )
        return 1
    print(
        json.dumps(
            {"status": "pass", "mutations": len(results), "results": results}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
