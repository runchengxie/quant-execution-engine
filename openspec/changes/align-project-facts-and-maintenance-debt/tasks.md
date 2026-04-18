## 1. Current Facts and Documentation Alignment

- [x] 1.1 Create `docs/current-capabilities.md` covering repo scope, supported brokers, maturity, account semantics, tracked-state semantics, credential source rules, output locations, and known evidence gaps.
- [x] 1.2 Update `README.md` to summarize current capabilities and link to `docs/current-capabilities.md` instead of repeating the full caveat matrix.
- [x] 1.3 Update `AGENTS.md` to keep only high-signal operational caveats and link to the current-facts source for expanded detail.
- [x] 1.4 Update `docs/testing.md` so default, e2e, integration, and broker smoke evidence commands match the current pytest config and broker maturity matrix.
- [x] 1.5 Update `docs/architecture.md`, `docs/execution-foundation.md`, and smoke runbooks so they reference the current-facts document for shared caveats.

## 2. Credential and Environment Examples

- [x] 2.1 Rewrite `.env.example` as a paper-safe local example and remove the repo-local LongPort real token placeholder.
- [x] 2.2 Add or update live credential documentation showing current-shell export and repo-external `~/.config/qexec/longport-live.env` usage.
- [x] 2.3 Align `.envrc` and `.envrc.example` so they share the same optional-extra detection model for Alpaca, LongPort, and IBKR.
- [x] 2.4 Update `docs/configuration.md` to describe the `.env.example`, `.envrc`, and live credential boundaries without conflicting guidance.

## 3. CLI and Target Contract Cleanup

- [x] 3.1 Update `docs/cli.md` to document every `state-repair` option, including `--drop-orphan-terminal-broker-orders`.
- [x] 3.2 Update README command examples to include the complete current recovery chain: `cancel-all`, `retry-stale`, `cancel-rest`, `resume-remaining`, and `accept-partial`.
- [x] 3.3 Search all runtime and tool call sites for legacy ticker-list/weights target parsing.
- [x] 3.4 Remove legacy target parsing from public rebalance runtime, or move any required conversion into explicitly named internal helper/tool code.
- [x] 3.5 Keep or add behavior tests proving `qexec rebalance` rejects non-canonical target inputs and helpers generate canonical `targets.json`.

## 4. LongPort Naming and Compatibility Boundary

- [x] 4.1 Rename externally visible test/docs filenames or headings that still present LongBridge as the current backend where practical.
- [x] 4.2 Document `LONGBRIDGE_*` env names as deprecated compatibility and prefer `LONGPORT_*` in all examples.
- [x] 4.3 Keep tests proving `LONGPORT_*` values take precedence over `LONGBRIDGE_*` compatibility values.
- [x] 4.4 Add brief code comments only where compatibility fallbacks remain and their removal path would otherwise be unclear.

## 5. Maintainer Tool Classification

- [x] 5.1 Classify `project_tools/smoke_signal_harness.py`, `project_tools/smoke_target_harness.py`, and `project_tools/smoke_operator_harness.py` as operator-facing smoke tools in docs.
- [x] 5.2 Classify `project_tools/export_repo_source.py` and `project_tools/package.sh` as maintainer-only utilities.
- [x] 5.3 Either document maintainer-only utilities in a dedicated section or move them under a maintainer/internal path with a compatibility wrapper.
- [x] 5.4 Ensure evidence bundle logic still excludes env/secrets files after any maintainer tool relocation.

## 6. Focused Refactoring

- [x] 6.1 Refactor `src/quant_execution_engine/cli_parser.py::create_parser` into smaller command/argument builder helpers without changing parser behavior.
- [x] 6.2 Refactor `project_tools/smoke_operator_harness.py::run_operator_smoke_workflow` into cohesive workflow step helpers or a step registry.
- [x] 6.3 Refactor LongPort client code by extracting account snapshot, quote, order mutation, and runtime config helper boundaries from `broker/longport.py`.
- [x] 6.4 Refactor `state_tools.py` so doctor, prune, and repair operations have smaller cohesive helper functions.
- [x] 6.5 Review remaining long-line hotspots and clean only touched files or high-readability offenders.

## 7. Verification

- [x] 7.1 Run `uv run pytest` and record the result.
- [x] 7.2 Run targeted e2e tests if CLI parser or smoke harness behavior changes.
- [x] 7.3 Run targeted integration tests only if broker/runtime behavior changes or affected env-gated paths need confirmation.
- [x] 7.4 Run `openspec status --change align-project-facts-and-maintenance-debt` and confirm the change is apply-ready.
