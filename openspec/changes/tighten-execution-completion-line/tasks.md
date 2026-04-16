## 1. Broker Evidence Maturity

- [x] 1.1 Add a small broker evidence maturity model/helper that records code-path state, latest evidence path, missing evidence, and recommended next smoke action for LongPort real, `longport-paper`, Alpaca paper, and `ibkr-paper`.
- [x] 1.2 Add rendering or CLI access for the maturity report without introducing a database, event stream, or broker-wide order query.
- [x] 1.3 Add behavior tests proving code-path maturity and evidence-path maturity are represented separately for LongPort real and `ibkr-paper`.
- [x] 1.4 Update `docs/execution-checklist.md` and `docs/testing.md` so the completion line distinguishes implemented code paths from broker evidence maturity.

## 2. Evidence Bundle Workflow

- [x] 2.1 Implement an evidence bundle builder that locates a run id in `outputs/orders/*.jsonl` and collects matching audit records plus referenced target input, local state snapshot, smoke evidence JSON when available, and operator notes.
- [x] 2.2 Emit a deterministic manifest with source paths, copied/missing artifact status, run id, broker, account label, dry-run/live mode, and creation timestamp.
- [x] 2.3 Add a thin operator entry point, such as `qexec evidence-pack <run-id>`, that creates a local review directory or archive and prints included/missing artifact counts.
- [x] 2.4 Add unit tests for successful bundle creation, missing run id failure, absent optional artifacts, and exclusion of credential/env files.

## 3. Risk Degradation Summary

- [x] 3.1 Add helper logic that groups risk decisions by `PASS`, `BLOCK`, and `BYPASS`, separating disabled-gate bypasses from market-data-degraded bypasses.
- [x] 3.2 Update preflight output and structured result details to show configured market-data-dependent gates that would bypass because bid/ask or daily volume is unavailable.
- [x] 3.3 Update rebalance operator output and audit payloads to expose bypass counts and reasons without changing existing submit semantics when no `BLOCK` exists.
- [x] 3.4 Add behavior tests for configured-but-missing spread, participation, and market-impact data, including audit JSONL assertions.

## 4. Operator Recovery Guidance

- [x] 4.1 Extend or normalize diagnostics for pending cancel, stale open order, partial fill, partial remainder canceled, and known broker rejection categories.
- [x] 4.2 Ensure `orders`, `exceptions`, `order`, `reconcile`, `retry-stale`, `cancel-rest`, `resume-remaining`, and `accept-partial` summaries render consistent next-step guidance where diagnostics are available.
- [x] 4.3 Keep guidance advisory by verifying no new cancel/retry/reprice/resume/accept mutation is triggered unless the operator invokes that command explicitly.
- [x] 4.4 Add smoke harness evidence tests for failed `rebalance`, failed downstream steps, and reconcile failure after a tracked order ref exists, including `failure_category` and `next_step_hint`.

## 5. Documentation and Validation

- [x] 5.1 Update `docs/longport-real-smoke.md` and `docs/ibkr-paper-smoke.md` with the new evidence bundle and maturity language.
- [x] 5.2 Update CLI documentation for the new evidence bundle entry point and risk bypass summary behavior.
- [x] 5.3 Run `openspec validate tighten-execution-completion-line` and fix any artifact issues.
- [x] 5.4 Run focused unit tests for touched behavior, then run `uv run pytest` before marking implementation complete.
