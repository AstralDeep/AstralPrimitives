# AstralPrimitives Constitution

## Core Principles

### I. Define, Never Render

`astralprims` defines UI primitives and their wire representation. It is the define stage of
the Astral UI contract: AstralPrimitives defines → AstralProjection renders and adapts →
AstralDeep orchestrates.

- Each primitive MUST be a pydantic v2 model that validates on construction and serializes to
  a plain JSON-compatible dict. JSON is the wire format; pydantic is only the authoring layer.
- The package MUST NOT render, escape, sanitize, adapt per device, orchestrate, authorize, or
  perform file, network, or other I/O. Rendering and device adaptation belong to
  AstralProjection; orchestration and vocabulary adoption belong to AstralDeep.
- Supporting a new client target MUST NOT require changing a primitive definition.
- Composite readouts MUST NOT carry color fields: their variant strings name semantic roles
  that renderers resolve from the active theme. New primitives SHOULD follow the same
  semantic-variant approach.

**Rationale**: Keeping definition separate from presentation keeps the wire contract stable
while renderers and clients evolve without coordinated releases of this package.

### II. Stable Wire Contract

The serialized shape is a public contract read by AstralProjection's renderers, the Swift
mirror in the Apple clients, and AstralDeep's agents.

- `to_dict()` and `model_dump()` MUST emit exactly this shape: `type` first; `None` fields
  dropped; an empty `css` block omitted (only `css`; an empty `payload` still appears);
  `class_name` serialized as `"class"`; nested models serialized recursively; and
  `attributes` merged last at the top level.
- Non-`None` defaults are emitted and are therefore part of the wire contract.
- `to_dict()` returns a dict and `to_json()` returns a JSON string. Code that needs a
  component dict MUST use `to_dict()` or `create_ui_response()`.
- `Primitive.from_dict()` MUST resolve the class by `type` through the registry, reject a
  missing or unknown `type`, and carry unknown keys into `attributes`.
- `attributes` is a trusted-input escape hatch that can overwrite any field, including
  `type`; callers MUST NOT place user- or model-supplied data in it.
- The styling field is `css` (kebab-case CSS properties), never `style`.
- A change to any rule above is a wire change under Principle III and MUST update the
  serialization tests in the same change.

### III. Versioned, Additive Evolution

- `version` in `pyproject.toml` is the sole release marker, and `astralprims.__version__`
  MUST equal it. There are no git tags.
- A change that alters shipped behavior of `src/astralprims/` (wire output, public API, or
  validation) MUST bump the version in the same pull request. A change confined to
  documentation, tests, CI, or repository tooling needs no bump.
- Breaking changes are removing or renaming a primitive, wire `type`, field, or public name;
  changing a serialization rule or an emitted default; and narrowing accepted input. While
  the major version is 0, a breaking change MUST bump the minor version and be called out in
  the pull request; from 1.0.0 on, semantic versioning applies to the wire contract and the
  public Python API. New primitives or optional fields bump the minor version; fixes that
  leave wire output unchanged bump the patch version.
- A renamed public class MUST keep a compatibility alias (as `Grid` does for `Grids`) until
  an explicitly breaking release.

### IV. Governed Vocabulary

- Every primitive MUST declare a unique snake_case wire `type` as a `Literal` default. A
  colliding `type` silently replaces the registered class and is prohibited.
- Every primitive MUST be documented in `README.md` (its class, wire `type`, and fields)
  before it ships, and the README primitive table MUST be updated in the same change.
- Adding a primitive to the Astral vocabulary requires the owner's approval and a
  coordinated change: here, the definition, README entry, tests, and version bump; then,
  under AstralProjection's constitution, `contracts/ui_protocol.json`, renderers, ROTE,
  affected clients, and drift guards; then AstralDeep's composition pin.
- Vocabulary parity is checked by comparing the `type` literals in
  `src/astralprims/primitives.py` with `component_types` in the pinned AstralProjection
  manifest. Manifest-only renderer types are allowed; a type released here before
  AstralProjection adopts it MUST be identified as such in its pull request.

### V. Thin, Portable Runtime

- The runtime dependency set is exactly `pydantic>=2`, pinned by `tests/test_ci_workflow.py`.
  Changing it requires the owner's approval because every consumer inherits it.
- `requires-python` is `>=3.9`. CI MUST test the declared floor and the newest supported
  Python (currently 3.9, 3.11, and 3.14).
- Development and CI tooling live in locked dependency groups in `uv.lock`; any such tooling
  MAY be added when declared there.
- The build backend is pinned exactly and built with hash-required build constraints
  (`tooling/python-ci/build-requirements.lock.txt`).

### VI. Self-Documenting Source

The code documents itself: names, types, and structure carry the meaning.

- Every source and test file MUST begin with a header of at most three sentences stating what
  it does and how it connects to other files; Python uses a module docstring.
- No other comments or docstrings are permitted, except a single-line comment where one is
  absolutely necessary to explain a non-obvious *why*: an ordering constraint, a security
  reason, an external quirk, an invariant enforced elsewhere, a surprising constant, or an
  intentionally empty block.
- Function and class docstrings, narrating comments, section banners, commented-out code,
  TODO/FIXME notes, spec, task, and requirement IDs, feature numbers, and change history MUST
  NOT appear in source or tests. They belong in pull requests, `README.md`, or issues.
