## Context

This repository is an execution-only Python package. Research, AI, backtesting, and data import layers are intentionally out of scope. The current CLI and broker paths cover dry-run rebalance plus broker-backed submit/query/cancel/reconcile paths for LongPort real, `longport-paper`, Alpaca paper, and `ibkr-paper`, with different maturity levels and explicit operator-supervised caveats.

The current audit found four kinds of drift:

- Configuration examples conflict with live safety rules: `.env.example` invites local real `LONGPORT_ACCESS_TOKEN` storage, while runtime guards and docs reject repo-local real tokens.
- Documentation repeats the same facts in `README.md`, `AGENTS.md`, `docs/testing.md`, `docs/configuration.md`, and execution runbooks, which makes maturity and caveat drift likely.
- Historical LongBridge names and `LONGBRIDGE_*` fallbacks remain mixed into LongPort-facing tests, modules, and docs.
- Several files are correct but broad enough to slow future changes: `cli_parser.py::create_parser`, `project_tools/smoke_operator_harness.py::run_operator_smoke_workflow`, `broker/longport.py::portfolio_snapshot`, `state_tools.py::doctor`, and `cli.py::main`.

Default tests currently pass with `191 passed, 1 skipped, 24 deselected`, so this change should preserve existing behavior while tightening documentation and reducing maintenance risk.

## Goals / Non-Goals

**Goals:**

- Establish one current-facts document for supported brokers, credential rules, testing modes, account semantics, state semantics, output locations, and evidence gaps.
- Make README, AGENTS, and detailed docs summarize and link to the current-facts document rather than duplicating full caveat lists.
- Make local environment examples consistent with live credential isolation.
- Make the target input contract explicit in both docs and code by removing or quarantining legacy ticker-list/weights compatibility from the rebalance runtime.
- Mark LongBridge naming and env fallbacks as deprecated compatibility, then rename externally visible tests/docs where possible.
- Classify `project_tools` as operator smoke harnesses or maintainer-only utilities.
- Refactor the highest-risk long functions into local helpers without changing command behavior.

**Non-Goals:**

- No broker API expansion, new order type, multi-account routing, or real broker maturity claim.
- No default inclusion of integration, e2e, or networked tests.
- No removal of recovery commands such as `cancel-rest`, `resume-remaining`, `accept-partial`, `retry-stale`, `state-doctor`, `state-prune`, or `state-repair`.
- No broad style-only churn across unrelated files.

## Decisions

1. Create a single current-facts document rather than spreading corrections across all docs.

   Rationale: the same facts appear in several places today: account labels are not multi-account routing, tracked state is not the broker order book, LongPort real is operator-supervised, `ibkr-paper` is Gateway-dependent, and credential source precedence differs by broker mode. A central document lowers the chance of future drift.

   Alternative considered: update every existing document independently. That would solve today's wording but keeps the same drift mechanism.

2. Make `.env.example` paper-safe and move live examples out of repo-local env files.

   Rationale: runtime guards already enforce that LongPort real tokens must not come from repo-local `.env*` / `.envrc*`. The example file must not instruct users to do the thing the guard rejects.

   Alternative considered: keep a placeholder `LONGPORT_ACCESS_TOKEN` in `.env.example` with a warning. That still trains users to put the key in the wrong file and makes live failures look surprising.

3. Prefer removing legacy target parsing from the rebalance runtime unless implementation review finds a real internal dependency.

   Rationale: docs and CLI now state that rebalance accepts canonical `targets.json` only. Keeping runtime compatibility makes the real contract ambiguous and adds test burden.

   Alternative considered: document legacy parsing as supported. That conflicts with the current execution-only boundary and keeps old input shapes alive in the main package.

4. Treat LongBridge names as compatibility, not product terminology.

   Rationale: dependencies, broker names, docs, and CLI are LongPort-facing. LongBridge fallbacks can stay temporarily where needed for user environments, but external-facing files should not suggest LongBridge is the current product backend.

   Alternative considered: delete all fallback support in one pass. That could break existing private environments without enough migration signal.

5. Refactor by behavior boundary rather than line-count alone.

   Rationale: large files are only a problem when they mix unrelated responsibilities. The first pass should extract helpers around repeated argument groups, smoke workflow steps, LongPort quote/account/order operations, and state repair primitives.

   Alternative considered: enforce a hard line-count rule. That encourages churn without guaranteeing clearer code.

## Risks / Trade-offs

- Legacy target compatibility may still be used by private scripts → Search call sites first; if usage exists, move conversion to a clearly named maintainer or test helper before removing runtime support.
- Documentation centralization can hide important warnings one click away → Keep short safety summaries in README and AGENTS, but link to the source of truth for details.
- LongBridge deprecation may surprise users with old env names → Keep fallbacks for one change, document deprecation, and add tests that current `LONGPORT_*` names win.
- Refactoring LongPort and state maintenance code can alter broker behavior accidentally → Use existing behavior tests first, then add focused tests around changed helper boundaries before editing deeper broker code.
- Maintainer-only script relocation can break personal workflows → Preserve script entry points with a short compatibility wrapper or document the new path in the same change.

## Migration Plan

1. Add `docs/current-capabilities.md` or equivalent support matrix and move duplicated facts into it.
2. Rewrite README, AGENTS, and detailed docs to summarize and link to the matrix.
3. Split local paper env examples from live credential examples.
4. Align `.envrc` and `.envrc.example` or reduce the tracked `.envrc` to a direct copy of the example model.
5. Clean up target input compatibility according to call-site findings.
6. Rename LongPort-facing tests/docs where names are user-visible; leave fallback internals with deprecation comments.
7. Refactor code hotspots in small commits with tests after each boundary.
8. Run default tests after each phase; run e2e/integration only for affected paths or when broker/runtime behavior changes.

Rollback is straightforward for documentation-only steps. For runtime cleanup, revert the specific compatibility or helper extraction commit if behavior changes unexpectedly.

## Open Questions

- Should repo-tracked `.envrc` stay as a working file, or should only `.envrc.example` be tracked?
- Should legacy target conversion remain available in a maintainer tool, or be removed entirely?
- How long should `LONGBRIDGE_*` env fallbacks remain before removal?
- Should maintainer-only `project_tools/package.sh` remain at its current path with clearer labeling, or move under a dedicated internal tools directory?
