## ADDED Requirements

### Requirement: Risk bypass decisions are summarized separately
The system SHALL summarize `BYPASS` risk decisions separately from `PASS` and `BLOCK` decisions in preflight and rebalance operator outputs.

#### Scenario: Market data is missing for configured risk gates
- **WHEN** spread, participation, or market impact gates are configured but missing market data causes `BYPASS`
- **THEN** the operator summary SHALL list each bypassed gate with its reason and SHALL not present those gates as passed checks

#### Scenario: Risk gate is disabled by configuration
- **WHEN** a risk gate returns `BYPASS` because the configured threshold is disabled
- **THEN** the operator summary SHALL identify the gate as disabled rather than market-data-degraded

### Requirement: Structured outputs include bypass metadata
The system SHALL include risk bypass metadata in structured JSON or payload outputs wherever risk decisions are already emitted.

#### Scenario: Audit log records risk decisions
- **WHEN** a rebalance audit log includes order risk decisions
- **THEN** the audit payload SHALL include enough detail to count bypassed gates and inspect each bypass reason

#### Scenario: Preflight returns warning readiness
- **WHEN** preflight detects market-data degradation that would cause configured gates to bypass
- **THEN** the preflight structured result SHALL expose that degradation as a warning with affected symbols and gates

### Requirement: Bypass visibility does not change submit semantics
The system MUST keep existing `BLOCK` behavior as the only automatic risk blocker introduced by risk gates in this change.

#### Scenario: Only bypass decisions are present
- **WHEN** an execution has bypassed risk gates but no blocking gate and no other failure condition
- **THEN** the system SHALL continue to follow existing submit behavior while clearly reporting the bypassed controls to the operator
