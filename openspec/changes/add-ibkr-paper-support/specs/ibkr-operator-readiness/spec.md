## ADDED Requirements

### Requirement: IBKR paper runtime configuration is inspectable
The system SHALL expose the effective non-secret IBKR paper runtime configuration through `qexec config --broker ibkr-paper` so operators can confirm what endpoint and account routing the CLI will use.

#### Scenario: Effective runtime configuration is displayed
- **WHEN** an operator runs `qexec config --broker ibkr-paper`
- **THEN** the output SHALL identify `ibkr-paper` as a paper backend and display the resolved host, paper port, client ID, account identifier, and runtime assumptions needed for operator validation

### Requirement: IBKR paper preflight checks local runtime readiness
The system SHALL treat local IB Gateway reachability and IBKR paper account/market-data readiness as formal preflight checks before operators attempt mutation.

#### Scenario: Gateway connectivity is unavailable
- **WHEN** `qexec preflight --broker ibkr-paper` cannot connect to the configured local IB Gateway endpoint
- **THEN** the preflight result SHALL fail with a connectivity-oriented message instead of a generic unsupported operation error

#### Scenario: Account and quote access are healthy
- **WHEN** `qexec preflight --broker ibkr-paper` reaches IB Gateway, resolves the supported account, and retrieves the requested symbol data
- **THEN** the preflight result SHALL report passing account-resolution, account-snapshot, and quote checks for the IBKR paper backend

### Requirement: IBKR paper smoke workflow is repeatable
The system SHALL provide a repeatable operator-supervised smoke workflow for `ibkr-paper` that mirrors the existing paper broker evidence model.

#### Scenario: Operator harness supports IBKR paper
- **WHEN** `project_tools/smoke_operator_harness.py` is run with `--broker ibkr-paper`
- **THEN** the harness SHALL support at least `--preflight-only` and `--execute` flows and preserve structured evidence output using the existing evidence contract

#### Scenario: Operator documentation identifies the runtime stack
- **WHEN** an operator reads the IBKR paper documentation
- **THEN** the documentation SHALL state that the backend depends on a locally running IB Gateway over the TWS API and SHALL enumerate the ordered config, preflight, account, quote, rebalance, and reconcile steps required for a paper smoke run
