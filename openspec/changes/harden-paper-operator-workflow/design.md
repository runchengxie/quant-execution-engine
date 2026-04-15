## Context

The repository is intentionally execution-only and is currently using `longport-paper` plus `alpaca-paper` as the lowest-cost way to exercise operator workflows. Recent work has already added `longport-paper`, smoke evidence output, partial-failure evidence capture, and small helper extraction from `longport.py` and `execution.py`, but the behavior is still stronger on happy-path execution than on realistic failure and recovery paths.

The requested scope is to harden the existing paper/operator workflow without turning the project into a larger platform. That means the design must improve failure-mode coverage, evidence quality, and local maintainability for the current command chain:
`config -> account -> quote -> rebalance -> orders -> order -> reconcile -> exceptions -> cancel-all`.

## Goals / Non-Goals

**Goals:**
- Make `longport-paper` smoke/operator failures reproducible and diagnosable through structured evidence rather than only terminal output.
- Define and test the expected behavior for realistic workflow failures and recovery edges, including rebalance failures, query failures, cancel-all partial failures, reconcile query errors, late fills, pending cancel, and partial-fill recovery.
- Keep `execution.py` maintainable by extracting low-risk helper clusters that directly support failure-mode testing and operator behavior.
- Preserve the existing execution-only boundary and single-account semantics.

**Non-Goals:**
- No new broker adapter, multi-account router, event bus, dashboard, or research/backtest scope.
- No attempt to make `longport-paper` and real LongPort identical in maturity.
- No large-scale architectural rewrite of `execution.py` or broker adapters for style alone.
- No new algo execution framework or generalized OMS abstractions.

## Decisions

### 1. Failure-mode coverage will be centered on the existing paper workflow, not new infrastructure

The change will extend tests and existing harness behavior around the current `longport-paper` operator sequence instead of introducing a new testing framework or orchestration layer.

Why:
- The project goal is to harden a real execution workflow, not to build generic workflow tooling.
- `longport-paper` is the closest low-cost proxy for LongPort operator behavior when real funding is inconvenient.

Alternatives considered:
- Add a broader workflow engine for smoke scenarios. Rejected because it adds framework surface without improving current execution claims.
- Focus only on LongPort real. Rejected because current real broker constraints make regression work too expensive and brittle.

### 2. Evidence output will become operator-oriented, not just command-output capture

Smoke evidence will include explicit run outcome metadata such as success/failure, failed step, failure category, skipped steps, state path, latest tracked order reference, and next-step hints when the system can infer them.

Why:
- Operators need to understand what failed, what did not run, and what to inspect next without replaying a full session.
- Structured evidence is more stable than relying on stderr phrasing alone.

Alternatives considered:
- Keep evidence as a raw step transcript. Rejected because it preserves output but not operator meaning.
- Add a separate database or event sink for evidence. Rejected as unnecessary scope expansion.

### 3. Execution refactors must be “pulled by tests”, not “pushed by architecture”

Only helper clusters with obvious repeated account/state/tracked-order resolution logic will be extracted from `execution.py`, and only when that extraction directly reduces duplication in failure-mode handling or test setup.

Why:
- The file is large, but large alone is not a reason to introduce more modules.
- Small helper extraction lowers test friction and regression risk without changing the service contract.

Alternatives considered:
- Full decomposition of `OrderLifecycleService` into multiple services now. Rejected because it would increase coordination cost before the behavior contract is complete.
- No refactor at all. Rejected because some repeated state/tracked-order setup is already impeding failure-mode coverage.

## Risks / Trade-offs

- [Richer evidence schema] → Existing consumers may assume a smaller payload. Mitigation: add fields additively and preserve existing keys.
- [More failure-mode tests] → Tests may become brittle if they overfit exact strings. Mitigation: assert structured fields and key phrases rather than full transcript matches.
- [Incremental helper extraction] → Re-export/import compatibility can break downstream imports. Mitigation: preserve existing public imports and run focused regression suites after each slice.
- [Operator hinting] → Suggested actions could become misleading if over-specified. Mitigation: keep hints conservative and tied to explicit failure categories.

## Migration Plan

1. Extend paper smoke tests and harness evidence additively, preserving existing CLI entry points.
2. Add structured evidence/diagnostic fields behind the current evidence output path instead of changing output destinations.
3. Extract low-risk helper functions from `execution.py` only where repeated state/tracked-order boilerplate already exists.
4. Validate with focused unit and e2e suites for smoke harnesses, execution lifecycle, and existing CLI/broker helper imports.

Rollback is straightforward because the change is file-local and additive:
- revert evidence field additions,
- revert helper extraction imports,
- revert failure-mode tests that depend on new behavior.

## Open Questions

- Which failure categories should be exposed in evidence as stable public labels versus internal/testing-only labels?
- How explicit should next-step hints be when the system knows a failure class but does not know broker-side intent with certainty?
