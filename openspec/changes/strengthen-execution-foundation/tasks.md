## 1. Broker Adapter Foundation

- [x] 1.1 Add broker lifecycle interfaces, capability matrix models, and broker selection plumbing in the core execution package
- [x] 1.2 Refactor the LongPort integration behind the new adapter contract with explicit support or explicit unsupported errors for submit, query, cancel, list, and reconcile operations
- [x] 1.3 Make `--account` resolve through broker account/profile configuration and fail fast when the selected adapter cannot satisfy the request

## 2. Order Lifecycle And State

- [x] 2.1 Introduce execution state models for order intents, broker orders, fill events, parent orders, and child orders
- [x] 2.2 Add a file-backed execution state store with atomic writes for active orders, remaining quantity, last reconcile time, and known fill progress
- [x] 2.3 Implement an idempotent submission coordinator that restores persisted state, checks broker open orders, and prevents duplicate submits after retries or restarts

## 3. Rebalance Execution Integration

- [x] 3.1 Refactor `RebalanceService` to emit order intents and call an order lifecycle service instead of invoking broker-specific submit logic directly
- [x] 3.2 Replace simulated live `order_id` behavior with real adapter-driven submit results and explicit failure paths when a broker cannot execute live orders
- [x] 3.3 Expand audit output to include intent ids, parent/child ids, broker order ids, fill summaries, reconcile outcomes, and account/profile metadata while preserving existing JSONL compatibility

## 4. Risk Gates And Safety Controls

- [x] 4.1 Implement a configurable `RiskGate` chain for max quantity or notional, spread, participation ratio, and market impact checks
- [x] 4.2 Add manual kill switch support and automatic stop conditions triggered by repeated submit, cancel, or reconcile failures
- [x] 4.3 Surface structured risk decisions and blocked-order reasons through CLI output and audit logs

## 5. Alpaca Paper And Smoke Harnesses

- [x] 5.1 Add an Alpaca paper adapter that implements the broker lifecycle contract and capability matrix
- [x] 5.2 Create a minimal signal-driven smoke harness outside the core package to exercise market-order execution paths against paper backends
- [x] 5.3 Create a target-driven smoke harness outside the core package to exercise rebalance, slicing scaffolding, and restart recovery scenarios

## 6. Verification And Documentation

- [x] 6.1 Add unit tests for broker capability validation, risk-gate decisions, state persistence, and idempotent submission behavior
- [x] 6.2 Add integration or e2e scenarios for submit, query, cancel, reconcile, restart recovery, and kill-switch behavior on supported broker backends
- [x] 6.3 Update README and docs to describe broker backend selection, account semantics, paper harness usage, audit outputs, and execution-only non-goals
