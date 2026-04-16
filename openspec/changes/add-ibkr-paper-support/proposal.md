## Why

The project already treats broker support as a full execution lifecycle concern rather than a thin submit-order integration, but IBKR is not yet part of that supported backend set. Adding a minimal `ibkr-paper` slice now creates a realistic paper-trading path for adapter, preflight, reconcile, and operator recovery work without prematurely committing to IBKR live trading support.

## What Changes

- Add a new `ibkr-paper` broker backend that participates in the existing execution-only lifecycle: config, account, quote, rebalance execution, order query, cancel, fills, and reconcile.
- Introduce IBKR-specific runtime/configuration handling for local IB Gateway connectivity over the TWS API, account resolution, market-data access, and connection teardown.
- Extend broker factory, CLI surfaces, capability reporting, stateful execution paths, and smoke tooling so IBKR is treated as a first-class paper backend.
- Add operator-facing documentation for IBKR setup, runtime assumptions, preflight checks, and paper smoke workflows.
- Defer IBKR live trading, multi-account routing, advanced order types, and non-US market coverage until the paper path is proven.

## Capabilities

### New Capabilities

- `ibkr-paper-backend`: Support IBKR paper trading as a broker-backed execution backend across adapter, factory, CLI, tracked-state, and reconcile flows.
- `ibkr-operator-readiness`: Expose IBKR runtime configuration, readiness checks, and operator smoke procedures so paper execution can be validated and troubleshot consistently.

### Modified Capabilities

None.

## Impact

- Affected code: `src/quant_execution_engine/broker/*`, `src/quant_execution_engine/preflight.py`, `src/quant_execution_engine/cli.py`, `project_tools/smoke_operator_harness.py`, selected unit/integration/e2e tests, and IBKR-specific docs.
- Dependencies: add an optional IBKR client dependency and include it in the `full` extra.
- Systems: a local IB Gateway runtime becomes an explicit execution prerequisite for the new backend.
