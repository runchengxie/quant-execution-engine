## 1. Backend Setup And Registration

- [x] 1.1 Select the initial Python IBKR client dependency and add an `ibkr` optional extra plus `full` extra coverage in `pyproject.toml`.
- [x] 1.2 Register `ibkr-paper` in the broker factory, paper-broker detection, capability lookup, and broker package exports.
- [x] 1.3 Add IBKR paper configuration helpers for host, port, client ID, account identifier, timeout, and install-time/import-time error reporting.

## 2. IBKR Runtime And Adapter

- [x] 2.1 Implement an IBKR runtime/client wrapper for local IB Gateway connectivity, session teardown, contract resolution, and normalized broker error mapping.
- [x] 2.2 Implement `IbkrPaperBrokerAdapter` with single-account validation, explicit initial market-scope validation, and normalized account snapshot and quote retrieval.
- [x] 2.3 Implement broker-backed `submit_order`, `get_order`, `list_open_orders`, `cancel_order`, `list_fills`, `reconcile`, and `close` behavior for `ibkr-paper`.

## 3. CLI And Operator Flows

- [x] 3.1 Extend `qexec config --broker ibkr-paper` to display the effective non-secret IBKR paper runtime configuration and routing assumptions.
- [x] 3.2 Ensure `preflight`, `account`, `quote`, `rebalance --execute`, `orders`, `order`, `exceptions`, `cancel`, and `reconcile` operate correctly with `ibkr-paper`.
- [x] 3.3 Extend `project_tools/smoke_operator_harness.py` and related evidence handling to support `ibkr-paper` in `--preflight-only` and `--execute` modes.

## 4. Tests, Docs, And Evidence

- [x] 4.1 Add unit tests for IBKR backend registration, configuration surfacing, account and market-scope validation, normalization, and broker import/runtime error handling.
- [x] 4.2 Add explicitly selected integration coverage for IBKR paper account, quote, submit, query, cancel, fill, and reconcile behavior against a reachable paper runtime.
- [x] 4.3 Update `README.md`, `docs/configuration.md`, `docs/architecture.md`, `docs/cli.md`, and `docs/testing.md`, and add `docs/ibkr-paper-smoke.md` with IB Gateway over TWS API prerequisites and smoke steps.
- [ ] 4.4 Capture at least one operator-supervised `ibkr-paper` evidence sample and document the resulting maturity caveats using the existing repo evidence style.
