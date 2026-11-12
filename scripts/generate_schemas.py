"""Writes the committed schema files (wire schema, strict generation profile, A2UI catalog) from the
package code, or with --check verifies they are current. tests/test_schema_files.py runs the same check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]


def targets() -> Dict[Path, Callable[[], Dict[str, Any]]]:
    from astralprims import a2ui_catalog, strict_schema, wire_schema

    return {
        ROOT / "schema" / "astralprims.wire.json": wire_schema,
        ROOT / "schema" / "astralprims.generation.strict.json": strict_schema,
        ROOT / "a2ui" / "catalog.json": a2ui_catalog,
    }


def render(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate or check the committed schema files.")
    parser.add_argument("--check", action="store_true", help="fail if a file differs instead of writing it")
    stale = []
    check = parser.parse_args(argv).check
    for path, build in targets().items():
        text = render(build())
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if check and stale:
        print("stale: " + ", ".join(str(p.relative_to(ROOT)) for p in stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
