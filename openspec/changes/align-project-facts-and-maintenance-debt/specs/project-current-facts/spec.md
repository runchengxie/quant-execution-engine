## ADDED Requirements

### Requirement: Current capabilities source of truth
The repository SHALL maintain a single current-facts document covering supported broker backends, maturity level, account semantics, local tracked-state semantics, credential source rules, output locations, and known evidence gaps.

#### Scenario: Reader checks broker maturity
- **WHEN** a reader needs to know whether `longport`, `longport-paper`, `alpaca-paper`, or `ibkr-paper` is suitable for a run
- **THEN** the current-facts document lists the supported path, required environment, evidence maturity, and remaining caveats for that backend

#### Scenario: Documentation repeats operational caveats
- **WHEN** README, AGENTS, or a detailed doc mentions broker maturity, account labels, tracked-state scope, or credential safety
- **THEN** it summarizes the fact briefly and links to the current-facts document for the canonical detail

### Requirement: Credential examples match live safety guards
The repository SHALL NOT present repo-local `.env*` or `.envrc*` files as a valid place to store LongPort real access tokens.

#### Scenario: User reads local env example
- **WHEN** a user opens `.env.example`
- **THEN** the example is clearly scoped to local paper/safe development values and excludes a usable LongPort real token placeholder

#### Scenario: User needs LongPort real setup
- **WHEN** a user looks for LongPort real credential instructions
- **THEN** the docs direct them to current-shell exports or a repo-external user-private file such as `~/.config/qexec/longport-live.env`

### Requirement: Test entry points remain explicit
The repository SHALL document the default quick test entry point and separate opt-in commands for e2e, integration, and broker-dependent smoke evidence.

#### Scenario: User runs default tests
- **WHEN** a user follows the default testing instructions
- **THEN** they run `uv run pytest` and the docs state that integration, e2e, and slow tests are excluded unless explicitly selected

#### Scenario: User wants broker evidence
- **WHEN** a user wants broker-backed evidence for LongPort, Alpaca, or IBKR paths
- **THEN** the docs identify the required env vars, local runtime dependencies, and whether the command is automated, operator-supervised, or expected to skip without credentials

### Requirement: CLI documentation reflects exposed commands
The CLI documentation SHALL list the public operator commands and every documented option needed to operate local state repair safely.

#### Scenario: User reviews state repair options
- **WHEN** a user reads the CLI docs for `state-repair`
- **THEN** the docs include `--clear-kill-switch`, `--dedupe-fills`, `--drop-orphan-fills`, `--drop-orphan-terminal-broker-orders`, and `--recompute-parent-aggregates`

#### Scenario: User reviews recovery commands
- **WHEN** a user reads README command examples or CLI docs
- **THEN** the docs include the current recovery chain commands including `cancel-all`, `retry-stale`, `cancel-rest`, `resume-remaining`, and `accept-partial`

### Requirement: Canonical targets contract is unambiguous
The repository SHALL describe `targets.json` as the only accepted rebalance input shape for public execution paths.

#### Scenario: User supplies legacy ticker-list input to rebalance
- **WHEN** a user invokes `qexec rebalance` with a legacy ticker-list or workbook input
- **THEN** the command rejects the input with a clear message requiring a canonical `targets` array

#### Scenario: Internal helper accepts ticker symbols
- **WHEN** an internal smoke or maintainer helper starts from a ticker list
- **THEN** it writes or converts to canonical `targets.json` before invoking the execution path
