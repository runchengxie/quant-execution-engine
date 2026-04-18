## ADDED Requirements

### Requirement: Legacy compatibility is explicit
The codebase SHALL make remaining historical compatibility layers explicit, documented, and bounded by migration intent.

#### Scenario: LongBridge env fallback remains
- **WHEN** `LONGBRIDGE_*` environment variables are still accepted as fallback inputs
- **THEN** documentation and code comments identify them as deprecated compatibility and prefer `LONGPORT_*` names in examples and tests

#### Scenario: Current LongPort names are available
- **WHEN** both current `LONGPORT_*` and legacy `LONGBRIDGE_*` names are present
- **THEN** the current `LONGPORT_*` value wins and tests cover that precedence

### Requirement: Maintainer-only scripts are distinguished from product workflows
The repository SHALL distinguish operator-facing smoke harnesses from maintainer-only utility scripts under `project_tools`.

#### Scenario: User reviews project tools
- **WHEN** a user inspects `project_tools`
- **THEN** each script is documented or located so its role is clear as either an operator smoke harness, target/signal generator, source export helper, or packaging helper

#### Scenario: Maintainer utility is moved
- **WHEN** a maintainer-only utility changes location
- **THEN** existing users receive either a compatibility wrapper or documented migration path for the new command location

### Requirement: Code hotspot cleanup preserves behavior
The project SHALL refactor high-risk long functions by extracting cohesive helpers while preserving CLI behavior and broker semantics.

#### Scenario: CLI parser is refactored
- **WHEN** `create_parser` is split into helper builders
- **THEN** existing CLI command tests still pass and shared broker/account/order-ref argument behavior remains unchanged

#### Scenario: Operator smoke workflow is refactored
- **WHEN** `run_operator_smoke_workflow` is split into step helpers or a step registry
- **THEN** existing smoke harness tests still pass and evidence output keeps the same structure unless explicitly changed

#### Scenario: LongPort helpers are refactored
- **WHEN** LongPort quote, account snapshot, order mutation, or runtime config code is extracted
- **THEN** adapter and credential tests still pass and public broker capability behavior remains unchanged

#### Scenario: State maintenance is refactored
- **WHEN** state doctor, prune, or repair logic is split into smaller operations
- **THEN** existing state lifecycle tests still pass and repair summaries remain behaviorally equivalent

### Requirement: Cleanup tests are behavior-oriented
Tests added for this maintenance change SHALL validate observable behavior instead of brittle source layout details.

#### Scenario: Testing documentation-sensitive behavior
- **WHEN** tests are added for env safety, target input boundaries, or command options
- **THEN** they assert CLI behavior, parser output, or function results rather than raw source strings or file existence alone

#### Scenario: Refactoring large functions
- **WHEN** implementation extracts helpers from a large module
- **THEN** tests focus on command output, state transitions, evidence JSON, or broker adapter contracts instead of helper names
