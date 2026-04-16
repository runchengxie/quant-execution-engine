## ADDED Requirements

### Requirement: Evidence bundle collects existing run artifacts
The system SHALL provide an evidence bundle workflow that collects existing artifacts for a single execution run without querying broker-wide state or mutating broker state.

#### Scenario: Bundle created for a known run id
- **WHEN** the operator requests an evidence bundle for a run id with a matching audit log
- **THEN** the system SHALL create a reviewable bundle containing the matching audit log, target input path when available, relevant local state snapshot, smoke evidence JSON when available, and operator notes when provided

#### Scenario: Bundle requested without matching audit log
- **WHEN** the operator requests an evidence bundle for a run id that cannot be found in local audit logs
- **THEN** the system SHALL fail without creating a partial bundle and SHALL list the searched locations or candidate run ids

### Requirement: Evidence bundle manifest is deterministic
Every evidence bundle SHALL include a machine-readable manifest describing the bundle inputs, source paths, copy status, run id, broker, account label, dry-run/live mode, and creation timestamp.

#### Scenario: Artifact is optional but absent
- **WHEN** an optional artifact such as smoke evidence JSON is not present for the run
- **THEN** the manifest SHALL record the artifact as missing rather than fabricating content or failing the whole bundle

#### Scenario: Bundle includes private live context
- **WHEN** the bundle references a real broker execution
- **THEN** the manifest SHALL include broker/account/run metadata but MUST NOT copy credential files, environment files, or secret values

### Requirement: Bundle output is operator-reviewable
The bundle workflow SHALL produce output that can be inspected locally by an operator and attached to a manual verification record.

#### Scenario: Bundle completes successfully
- **WHEN** a bundle is created
- **THEN** the CLI or tool output SHALL print the bundle path, manifest path, included artifact count, missing artifact count, and recommended review steps
