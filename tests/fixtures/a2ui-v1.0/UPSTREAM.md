# A2UI 1.0 conformance fixtures

These unmodified schemas come from a2ui-project/a2ui commit `8bf644a37d680a227296b8c0849a7f4b328b8b73` (2026-11-12), checked after the stable 1.0 announcement of 2026-11-11. They are covered by the adjacent upstream Apache 2.0 license.

- Protocol schemas: `specification/v1_0/json/`.
- `basic_catalog.json`: `catalogs/basic/v1/catalog.json`.
- Source: https://github.com/a2ui-project/a2ui/tree/8bf644a37d680a227296b8c0849a7f4b328b8b73

Conformance tests resolve every reference locally. Updating the snapshot requires reviewing upstream protocol changes and both Python and Rust adapters; tests never download schemas.