- Tool directives (`# noqa`, `# type: ignore`, `# pragma: no cover`, shebangs, encoding
  lines) are not comments and MUST be preserved verbatim.
- Text that the runtime or schema tooling reads MUST be an explicit value (for example
  `Field(description=...)`), never a docstring.
- Tests MUST verify behavior and MUST NOT assert on comments or docstrings.
- Files generated and managed by Spec Kit (`.specify/`, `.agents/`, `.claude/`) are upstream
  tooling, exempt from this principle, and change only through Spec Kit.

### VII. Test and Coverage Discipline

- New or changed primitives MUST ship with tests for default construction and validation,
  serialization shape, `from_dict` round-trip, and adapter validation, covering golden paths,
  edge cases, and rejected input.
- CI MUST keep at least 90% total branch coverage (`pytest --cov-branch --cov-fail-under=90`)
  and at least 90% coverage of changed lines (`diff-cover --fail-under=90`).
- A change with no measurable executable lines makes changed-line coverage not applicable,
  and that outcome MUST be recorded explicitly rather than passing vacuously.
- The built distribution MUST pass the clean-install smoke: manifest version, `__version__`,
  `py.typed`, and the exact serialization of a sample primitive.
- Shipped code MUST NOT contain work-in-progress, stubbed, mocked, hard-coded, or debug-only
  paths.

### VIII. Locked, Bounded, Deterministic CI

- `.github/workflows/ci.yml` MUST run on every pull request and every push to `main`: lock
  verification, locked install, ruff, tests with coverage, changed-line coverage, the Python
  compatibility matrix, the distribution build, `twine check`, the clean-install smoke, and an
  aggregate `gates` job that fails unless every job succeeds.
- Every job MUST finish within 30 minutes and declare `timeout-minutes` of at most 30. A suite
  over budget gets cheaper fixtures or loses its slowest tests; the limit is never raised.
- Required gates MUST NOT depend on live third-party network services, exact clock-derived
  values, or wall-clock performance bounds. Soak tests are prohibited; per-test retries are
  permitted and whole-suite reruns are not.
- A gate MUST fail only for a defect the change introduced or can fix.
- Workflows MUST use approved actions pinned to full commit SHAs, least-privilege
  permissions (`contents: read` for qualification), and no `continue-on-error`.
  `tests/test_ci_workflow.py` pins these properties and MUST stay green.

### IX. Trusted, Gated Publication

- Publication to PyPI MUST run only from `.github/workflows/python-publish.yml` on a push to
  `main`, only when the `pyproject.toml` version is absent from PyPI, and only after its
  unprivileged job repeats the locked lint, tests, build, and `twine check`. A failed PyPI
  lookup MUST fail the job.
- Only the publisher job, in the protected `pypi` environment, holds `id-token: write`; it
  uploads exactly the verified artifacts through OIDC trusted publishing. No stored PyPI
  token may exist.
- Publication does not replace pull-request qualification: a version bump MUST land through
  a pull request whose `ci.yml` run passed, and an owner-authorized direct push MUST NOT change
  the version.
- After a repository rename or transfer, the PyPI trusted-publisher binding MUST be
  re-verified before the next release.

## Consumers and Cross-Repository Changes

- AstralDeep pins this repository at `components/AstralPrimitives` and verifies the package
  version, `__version__`, and a digest of the `src/astralprims/*.py` sources in its
  composition manifest. AstralProjection depends on a pinned `astralprims` release and owns
  `contracts/ui_protocol.json`; the Apple clients mirror the vocabulary in Swift.
- This repository never edits its consumers. A change reaches them only when they adopt a
  new version or revision under their own constitutions, and a source change without a
  version bump obliges consumers that digest the sources to re-digest when they next pin.
- A wire-contract change lands here first (definition, README, tests, and version), then in
  AstralProjection, then in AstralDeep.

## Development Workflow

- Changes land through pull requests qualified by `ci.yml` unless the owner explicitly
  authorizes a direct push; a directly pushed change runs the same gates on `main`.
- Reviewers MUST verify constitution compliance: file headers and no extra comments
  (Principle VI), README entries (Principle IV), serialization tests (Principles II and VII),
  and the version rules (Principle III).
- Spec, task, and feature IDs belong in pull request descriptions, never in source or tests.
- A pull request that adds a dependency SHOULD name it and its purpose.

## Governance

- This constitution is the highest-authority engineering policy for AstralPrimitives and
  supersedes `AGENTS.md`, `README.md`, and other guidance where they conflict. It replaces the
  AstralDeep constitution as this repository's governing document; AstralDeep's constitution
  governs only how AstralDeep consumes this package.
- Amendments land by pull request unless the owner explicitly authorizes a direct push. Each
  amendment is approved by the owner or a lead developer and records its rationale, version
  change, and Sync Impact Report in the pull request or commit message.
- Versioning follows semantic versioning: MAJOR for principle removals or redefinitions,
  MINOR for new principles or materially expanded guidance, and PATCH for clarifications.
- Every pull request and review MUST verify compliance. Violations are resolved before merge,
  and known shortfalls are tracked as follow-up work until closed.
- References to numbered constitution principles in records written before 2026-09-28 refer
  to the AstralDeep constitution v5.0.0.

**Version**: 1.0.0 | **Ratified**: 2026-09-28 | **Last Amended**: 2026-09-28
