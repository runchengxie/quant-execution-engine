## Context

`quant_execution_engine` is an execution-only repository with a broker adapter layer, tracked local execution state, preflight checks, operator recovery commands, and smoke tooling. Existing supported broker paths already assume that a broker integration is only complete when adapter behavior, CLI surfacing, tracked-state reconciliation, and operator-facing documentation all work together.

IBKR differs from the current LongPort and Alpaca paths because the runtime is not just remote credentials plus HTTP APIs. The initial paper integration depends on a locally reachable IB Gateway process over the TWS API, plus explicit contract mapping and connection lifecycle handling. That adds new operational prerequisites and new failure modes that must be surfaced cleanly to operators.

## Goals / Non-Goals

**Goals:**

- Add a first-class `ibkr-paper` backend that works through the existing broker lifecycle contract.
- Keep the first slice intentionally small: paper only, single account semantics, and an explicitly documented initial market scope.
- Make IBKR readiness visible through existing operator commands: `config`, `preflight`, `account`, `quote`, `rebalance --execute`, `orders`, `order`, `exceptions`, `cancel`, and `reconcile`.
- Preserve the repository's current maturity model by adding smoke documentation and evidence-oriented operator workflows rather than claiming unproven live support.

**Non-Goals:**

- IBKR live trading support.
- Multi-account routing or true `--account` multiplexing.
- Advanced order types, native modify/replace flows, algorithmic execution, or portfolio margin semantics.
- Immediate support for all IBKR-supported markets and contract types.
- Converging IBKR into a generic broker plugin system outside the current factory-based design.

## Decisions

### 1. First release scope is `ibkr-paper`, `main` account only, and a narrow contract scope

The change will define a minimum vertical slice, not feature parity with every broker behavior IBKR can expose. The backend will initially support `ibkr-paper`, preserve the repository's current single-account semantics, and validate symbol/market scope explicitly so unsupported contracts fail fast instead of being guessed.

This matches the current repository model where broker maturity is earned through a repeatable paper workflow before any live claims are made.

Alternatives considered:

- Add both `ibkr` and `ibkr-paper` immediately. Rejected because it would create live-path obligations before the paper lifecycle is proven.
- Promise broad IBKR market support in v1. Rejected because contract mapping complexity would dominate the first integration and blur failure diagnosis.

### 2. IBKR adapter logic will be split from IBKR runtime/session management

The broker integration will use an `ibkr` adapter module for `BrokerAdapter` conformance and a separate IBKR runtime/client layer for connection setup, teardown, contract resolution, request/response normalization, and error mapping.

This keeps socket or callback-driven API details from leaking into the adapter methods that the execution engine already expects to be synchronous and broker-neutral.

Alternatives considered:

- Put all IBKR calls directly inside `BrokerAdapter` methods. Rejected because connection lifecycle, contract lookup, and error normalization would become hard to test and hard to reuse across `account`, `quote`, `submit`, and `reconcile`.
- Build a new generic event-driven broker abstraction. Rejected because it would be a larger architectural change than this repository currently needs.

### 3. Configuration will be explicit, non-secret, and paper-oriented

The initial IBKR configuration surface will be a small set of runtime values such as host, port, client ID, account identifier, and connection timeout. These values will be inspectable through `qexec config --broker ibkr-paper` because they are routing parameters, not secrets.

The documentation will describe the runtime stack as local IB Gateway over the TWS API, and the CLI/config layer will make that assumption visible instead of treating IBKR like a pure cloud backend.

Alternatives considered:

- Hide IBKR runtime assumptions behind undocumented defaults. Rejected because operator confusion around host, port, login state, and paper routing would become the primary support burden.
- Introduce a large forward-looking configuration matrix for live/paper/TWS/Gateway at once. Rejected because it would add configuration surface before those modes are in scope.

### 4. `preflight` and smoke workflows will treat local gateway readiness as first-class

The IBKR path will not rely on generic downstream exceptions alone. `qexec preflight --broker ibkr-paper` and `project_tools/smoke_operator_harness.py --broker ibkr-paper` will be part of the defined backend contract so connectivity, account resolution, quote access, and paper execution can be verified before implementation is declared complete.

This follows the repository's existing execution philosophy: readiness, reconcile, and operator evidence matter as much as the first successful submit.

Alternatives considered:

- Rely on `account` or `rebalance` failures as the de facto readiness test. Rejected because the resulting diagnostics would be less specific and harder for operators to act on.
- Treat smoke execution as out-of-band manual knowledge. Rejected because the repository already has first-class operator smoke tooling and evidence output.

### 5. Testing will stay layered and evidence-driven

The change will add unit tests for normalization and validation, selective integration tests for runtime-backed behavior, and operator-smoke coverage aligned with the existing paper broker paths. CI will continue to default to fast unit tests; IBKR runtime-dependent tests remain explicitly selected.

Alternatives considered:

- Require full IBKR runtime coverage in default CI. Rejected because local gateway availability is environment-dependent and would reduce test determinism.
- Skip integration/smoke coverage and rely on unit tests. Rejected because the runtime dependency is a material part of the backend contract.

## Risks / Trade-offs

- [IBKR client library choice remains unsettled] → Keep engine code behind an internal runtime abstraction and finalize the external dependency during implementation.
- [IBKR contract mapping is more ambiguous than current brokers] → Define a narrow initial market scope and reject unsupported symbols early.
- [Local gateway login state creates operator friction] → Surface host, port, account, and connectivity assumptions in config, preflight, and dedicated smoke docs.
- [Paper execution may still behave differently from future live support] → Keep live support explicitly out of scope and require new evidence before adding `ibkr`.
- [Adding backend-specific checks can bloat generic CLI code] → Keep IBKR-specific probing isolated behind helper functions or runtime-aware adapter methods rather than spreading conditionals widely.

## Migration Plan

1. Add the optional IBKR dependency and backend registration without changing any existing broker default.
2. Implement the runtime wrapper and adapter methods for `ibkr-paper`.
3. Extend config output, preflight, and smoke tooling so operators can validate the runtime before mutation.
4. Add tests and operator docs, then collect at least one paper smoke evidence sample before treating the backend as ready for routine use.

Rollback is straightforward because the change is additive: remove `ibkr-paper` from configuration, omit the IBKR optional dependency, and stop using the backend while leaving existing broker paths untouched.

## Open Questions

- Which Python IBKR client wrapper should become the supported optional dependency for the first implementation?
- What exact initial market scope should be supported in v1: US equities only, or a slightly broader but still explicit set?
- Should `qexec config --broker ibkr-paper` display only raw routing values, or also include derived guidance such as the expected default paper port and gateway requirement?
- When live support is explored later, should the project support TWS UI directly, or stay Gateway-only even beyond the first slice?
