# quant-execution-engine task runner
# ===================================
#
# Usage:
#   make sync                  Install dev + CLI deps
#   make test                  Run fast unit tests
#   make test-all              Run full test suite (unit + integration + e2e)
#   make lint                  Run ruff lint
#   make format                Run ruff format check
#   make typecheck             Run pyright + mypy
#   make quality               Run full quality gate (lint + format + typecheck + test)
#   make preflight-paper       Preflight check against longport-paper
#   make preflight-ibkr        Preflight check against ibkr-paper
#   make smoke-longport-paper  Run operator smoke against longport-paper
#   make smoke-alpaca-paper    Run operator smoke against alpaca-paper
#
# Emergency / operator targets:
#   make emergency-check BROKER=longport-paper
#   make emergency-cancel-all BROKER=longport-paper
#
# Override defaults:
#   BROKER=longport            Default broker for emergency / smoke targets
#   UV_SYNC_ARGS               Extra args for uv sync (e.g. --extra alpaca)

BROKER       ?= longport-paper
UV_SYNC_ARGS ?= --group dev --extra cli

.PHONY: sync
sync:
	uv sync $(UV_SYNC_ARGS)

.PHONY: test
test:
	uv run pytest $(PYTEST_ARGS)

.PHONY: test-all
test-all:
	uv run pytest $(PYTEST_ARGS) -m ''

.PHONY: test-integration
test-integration:
	uv run pytest $(PYTEST_ARGS) -m integration

.PHONY: test-e2e
test-e2e:
	uv run pytest $(PYTEST_ARGS) -m e2e

.PHONY: lint
lint:
	uv run ruff check src/ tests/

.PHONY: format
format:
	uv run ruff format --check src/ tests/

.PHONY: format-fix
format-fix:
	uv run ruff format src/ tests/

.PHONY: typecheck
typecheck:
	uv run pyright src/quant_execution_engine/
	uv run mypy src/quant_execution_engine/

.PHONY: quality
quality: lint format typecheck test
	@echo "=== quality gate passed ==="

.PHONY: preflight-paper
preflight-paper:
	qexec preflight --broker $(BROKER)

.PHONY: preflight-ibkr
preflight-ibkr:
	qexec preflight --broker ibkr-paper

.PHONY: smoke-longport-paper
smoke-longport-paper:
	PYTHONPATH=src uv run python project_tools/smoke_operator_harness.py \
		--broker longport-paper --execute

.PHONY: smoke-alpaca-paper
smoke-alpaca-paper:
	PYTHONPATH=src uv run python -m project_tools.smoke_operator_harness \
		--broker alpaca-paper --execute

.PHONY: emergency-check
emergency-check:
	@echo "=== EMERGENCY CHECKLIST ($(BROKER)) ==="
	@echo
	@echo "1. Kill switch status:"
	qexec state-doctor --broker $(BROKER) || true
	@echo
	@echo "2. Open orders:"
	qexec orders --broker $(BROKER) --status open || true
	@echo
	@echo "3. Exceptions:"
	qexec exceptions --broker $(BROKER) || true
	@echo
	@echo "4. Reconciling with broker:"
	qexec reconcile --broker $(BROKER) || true
	@echo
	@echo "=== checklist done ==="

.PHONY: emergency-cancel-all
emergency-cancel-all:
	@echo "=== EMERGENCY CANCEL-ALL ($(BROKER)) ==="
	qexec cancel-all --broker $(BROKER)
	qexec reconcile --broker $(BROKER)
	@echo "=== cancel-all done, state reconciled ==="

.PHONY: health
health:
	qexec health --broker $(BROKER) || true

.PHONY: report
report:
	qexec report --broker $(BROKER)

.PHONY: evidence-preview
evidence-preview:
	qexec evidence-maturity

.PHONY: help
help:
	@echo "quant-execution-engine task runner"
	@echo
	@echo "Development:"
	@echo "  make sync               Install dev + CLI deps"
	@echo "  make test                Run fast unit tests"
	@echo "  make test-all            Run full suite"
	@echo "  make lint                Ruff lint"
	@echo "  make format              Ruff format check"
	@echo "  make typecheck           Pyright + mypy"
	@echo "  make quality             Full gate: lint + format + typecheck + test"
	@echo
	@echo "Broker smoke (paper only):"
	@echo "  make preflight-paper     Preflight longport-paper"
	@echo "  make preflight-ibkr      Preflight ibkr-paper"
	@echo "  make smoke-longport-paper"
	@echo "  make smoke-alpaca-paper"
	@echo
	@echo "Operational:"
	@echo "  make health              Quick health check (preflight + state-doctor)"
	@echo "  make report              Show latest evidence bundle report"
	@echo "  make emergency-check     Full emergency audit (state + orders + reconcile)"
	@echo "  make emergency-cancel-all  Cancel all open orders + reconcile"
	@echo "  make evidence-preview    Show broker evidence maturity"
	@echo
	@echo "Override BROKER to target a different backend:"
	@echo "  make emergency-check BROKER=longport"
	@echo "  make emergency-check BROKER=alpaca-paper"
