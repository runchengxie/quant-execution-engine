## Why

The project is intentionally staying execution-only, but the current LongPort paper/operator path still proves more happy-path behavior than failure behavior. Before adding broader platform features or new brokers, the more valuable work is to harden the existing paper workflow so operator failures, partial recovery paths, and evidence capture are predictable and reviewable.

## What Changes

- Add failure-mode regression coverage for `longport-paper` operator workflows, focusing on realistic failure points in the existing command chain rather than new platform features.
- Strengthen smoke harness evidence so failed runs preserve enough structured context to explain what happened, what was skipped, and what an operator should inspect next.
- Tighten behavior around partial-fill, pending-cancel, late-fill, reconcile, and broker query error handling where the project already claims operator support.
- Keep `execution.py` refactors scoped to low-risk helper extraction that directly supports testability and operator behavior hardening; no platform-style rearchitecture is in scope.

## Capabilities

### New Capabilities
- `paper-operator-hardening`: Defines the expected failure-mode and recovery behavior for the existing `longport-paper` config/account/quote/rebalance/orders/order/reconcile/exceptions/cancel-all workflow.
- `operator-evidence-diagnostics`: Defines the structured evidence and diagnostic fields that must be preserved for both successful and failed operator smoke runs.

### Modified Capabilities

## Impact

- Affected code:
  `project_tools/smoke_operator_harness.py`,
  `src/quant_execution_engine/execution.py`,
  `src/quant_execution_engine/renderers/*`,
  `tests/unit/test_smoke_operator_harness.py`,
  `tests/unit/test_execution_foundation.py`,
  `tests/e2e/test_smoke_harnesses.py`
- Affected operator flows:
  `longport-paper` smoke/evidence runs, tracked-order recovery, partial-fill handling, and reconcile-driven diagnostics.
- No new broker platform, dashboard, multi-account router, or research/backtest scope is introduced.
