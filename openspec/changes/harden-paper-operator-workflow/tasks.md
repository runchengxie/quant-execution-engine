## 1. LongPort Paper Failure-Mode Coverage

- [x] 1.1 Add `longport-paper` smoke harness tests for rebalance-step failure and verify later steps do not execute.
- [x] 1.2 Add `longport-paper` smoke harness tests for downstream operator-step failures (`orders`, `order`, `reconcile`, `exceptions`, `cancel-all`) and verify partial evidence is preserved.
- [x] 1.3 Add workflow coverage for the case where no tracked order reference exists after rebalance and verify `order` is skipped while safe follow-up steps continue.
- [x] 1.4 Extend execution lifecycle tests for reconcile query failures (`get_order`, `list_fills`) so warnings are preserved without deleting local tracked state.
- [x] 1.5 Extend execution lifecycle tests for partial-fill, pending-cancel, and late-fill recovery paths to lock in current operator behavior.

## 2. Operator Evidence And Diagnostics

- [x] 2.1 Extend smoke evidence payloads with stable run-outcome fields such as `success`, `failed_step`, failure category, skipped-step context, state path, and latest tracked order reference.
- [x] 2.2 Add conservative next-step hints for evidence/diagnostic output when failure class can be inferred without guessing broker intent.
- [x] 2.3 Update smoke harness unit tests to assert structured evidence fields instead of relying only on raw transcript output.
- [x] 2.4 Update operator/testing documentation so the paper smoke workflow explains how to interpret successful runs, failed runs, and partial evidence records.

## 3. Low-Risk Execution Helper Extraction And Verification

- [x] 3.1 Extract repeated account/state/tracked-order resolution logic from `execution.py` into helper functions only where it directly reduces duplication in operator actions.
- [x] 3.2 Extract any additional partial-fill or retry/reprice helper logic that becomes obviously repetitive while implementing the failure-mode tests.
- [x] 3.3 Preserve existing public imports and command behavior while refactoring, including renderer and test imports that still expect `execution.py` re-exports.
- [x] 3.4 Run focused unit and e2e regression suites for smoke harnesses, execution lifecycle, CLI routing, and LongPort helper compatibility after each refactor slice.
