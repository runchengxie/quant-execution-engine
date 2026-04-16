## ADDED Requirements

### Requirement: Tracked order views include actionable next-step guidance
The system SHALL provide consistent operator-facing next-step guidance for tracked order states that require manual recovery.

#### Scenario: Order is pending cancel
- **WHEN** a tracked order is in `PENDING_CANCEL` or equivalent broker pending-cancel status
- **THEN** the order detail and summary outputs SHALL recommend waiting for broker acknowledgement or running reconcile before retrying or repricing

#### Scenario: Order is partially filled
- **WHEN** a tracked order is partially filled or has canceled remaining quantity after a partial fill
- **THEN** the order detail and summary outputs SHALL recommend choosing among `cancel-rest`, `resume-remaining`, and `accept-partial` based on remaining intent

#### Scenario: Broker rejection has a known category
- **WHEN** a broker rejection matches a known diagnostic category such as funds, session, symbol, size/price, permission, or short locate
- **THEN** the output SHALL include the normalized diagnostic code, human-readable summary, and next-step hint

### Requirement: Smoke workflow failures preserve next-step evidence
The smoke operator harness SHALL preserve failure category and next-step guidance in evidence output when a fixed smoke workflow fails after starting.

#### Scenario: Rebalance step fails
- **WHEN** a smoke workflow fails during `rebalance`
- **THEN** the evidence JSON SHALL include the failed step, failure category, failure message, skipped later steps, and a next-step hint for operator follow-up

#### Scenario: Reconcile step fails after an order reference exists
- **WHEN** a smoke workflow fails during `reconcile` after a tracked order reference was observed
- **THEN** the evidence JSON SHALL include the latest tracked order reference and a next-step hint to rerun reconcile or inspect broker state before further mutation

### Requirement: Guidance remains advisory
Operator recovery guidance MUST NOT automatically perform broker mutations beyond the explicit command the operator invoked.

#### Scenario: Next-step guidance is rendered
- **WHEN** the system prints or records a recommended next step
- **THEN** the system SHALL leave any cancel, retry, reprice, resume, or accept-partial action behind a separate explicit operator command
