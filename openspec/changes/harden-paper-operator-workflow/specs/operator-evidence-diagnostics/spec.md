## ADDED Requirements

### Requirement: Operator smoke evidence SHALL classify run outcome
Structured operator smoke evidence SHALL expose stable run-outcome fields that allow a failed or successful run to be interpreted without replaying terminal output.

#### Scenario: Successful paper smoke run
- **WHEN** the smoke workflow completes all intended steps without error
- **THEN** the evidence SHALL record the run as successful
- **AND** the evidence SHALL leave `failed_step` empty
- **AND** the evidence SHALL preserve the latest tracked order reference when one exists

#### Scenario: Failed paper smoke run
- **WHEN** the smoke workflow stops because a step returns a non-zero exit code
- **THEN** the evidence SHALL record the run as unsuccessful
- **AND** the evidence SHALL record the failed step name
- **AND** the evidence SHALL preserve the failed step payload including exit code and stderr

### Requirement: Operator smoke evidence SHALL preserve operator-facing context
Structured operator smoke evidence SHALL preserve the minimum context required to support post-run diagnosis of a paper workflow.

#### Scenario: Evidence captures run context
- **WHEN** a smoke run writes evidence
- **THEN** the evidence SHALL include the broker, account label, symbol, targets output path, and state path
- **AND** the evidence SHALL include whether the run was execute mode, preflight-only mode, or cleanup mode
- **AND** the evidence SHALL include the latest tracked order reference when one is available

#### Scenario: Evidence records skipped order inspection
- **WHEN** a run cannot inspect a single tracked order because no tracked order reference exists
- **THEN** the evidence SHALL preserve a null or empty tracked order reference
- **AND** the step list SHALL omit the `order` step instead of fabricating a placeholder success

### Requirement: Operator diagnostics SHALL include actionable failure interpretation
The operator-facing evidence and diagnostics SHALL preserve failure interpretation fields that can drive conservative next-step guidance.

#### Scenario: Failure is categorized for operator review
- **WHEN** the workflow records a failed step
- **THEN** the diagnostics payload SHALL include a stable failure category for that step
- **AND** the diagnostics payload SHALL allow a next-step hint to be attached when the system can infer a conservative operator action

#### Scenario: Non-failed runs preserve reviewability without failure classification
- **WHEN** the workflow succeeds
- **THEN** the evidence MAY omit failure category and next-step hint
- **AND** it SHALL still preserve the step transcript and run context needed for later review
