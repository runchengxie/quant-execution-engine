## Context

This repository is execution-only. It already has broker-backed execution paths, tracked local state, reconcile, risk decisions, smoke harness evidence output, and operator recovery commands. The remaining problem is not a missing broad platform layer; it is that several important paths are still easier to describe from code than to prove from evidence.

The current completion boundary in `docs/execution-checklist.md` is aligned with this: LongPort real still needs supervised submit/query/cancel/reconcile evidence, `ibkr-paper` still needs effective-market-data broker order evidence, and failure scenarios need deeper regression coverage. Existing artifacts already include targets, audit JSONL, state JSON, smoke evidence JSON, and operator notes, but they are scattered across `outputs/` and documentation.

## Goals / Non-Goals

**Goals:**
- Make broker/backend maturity explicit as code-path maturity plus evidence maturity.
- Package already-produced execution artifacts into a reviewable evidence bundle.
- Surface risk `BYPASS` decisions where operators make submit decisions.
- Give operators consistent next-step guidance for dirty tracked-order and smoke failure states.
- Keep changes small, file-backed, and compatible with the current CLI and smoke harness shape.

**Non-Goals:**
- Add a database, event bus, scheduler, dashboard, or broker-wide order book.
- Add multi-account routing beyond current label validation.
- Add TWAP/POV or any general algorithmic execution framework.
- Add fractional `resume-remaining` support in this change.
- Promote every broker backend to the same maturity level at once.

## Decisions

### Decision: Treat evidence maturity as a first-class local report

Add a small evidence maturity model that can be rendered in docs and optionally through CLI/test helpers. Each broker/backend entry records the supported code path, latest evidence artifact path if available, missing proof, and recommended next smoke action.

Alternative considered: infer maturity only from README prose. That keeps implementation smaller but leaves evidence status hard to test and easy to drift.

### Decision: Evidence bundles copy references, not broker state

The bundle capability should collect the existing target input, audit log, state snapshot, smoke evidence JSON, and operator note into a timestamped review directory or archive. It should not fetch broker-wide orders or mutate broker state.

Alternative considered: build a richer evidence database. That is out of scope for a single-machine, low-frequency execution repo and would pull the project toward platform infrastructure.

### Decision: Summarize `BYPASS` separately from `PASS`

Risk gate output should keep the existing `PASS` / `BLOCK` / `BYPASS` semantics, but preflight and rebalance summaries should list bypassed gates explicitly with reasons. A configured-but-unevaluated market-data gate is not equivalent to a passed gate.

Alternative considered: turn every market-data `BYPASS` into a hard block. That would be safer in some live contexts but changes execution semantics too broadly for this boundary-setting change.

### Decision: Centralize operator next-step classification

Next-step wording should continue to flow through the existing diagnostics/rendering path instead of creating a separate command runner. The output should advise an operator to reconcile, wait, cancel-rest, resume-remaining, accept-partial, adjust inputs, or inspect broker state; it should not automatically perform the next mutation.

Alternative considered: implement semi-automatic recovery scripts. That is premature until failure evidence is stronger and would raise the risk of incorrect broker mutations.

## Risks / Trade-offs

- Evidence maturity can become stale -> Keep it generated or covered by behavior tests where possible, and update smoke docs when evidence paths change.
- Bundle lookup by run id may be ambiguous -> Require deterministic matching and fail with candidate paths instead of guessing.
- More warnings may make output noisy -> Render a compact summary first, with structured JSON carrying full detail.
- Operator hints can be overconfident -> Phrase hints as recommended next steps and keep broker mutation behind existing explicit commands.
- Existing ignored `outputs/` artifacts may be absent in CI -> Unit tests should use temporary fixture artifacts and not depend on local private evidence files.

## Migration Plan

No data migration is required. The change should add new files and summary fields while keeping existing audit/state formats readable. Existing commands should remain compatible; new structured fields can be additive.

Rollback is straightforward: remove the new command/helper and rendering additions while leaving existing execution, state, and broker behavior unchanged.

## Open Questions

- Should the evidence bundle default to a directory or a zip archive? Directory output is easier to inspect and test; zip output is easier to share.
- Should broker evidence maturity be exposed as a standalone CLI command, a documentation-generated table, or both?
- Should live LongPort evidence bundle creation require an explicit operator note, or merely recommend one?
