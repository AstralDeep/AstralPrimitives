"""Qualify shipped Python changes against an immutable event-base tree.
Independent wire fixtures and released exports enforce the package's version policy.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


FIXTURE_PATH = "tests/fixtures/released_wire.json"
PROBE = """import json, sys
sys.path.insert(0, sys.argv[1])
from astralprims import Primitive
cases = json.loads(sys.argv[2])
actual = []
for case in cases:
    try:
        actual.append(Primitive.from_dict(case['input']).to_dict())
    except Exception as error:
        actual.append({'error': type(error).__name__})
print(json.dumps(actual, allow_nan=False))
"""


class SemanticTree(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)

    def visit_Module(self, node):
        node.body = [
            item
            for item in node.body
            if not (
                isinstance(item, ast.Assign)
                and len(item.targets) == 1
                and isinstance(item.targets[0], ast.Name)
                and item.targets[0].id == "__version__"
            )
        ]
        return self.generic_visit(node)


def _version(value: str):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError(f"invalid release version {value!r}")
    return tuple(map(int, value.split(".")))


def _surface(sources: Dict[str, str]):
    exports = set()
    declarations = {}
    trees = {path: ast.parse(text) for path, text in sources.items()}
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exports.update(ast.literal_eval(node.value))
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id in exports
                        and target.id != "__all__"
                    ):
                        declarations[target.id] = {
                            "binding": ast.dump(node.value, include_attributes=False)
                        }
            if isinstance(node, ast.ClassDef) and node.name in exports | {"SerModel"}:
                declarations[node.name] = {
                    child.target.id: ast.dump(child, include_attributes=False)
                    for child in node.body
                    if isinstance(child, ast.AnnAssign)
                    and isinstance(child.target, ast.Name)
                }
                for child in node.body:
                    if isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and not child.name.startswith("_"):
                        declarations[node.name]["method:" + child.name] = ast.dump(
                            child.args, include_attributes=False
                        )
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in exports
            ):
                declarations[node.name] = {
                    "signature": ast.dump(node.args, include_attributes=False)
                }
    return exports, declarations


def qualify_sources(
    base: Dict[str, str],
    candidate: Dict[str, str],
    base_version: str,
    candidate_version: str,
    wire_changed: bool = False,
) -> Dict[str, Any]:
    before, after = _version(base_version), _version(candidate_version)

    def normalize(text):
        return ast.dump(SemanticTree().visit(ast.parse(text)), include_attributes=False)

    changed = sorted(
        path
        for path in base.keys() | candidate.keys()
        if path not in base
        or path not in candidate
        or normalize(base[path]) != normalize(candidate[path])
    )
    old_exports, old_fields = _surface(base)
    new_exports, new_fields = _surface(candidate)
    removed = sorted(old_exports - new_exports)
    added = sorted(new_exports - old_exports)
    breaking = bool(removed or wire_changed)
    additive = bool(added)
    for name, fields in old_fields.items():
        current = new_fields.get(name, {})
        breaking |= any(current.get(field) != value for field, value in fields.items())
        additive |= bool(current.keys() - fields.keys())
    required = (
        "major"
        if breaking and before[0]
        else "minor"
        if breaking or additive
        else "patch"
        if changed
        else "none"
    )
    allowed = {
        "none": after >= before,
        "patch": after > before,
        "minor": after[:2] > before[:2],
        "major": after[0] > before[0],
    }[required]
    if not allowed:
        raise ValueError(
            f"{required} version bump required: {base_version} -> {candidate_version}"
        )
    return {
        "required_bump": required,
        "base_version": base_version,
        "candidate_version": candidate_version,
        "runtime_changed_paths": changed,
        "removed_exports": removed,
        "added_exports": added,
        "wire_changed": wire_changed,
    }


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot inspect Git tree: {result.stderr.strip()}")
    return result.stdout


def _tree(root: Path, revision: str) -> Dict[str, str]:
    paths = _git(
        root, "ls-tree", "-r", "--name-only", revision, "src/astralprims"
    ).splitlines()
    sources = {
        path.removeprefix("src/astralprims/"): _git(root, "show", f"{revision}:{path}")
        for path in paths
        if path.endswith(".py")
    }
    if not sources:
        raise ValueError("package source tree is empty")
    return sources


def _manifest_version(text: str) -> str:
    match = re.search(r'(?m)^version = "([^"]+)"$', text)
    if not match:
        raise ValueError("manifest version is missing")
    return match[1]


def _check_versions(sources: Dict[str, str], manifest: str, lock: str) -> str:
    version = _manifest_version(manifest)
    tree = ast.parse(sources["__init__.py"])
    runtime = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    ]
    locked = re.findall(
        r'\[\[package\]\]\nname = "astralprims"\nversion = "([^"]+)"', lock
    )
    if runtime != [version] or locked != [version]:
        raise ValueError("manifest, runtime, and lock versions must agree")
    return version


def _probe(sources: Dict[str, str], fixture: list) -> list:
    with tempfile.TemporaryDirectory(prefix="astralprims-release-") as directory:
        package = Path(directory) / "astralprims"
        package.mkdir()
        for path, text in sources.items():
            target = package / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-I", "-c", PROBE, directory, json.dumps(fixture)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise ValueError(f"package probe failed: {result.stderr.strip()}")
        return json.loads(result.stdout)


def qualify_tree(root: Path, base_sha: str) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha) or base_sha == "0" * 40:
        raise ValueError("base must be a nonzero 40-hex immutable commit SHA")
    if (
        _git(root, "rev-parse", "--verify", f"{base_sha}^{{commit}}").strip()
        != base_sha
    ):
        raise ValueError("base is not a commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("tracked tree is dirty")
    candidate_sha = _git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    base, candidate = _tree(root, base_sha), _tree(root, candidate_sha)
    base_version = _check_versions(
        base,
        _git(root, "show", f"{base_sha}:pyproject.toml"),
        _git(root, "show", f"{base_sha}:uv.lock"),
    )
    candidate_version = _check_versions(
        candidate,
        _git(root, "show", f"{candidate_sha}:pyproject.toml"),
        _git(root, "show", f"{candidate_sha}:uv.lock"),
    )
    fixture_revision = (
        base_sha
        if FIXTURE_PATH
        in _git(root, "ls-tree", "-r", "--name-only", base_sha).splitlines()
        else candidate_sha
    )
    fixture = json.loads(_git(root, "show", f"{fixture_revision}:{FIXTURE_PATH}"))
    if not isinstance(fixture, list) or not fixture:
        raise ValueError("released wire fixture is empty or malformed")
    expected = [case["expected"] for case in fixture]
    if _probe(base, fixture) != expected:
        raise ValueError("released wire fixture does not match immutable base behavior")
    decision = qualify_sources(
        base,
        candidate,
        base_version,
        candidate_version,
        _probe(candidate, fixture) != expected,
    )
    decision.update(
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        fixture_sha=fixture_revision,
        fixture_cases=len(fixture),
        status="pass",
    )
    return decision


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args(argv)
    try:
        decision = qualify_tree(Path.cwd(), args.base_sha)
    except (
        ValueError,
        OSError,
        SyntaxError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(json.dumps({"status": "error", "reason": str(error)}))
        return 1
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
