# Developer shortcuts. Every target is a thin wrapper around `uv run`, so CI and
# your laptop run exactly the same commands.

.PHONY: install format lint types imports test check

install: ## Create the virtualenv and install the locked dependencies
	uv sync --locked

format: ## Auto-format and apply safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint and check formatting, without changing files
	uv run ruff check .
	uv run ruff format --check .

types: ## Static type check (mypy, strict)
	uv run mypy

imports: ## Check the architecture contracts (import-linter)
	uv run lint-imports

test: ## Run the test suite with coverage
	uv run pytest --cov --cov-report=term-missing

check: lint types imports test ## Everything CI runs
