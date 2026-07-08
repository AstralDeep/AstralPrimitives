# Astral-Primitives — working notes

`astralprims`: composable, serializable UI primitives for Python. Each primitive is a
pydantic-v2 model that validates on construction and serializes to a plain wire dict. JSON
is the wire format; pydantic is only the authoring layer.

This package is the **"define" stage** of [AstralBody](https://github.com/AstralDeep)'s
server-driven UI: *astralprims defines → the orchestrator renders → ROTE adapts per device.*
It is consumed there as an ordinary pip dependency, and it releases on its own train.

## Layout

Five files, small enough to read end to end:

- `src/astralprims/base.py` — `Primitive` (the base), `SerModel` (nested non-primitive
  helpers), the `_REGISTRY` type→class map, and `Primitive.from_dict`.
- `src/astralprims/primitives.py` — the 32 concrete primitives.
- `src/astralprims/__init__.py` — public surface, `__version__`, and the `AnyPrimitive`
  discriminated union + `primitive_adapter`.
- `src/astralprims/response.py` — `create_ui_response()`.
- `tests/test_primitives.py` — serialization shape, nesting, `from_dict` round-trips,
  adapter validation.

Dependencies stay thin on purpose: `pydantic>=2`, `requires-python >=3.9`, hatchling.

## Dev workflow

```bash
pip install -e ".[dev]"
pytest
```

## Release model — read this before merging

`.github/workflows/python-publish.yml` is the **only** workflow. On push to `main` it
builds, asks PyPI whether the current `pyproject.toml` version already exists, and uploads
only if it does not (OIDC trusted publishing; no stored token).

Two consequences that bite:

- **`version` in `pyproject.toml` is the sole release marker.** There are no git tags.
  Merging a primitive does not ship it — the bump does. Bump in the same PR that adds it.
- **CI never runs the tests.** A green PyPI release is not evidence `pytest` passes. Run it
  locally before merging; this repo has none of AstralBody's drift guards.

AstralBody pins a version *floor* (`astralprims>=0.2.0` in `backend/requirements.txt`), so
its container image can lag this repo's HEAD. New component types therefore often have
renderers in AstralBody before the class exists here, and agents emit them as plain dicts in
the meantime. That is the normal pattern, not a bug.

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
- Adding a primitive to the AstralBody vocabulary additionally requires Constitution VIII
  approval, documentation, and a same-PR edit to `backend/shared/ui_protocol.json` — four
  drift guards fail otherwise. Those guards live in the AstralBody repo, not this one.
- Update the primitive table in `README.md`. It has drifted before.

## Knowledge graph

An LLM-maintained wiki mirrors this repo at `/Users/sam/Desktop/Work/obsidian-vault` (its
own git repo; read its `CLAUDE.md` for the schema). The relevant pages:

- `wiki/sources/astral-primitives-repo.md` — the anchor: filesystem path + the commit last
  reviewed. Every claim derived from this repo cites it.
- `wiki/entities/astralprims.md` — the package: primitive table, the 32-vs-35 gap, release
  model.
- `wiki/concepts/Primitive Serialization Contract.md` — the rules above, in depth.

**Refresh it at every checkpoint.** Anchors go stale silently: a version bump or a new
primitive class invalidates claims on those pages and the 32-vs-35 count on
`wiki/concepts/SDUI Pipeline.md`. The vault has already carried one stale claim this way
(`astralprims>=0.1.0` long after the real pin moved to `>=0.2.0`).

Triggers specific to this repo: **a `version` bump in `pyproject.toml`** (the release
marker) or **adding/removing a primitive class**. Also on the usual checkpoints — a PR
merged, a feature shipped, a notable decision made.

When triggered, follow the vault's `Operation: SESSION CHECKPOINT`:

1. Re-anchor `reviewed_commit:` in `wiki/sources/astral-primitives-repo.md` to this repo's
   HEAD.
2. **Revise** the affected pages — don't just append. Re-verify counts against the working
   tree rather than trusting a stale page; if a new fact contradicts an existing page, say
   so explicitly on the page.
3. Append a `log.md` entry, update `index.md` if pages were added or renamed.
4. Commit the vault repo.

A useful cross-check when the vocabulary changes — the class list against AstralBody's wire
manifest:

Absolute paths on purpose — the two halves live in different repos, and a wrong cwd makes
`prims.txt` empty, which reads as "every wire type is missing a class" rather than as an
error.

```bash
P=/Users/sam/Desktop/Work/Astral-Primitives
A=/Users/sam/Desktop/Work/AstralBody

grep -oE 'type: Literal\["[a-z_]+"\]' "$P/src/astralprims/primitives.py" \
  | sed 's/.*\["//;s/"\]//' | sort > /tmp/prims.txt
python3 -c "import json;print('\n'.join(sorted(json.load(open('$A/backend/shared/ui_protocol.json'))['component_types'])))" \
  > /tmp/wire.txt

wc -l /tmp/prims.txt /tmp/wire.txt      # sanity: neither may be 0
comm -13 /tmp/prims.txt /tmp/wire.txt   # wire types with a renderer but no class
comm -23 /tmp/prims.txt /tmp/wire.txt   # classes not in the manifest — should be empty
```

At `a204ec6` that prints 32 and 35, with `download_card`, `generative`, `skeleton` in the
first diff and nothing in the second.
