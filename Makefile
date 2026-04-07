.PHONY: test test-all test-int test-e2e coverage

test: ## Unit tests
	pytest

test-all: ## Run all tests
	pytest -m "unit or integration or e2e"

test-int: ## Integration tests
	pytest -m "integration" -q

test-e2e: ## End-to-end tests
	pytest -m "e2e" -q

coverage: ## Coverage report
	pytest --cov=stock_analysis --cov-report=term-missing
