# AstralPrimitives Agent Guide

`AGENTS.md` is the single repository instruction file for all coding agents. Update it directly; do not create a separate agent-specific guide.

`astralprims`: composable, serializable UI primitives for Python. Each primitive is a
pydantic-v2 model that validates on construction and serializes to a plain wire dict. JSON
is the wire format; pydantic is only the authoring layer.

This package is the **"define" stage** of [AstralDeep](https://github.com/AstralDeep)'s
server-driven UI: *AstralPrimitives defines → AstralProjection renders and adapts → AstralDeep orchestrates.*
It is consumed there as an ordinary pip dependency, and it releases on its own train.

## Layout

Start with these files:

- `src/astralprims/base.py` — `Primitive` (the base), `SerModel` (nested non-primitive
  helpers), the `_REGISTRY` type→class map, and `Primitive.from_dict`.
- `src/astralprims/primitives.py` — the concrete primitive definitions; derive the current vocabulary from their type literals.
- `src/astralprims/__init__.py` — public surface, `__version__`, and the `AnyPrimitive`
  discriminated union + `primitive_adapter`.
- `src/astralprims/response.py` — `create_ui_response()`.
- `tests/test_primitives.py` — serialization shape, nesting, `from_dict` round-trips,
  adapter validation.

Dependencies stay thin on purpose: `pydantic>=2`, `requires-python >=3.9`, hatchling.

## Comments

The code documents itself (AstralDeep Constitution VI). Each file opens with a header of at most three sentences on what it does and how it connects to other files. Add no other comments or docstrings except a one-line *why* where absolutely necessary; primitive documentation lives in `README.md`. No spec IDs, history, TODOs, or narration in source. Tool directives (`# noqa`, `# type: ignore`, `# pragma: no cover`) stay.

## Dev workflow

```bash
pip install -e ".[dev]"
pytest
```

## Release model — read this before merging

`.github/workflows/ci.yml` qualifies pull requests with locked tooling, including
branch and changed-line coverage, both distribution formats, and a clean-install smoke test.
`.github/workflows/python-publish.yml` runs only on push to `main`; its unprivileged job
tests and builds before the environment-protected publisher receives OIDC and uploads the
verified artifact. It asks PyPI whether the current `pyproject.toml` version already exists
and uploads only if it does not (OIDC trusted publishing; no stored token).

Two consequences that bite:

- **`version` in `pyproject.toml` is the sole release marker.** There are no git tags.
  Merging a primitive does not ship it — the bump does. Bump in the same PR that adds it.
- **Publication does not replace PR qualification.** The release workflow repeats the
  locked tests and package checks without OIDC before its isolated publisher runs.

Consumers pin their own package/component revisions. Check their current manifests and
installed package versions before importing a newly added class; a running image can lag
this repository. New wire types may use an approved plain dict until the matching package
is installed. A documentation-only change does not require a package version bump.

## Serialization contract

`Primitive._serialize` is a `@model_serializer(mode="plain")`, so `.to_dict()` /
`.model_dump()` bypass pydantic's default serializer and emit exactly this shape:

1. `"type"` first, from the subclass's `Literal` default.
2. `None` fields are dropped.
3. An empty `css` block is omitted (only `css` — an empty `payload` still appears).
4. `class_name` serializes as `"class"`; `populate_by_name` lets you construct with either.
5. Nested models serialize themselves — `children`, `content`, `tabs` recurse.
6. `attributes` is merged **last**, at the top level.

Gotchas:

- `to_dict()` returns a dict; **`to_json()` returns a string.** Passing the latter where a
  component dict is expected is the classic error.
- The styling field is **`css`** (kebab-case CSS properties), never `style`.
- Because `attributes` merges last, it can **silently overwrite any field, including
  `type`**. It is a trusted-input escape hatch — do not splat user data into it.
- `model_config` sets `extra="ignore"`, so a typo'd constructor kwarg is silently dropped
  (`Button(labl="x")` raises nothing). Note the asymmetry: `from_dict` funnels unknown
  *dict* keys into `attributes`, but the *constructor* discards unknown kwargs.
- `Grid` is an alias for the class `Grids`, whose wire `type` is `"grid"`.

### Adding a primitive

Subclassing is registration: `__pydantic_init_subclass__` reads the `type` default and
writes `_REGISTRY[default] = cls`. So:

- Pick a `type` string that does not collide with a built-in — a collision **silently
  replaces** the built-in in the registry.
- The union snapshots `_REGISTRY` at import time. After defining a custom primitive, call
  `rebuild_primitive_union()` or `primitive_adapter` will not see it.
- Adding a primitive to the AstralDeep vocabulary additionally requires Constitution VIII
  approval, documentation, and coordinated changes to AstralProjection's
  `contracts/ui_protocol.json`, renderers, ROTE, affected clients, and drift guards,
  followed by the consuming AstralDeep composition pin. Keep the repositories' release
  trains distinct; a package-only change does not update a deployed client.
- Update the primitive table in `README.md`. It has drifted before.

## Knowledge graph

Use the `kos-wiki` repository supplied by the current workspace, not historical absolute
paths. Read its `AGENTS.md` and `index.md` before editing. Relevant curated pages are:

- `wiki/astral-primitives.md` — package vocabulary and release model.
- `wiki/astral-primitive-serialization-contract.md` — serialization rules.
- `wiki/astral-sdui-pipeline.md` — ownership and cross-repository flow.

Refresh the vault at major checkpoints, especially a version bump, a primitive addition
or removal, a PR merge, or a durable decision. Re-anchor the reviewed repository commit,
revise affected claims against the live tree, update `index.md`, append to `log.md`, then
commit and push the vault separately under its standing authorization. Never add raw
artifacts, credentials, or user data. Report any blocked vault commit or push.

When checking vocabulary parity, compare `type: Literal[...]` declarations in
`src/astralprims/primitives.py` with `component_types` in the pinned AstralProjection
`contracts/ui_protocol.json`. Resolve both repositories from the current workspace,
check that both inputs are nonempty, and distinguish manifest-only renderer types from
primitive classes. Do not use historical class counts as the current expected result.
