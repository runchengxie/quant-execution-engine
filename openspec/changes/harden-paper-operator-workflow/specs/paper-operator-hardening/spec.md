## ADDED Requirements

### Requirement: LongPort paper operator workflow SHALL preserve failure boundaries
The `longport-paper` smoke/operator workflow SHALL stop at the first mutating step that fails and SHALL preserve structured evidence for all completed steps plus the failed step.

#### Scenario: Rebalance step fails before tracked-order inspection
- **WHEN** the paper smoke workflow fails during `rebalance`
- **THEN** the run SHALL be marked unsuccessful in structured evidence
- **AND** the evidence SHALL record `rebalance` as the failed step
- **AND** later steps such as `orders`, `order`, `reconcile`, `exceptions`, and `cancel-all` SHALL NOT run

#### Scenario: Downstream operator step fails after an order is tracked
- **WHEN** the paper smoke workflow fails during a later operator step such as `orders`, `order`, `reconcile`, `exceptions`, or `cancel-all`
- **THEN** the run SHALL be marked unsuccessful in structured evidence
- **AND** the evidence SHALL preserve all completed prior steps plus the failed step payload
- **AND** the workflow SHALL stop before any later step executes

### Requirement: LongPort paper operator workflow SHALL handle missing tracked orders conservatively
The paper smoke workflow SHALL continue with safe read-only follow-up steps when no tracked order reference is available after `rebalance`.

#### Scenario: No tracked order exists after rebalance
- **WHEN** `rebalance` completes but the local tracked state does not contain a broker order reference for the requested symbol
- **THEN** the workflow SHALL skip the `order` step
- **AND** the workflow SHALL continue with `reconcile` and `exceptions`
- **AND** the evidence SHALL record that no tracked order reference was available

### Requirement: Execution lifecycle SHALL preserve existing partial-recovery behavior
The execution lifecycle SHALL keep explicit operator behavior for partially filled, pending-cancel, and late-fill recovery paths instead of silently collapsing them into generic success or failure states.

#### Scenario: Partially filled order requires explicit operator action
- **WHEN** a tracked order has a positive filled quantity and a positive remaining quantity
- **THEN** retry-style actions that only support zero-fill retries SHALL reject that order
- **AND** `cancel-rest`, `resume-remaining`, or `accept-partial` SHALL remain the supported operator actions

#### Scenario: Reconcile discovers a late fill for a tracked closed order
- **WHEN** reconcile loads a tracked order that is no longer open and the broker returns new fill data
- **THEN** the local execution state SHALL append the missing fill event
- **AND** the parent order SHALL be updated to reflect the recovered fill quantity and resulting status

#### Scenario: Reconcile cannot refresh a tracked order or fill query
- **WHEN** reconcile fails to load a tracked order detail or its fill list from the broker
- **THEN** reconcile SHALL preserve the local state instead of deleting the tracked order
- **AND** the reconcile result SHALL include a warning describing the broker query failure
