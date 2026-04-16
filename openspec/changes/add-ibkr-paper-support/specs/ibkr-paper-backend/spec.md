## ADDED Requirements

### Requirement: IBKR paper backend registration
The system SHALL expose `ibkr-paper` as a supported broker backend with an installable optional dependency so that broker selection, capability inspection, and adapter creation work through the existing factory and CLI entry points.

#### Scenario: Broker backend is selected explicitly
- **WHEN** `broker.backend` or `--broker` is set to `ibkr-paper`
- **THEN** the broker factory SHALL resolve the backend without treating it as an unsupported broker

#### Scenario: IBKR dependency is missing
- **WHEN** an operator invokes an `ibkr-paper` command without the required optional dependency installed
- **THEN** the system SHALL fail with a broker import error that identifies the missing IBKR dependency and the `uv sync --extra ibkr` installation path

### Requirement: IBKR paper scope is validated
The system SHALL constrain the initial `ibkr-paper` backend to the explicitly supported scope and reject unsupported account or symbol scope before mutating broker state.

#### Scenario: Unsupported account label is requested
- **WHEN** an operator invokes `ibkr-paper` with an account label other than `main`
- **THEN** the adapter SHALL fail fast with a validation error that `ibkr-paper` is currently single-account only

#### Scenario: Unsupported market scope is requested
- **WHEN** the execution path receives a target or quote request outside the initial supported IBKR market scope
- **THEN** the backend SHALL reject the request with a validation error that names the unsupported symbol or market and the supported initial scope

### Requirement: IBKR paper account and quote data is normalized
The system SHALL provide IBKR paper account snapshots and quote lookups through the existing broker-neutral models used by `account`, `quote`, and `preflight`.

#### Scenario: Account snapshot is requested
- **WHEN** `qexec account --broker ibkr-paper` resolves a reachable IBKR paper runtime
- **THEN** the backend SHALL return a normalized account snapshot with cash, positions, total portfolio value, and base currency populated through the existing `AccountSnapshot` model

#### Scenario: Quote data is requested
- **WHEN** `qexec quote` or `qexec preflight` requests supported IBKR symbols
- **THEN** the backend SHALL return normalized `Quote` records that preserve the canonical execution symbol and available bid, ask, and timestamp fields

### Requirement: IBKR paper execution lifecycle is broker-backed
The system SHALL implement broker-backed submit, query, open-order listing, cancel, fill lookup, and reconcile behavior for `ibkr-paper` through the existing `BrokerAdapter` lifecycle contract.

#### Scenario: Order submission succeeds
- **WHEN** `qexec rebalance --broker ibkr-paper --execute` submits an order within the supported scope
- **THEN** the adapter SHALL return a normalized `BrokerOrderRecord` with broker order ID, status, quantity, side, broker name, and account label for tracked-state persistence

#### Scenario: Reconcile refreshes tracked IBKR state
- **WHEN** `qexec reconcile --broker ibkr-paper` runs after one or more tracked IBKR orders exist
- **THEN** the adapter SHALL return open orders and fills in normalized broker-neutral records so the local execution state can refresh tracked order status and fill history

#### Scenario: Cancel queries refreshed order state
- **WHEN** an operator runs `qexec cancel --broker ibkr-paper` for a tracked open order
- **THEN** the lifecycle path SHALL issue broker cancel, refresh the broker order state, and persist the post-cancel status through the existing tracked-state flow
