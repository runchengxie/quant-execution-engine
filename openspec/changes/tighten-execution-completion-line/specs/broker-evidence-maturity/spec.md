## ADDED Requirements

### Requirement: Broker maturity separates code path and evidence path
The system SHALL represent broker/backend maturity as separate code-path and evidence-path states for LongPort real, `longport-paper`, Alpaca paper, and `ibkr-paper`.

#### Scenario: Backend has code path but incomplete evidence
- **WHEN** a backend supports submit/query/cancel/reconcile in code but lacks a complete smoke artifact for broker orders
- **THEN** the maturity output SHALL mark the code path as present and the evidence path as incomplete with the missing evidence named explicitly

#### Scenario: Backend has supervised real-only evidence
- **WHEN** a backend depends on operator-supervised live validation
- **THEN** the maturity output SHALL identify the latest supervised evidence path and SHALL not describe the backend as fully automated

### Requirement: Evidence gaps include recommended next smoke action
The system SHALL attach a recommended next smoke action to every incomplete broker/backend evidence state.

#### Scenario: LongPort real lacks minimal submit evidence
- **WHEN** LongPort real has only read-only evidence
- **THEN** the maturity output SHALL recommend a supervised minimal `rebalance --execute` smoke with audit log and operator note

#### Scenario: IBKR paper lacks broker order evidence
- **WHEN** `ibkr-paper` has Gateway/account/reconcile evidence but no effective-market-data broker order evidence
- **THEN** the maturity output SHALL recommend a paper smoke run that captures submit/query/cancel or fill evidence under valid market data

### Requirement: Evidence maturity remains execution-only
The system MUST NOT require broker-wide order books, event streams, strategy research outputs, or backtest artifacts to mark execution evidence maturity.

#### Scenario: Evidence report is generated
- **WHEN** broker evidence maturity is rendered
- **THEN** the report SHALL only reference execution inputs, audit logs, local execution state, smoke evidence, operator notes, and broker execution actions already in scope
