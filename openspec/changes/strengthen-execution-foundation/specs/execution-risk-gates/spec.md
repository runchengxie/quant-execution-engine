## ADDED Requirements

### Requirement: Live submission SHALL pass through a risk gate chain
Before any non-dry-run broker order is submitted, the engine SHALL evaluate configured risk gates against the planned order, broker capabilities, current market data, and current account state, and SHALL block submission if any gate rejects the order.

#### Scenario: Spread guard rejection
- **WHEN** an order's observed spread exceeds the configured threshold during execution validation
- **THEN** the engine rejects the order before broker submission and records the rejection as a risk-gate decision

### Requirement: Baseline execution guards SHALL be configurable
The system SHALL support configuration for at least maximum quantity or notional per order, spread guard, participation ratio guard, and market impact threshold, with per-broker or per-market overrides where necessary.

#### Scenario: Different limits by market
- **WHEN** orders for different markets or broker backends are validated
- **THEN** the engine can apply different configured thresholds for each market or broker context

### Requirement: A kill switch SHALL stop new submissions
The system SHALL provide both a manual kill switch and an automatic failure-triggered stop condition that prevent new broker submissions while still allowing query, cancel, and reconcile operations for already active orders.

#### Scenario: Automatic stop after repeated failures
- **WHEN** submit, cancel, or reconcile failures exceed the configured threshold
- **THEN** the engine stops issuing new broker orders and records the stop reason until the stop condition is cleared under configured recovery rules

### Requirement: Risk decisions SHALL be auditable
Every risk-gate pass, rejection, or bypass decision SHALL produce structured audit data that identifies the gate, decision, evaluated metrics, and reason, and links that decision to the relevant intent or parent order.

#### Scenario: Structured audit for rejected order
- **WHEN** a risk gate rejects an order
- **THEN** the audit output includes the gate name, measured values, rejection reason, and the associated execution identifiers
