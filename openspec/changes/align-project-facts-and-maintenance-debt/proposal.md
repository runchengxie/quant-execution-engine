## Why

The execution engine has accumulated accurate broker-backed execution paths, recovery commands, smoke evidence, and safety guards, but the documentation and compatibility naming no longer present one clean current fact model. The codebase is not a rewrite candidate; it needs focused fact alignment, legacy boundary decisions, and maintainability cleanup before further broker/runtime expansion makes drift harder to control.

## What Changes

- Add a single current-capabilities/support-matrix document that is the source of truth for supported brokers, maturity, account semantics, state semantics, credential sources, and evidence gaps.
- Align `README.md`, `AGENTS.md`, and `docs/*.md` to reference that source instead of repeating divergent caveats across multiple files.
- Rewrite `.env.example` as a paper-safe local example and move LongPort live credential guidance to a repo-external user-private example path or dedicated live credential document.
- Bring `.envrc` and `.envrc.example` back under one documented model, including optional extras for Alpaca, LongPort, and IBKR.
- Document every `state-repair` option exposed by the CLI, including `--drop-orphan-terminal-broker-orders`.
- Decide and implement the canonical-target boundary: either remove legacy ticker-list/weights parsing from runtime code or explicitly scope it to internal migration helpers outside the rebalance path.
- Normalize external-facing LongPort naming and document any remaining `longbridge` / `LONGBRIDGE_*` compatibility as deprecated.
- Classify `project_tools` scripts as product smoke harnesses versus maintainer-only utilities, then relocate or document maintainer-only scripts.
- Refactor the highest-risk long functions/classes without changing broker behavior, prioritizing CLI parser construction, operator smoke workflow orchestration, LongPort snapshot/order helpers, and state maintenance operations.
- Add focused behavior tests for documentation-sensitive contracts and cleanup boundaries where code behavior changes.

## Capabilities

### New Capabilities

- `project-current-facts`: Defines how the repository exposes current supported functionality, maturity, credential safety rules, testing entry points, and operational caveats without divergent duplicate documentation.
- `maintenance-debt-governance`: Defines how obsolete compatibility layers, maintainer-only scripts, naming drift, and large code hotspots are identified, scoped, and safely reduced.

### Modified Capabilities

- None.

## Impact

- Documentation: `README.md`, `AGENTS.md`, `docs/configuration.md`, `docs/testing.md`, `docs/cli.md`, `docs/targets.md`, `docs/architecture.md`, and smoke runbooks.
- Configuration examples: `.env.example`, `.envrc`, `.envrc.example`, and any new live credential example/document.
- Runtime code: `src/quant_execution_engine/targets.py`, LongPort compatibility naming/imports, CLI parser construction, state maintenance, and smoke harness orchestration.
- Tests: default unit tests should remain fast; any new tests should be behavior-oriented and avoid brittle source-text assertions.
- No broker API contract or default test selection should change unless explicitly called out in tasks.
