## ADDED Requirements

### Requirement: Engine SHALL use a broker lifecycle adapter contract
The execution engine SHALL interact with brokers through a lifecycle adapter contract that covers account retrieval, position retrieval, capability declaration, order submission, order lookup, open-order listing, cancellation, and reconcile support.

#### Scenario: Adapter contract drives execution
- **WHEN** `qexec rebalance` or a smoke harness needs broker operations
- **THEN** the engine routes those operations through the configured adapter contract rather than calling broker-specific SDK functions directly from domain services

### Requirement: Broker adapters SHALL expose a machine-readable capability matrix
Each broker adapter SHALL expose a machine-readable capability matrix that includes account/profile selection support, supported order types, supported time-in-force values, fractional trading support, short support, lot size rules, extended-hours support, and any broker-specific validation constraints needed by planning or execution.

#### Scenario: Capability-aware validation
- **WHEN** the engine validates an order before submission
- **THEN** it can inspect the selected adapter's capability matrix and reject unsupported requests before any broker call is made

### Requirement: Unsupported account or order features SHALL fail fast
When a user requests an account label, profile, order type, or execution option that the selected broker adapter cannot satisfy, the engine SHALL return a structured validation error and SHALL NOT silently reduce the request to logging-only behavior.

#### Scenario: Unsupported account selection
- **WHEN** the user passes `--account` for a broker adapter that cannot resolve the requested account or profile
- **THEN** the engine exits with a validation error and records the rejected request in audit output instead of pretending the request succeeded

### Requirement: Alpaca paper SHALL be a first-class adapter implementation
The system SHALL provide an Alpaca paper adapter that implements the same lifecycle adapter contract as production brokers so paper execution can exercise submit, query, cancel, list, and reconcile flows without changing core execution services.

#### Scenario: Paper backend selected
- **WHEN** the configured broker backend is Alpaca paper
- **THEN** rebalance and smoke workflows execute through the Alpaca adapter using the same domain interfaces used by other broker adapters
