## ADDED Requirements

### Requirement: Smoke harness utilities SHALL remain outside the core engine package
The project SHALL provide smoke harness utilities outside the core execution package so they can generate test inputs and drive execution without turning the engine into a strategy framework or pulling research infrastructure into the core domain.

#### Scenario: External harness generates engine input
- **WHEN** a smoke utility generates targets or signal-driven orders
- **THEN** it writes canonical engine inputs or calls public execution interfaces without adding research or backtest modules to the core package

### Requirement: The project SHALL provide both signal-driven and target-driven smoke drivers
The project SHALL include at least one simple signal-driven harness and one direct target-generator harness suitable for paper testing of market and limit order flows.

#### Scenario: Signal-driven harness exercises market path
- **WHEN** the user runs the minimal signal-driven harness against a paper broker
- **THEN** the harness emits a deterministic small set of orders that exercises the engine end-to-end through the market-order path

#### Scenario: Target-driven harness exercises rebalance path
- **WHEN** the user runs the target-generator harness
- **THEN** the harness emits canonical targets or parent-order intents that can drive rebalance and slicing workflows without relying on an alpha research stack

### Requirement: Paper scenarios SHALL validate execution behavior rather than performance
Smoke scenarios SHALL validate submit, query, cancel, reconcile, restart recovery, and risk-gate interaction behavior, and SHALL NOT use P&L, backtest metrics, or paper profitability as the primary pass criteria.

#### Scenario: Restart recovery determines pass or fail
- **WHEN** a paper scenario restarts after an active order has been created
- **THEN** the scenario passes only if the engine restores state and reconciles correctly, regardless of the strategy's paper return

### Requirement: Alpaca paper SHALL be the initial default paper backend
The initial smoke harness SHALL target the Alpaca paper adapter and SHALL allow broker backend selection so the same scenarios can later run against other supported paper or dry-run adapters.

#### Scenario: Backend selection stays adapter-driven
- **WHEN** the user selects Alpaca paper for a smoke scenario
- **THEN** the scenario uses the broker adapter interface and records backend-specific audit details without changing the scenario logic itself
