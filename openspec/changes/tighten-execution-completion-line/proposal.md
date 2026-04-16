## Why

The repository already has the core execution-only paths in code, but the remaining gap is that key broker paths and dirty operator scenarios are not yet equally defensible as evidence. This change tightens the project completion line around proof, degraded-risk visibility, and operator recovery without expanding the repository into a general execution platform.

## What Changes

- Add a broker evidence maturity capability that records which broker/backend flows have code coverage, paper or live smoke evidence, and remaining supervised gaps.
- Add a thin evidence bundle command or tool path that packages the existing target input, audit log, local state snapshot, smoke evidence JSON, and operator notes for a specific execution run.
- Make risk `BYPASS` decisions explicit in preflight and rebalance operator summaries so the operator can see which market-data-dependent controls were not actually evaluated.
- Strengthen operator next-step guidance for stale open orders, pending cancel states, partial fills, broker rejection classes, and smoke workflow failures.
- Keep fractional `resume-remaining`, multi-account routing, broker-wide order books, event streams, dashboards, and TWAP/POV out of this change unless a later change proves they are necessary for the basic execution loop.

## Capabilities

### New Capabilities
- `broker-evidence-maturity`: Tracks broker/backend execution maturity and required evidence for LongPort real, `longport-paper`, Alpaca paper, and `ibkr-paper`.
- `evidence-bundle`: Packages existing run artifacts into a reviewable evidence bundle without creating a new persistence layer.
- `risk-degradation-summary`: Exposes risk gate `BYPASS` decisions clearly in preflight/rebalance outputs and structured results.
- `operator-recovery-guidance`: Provides consistent operator-facing next-step guidance for tracked order recovery and smoke workflow failures.

### Modified Capabilities

None.

## Impact

- Affected CLI surfaces may include `qexec preflight`, `qexec rebalance`, a new evidence packing command, and existing operator commands such as `orders`, `exceptions`, `order`, `reconcile`, `cancel-rest`, `resume-remaining`, and `accept-partial`.
- Affected implementation areas are expected around `cli.py`, `preflight.py`, `rebalance.py`, `risk.py`, `execution.py`, `diagnostics.py`, `state_tools.py`, `renderers/`, and `project_tools/smoke_operator_harness.py`.
- Documentation updates should revise `docs/execution-checklist.md`, `docs/testing.md`, `docs/longport-real-smoke.md`, and `docs/ibkr-paper-smoke.md` so code-path maturity and evidence maturity remain separate.
- No new broker dependency, database, event bus, strategy layer, or platform-style scheduler should be introduced by this change.
