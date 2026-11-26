# Developer shortcuts. Every target is a thin wrapper around `uv run`, so CI and
# your laptop run exactly the same commands.

.PHONY: install format lint types imports test check ui ui-check ui-types

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

check: lint types imports test ui-check ## Everything CI runs

# --- The console (ADR-0046): a React app in ui/, built with npm --------------
ui: ## Build the console's page into ui/dist, which `tyche ui` serves
	cd ui && npm ci --no-audit --no-fund && npm run build

ui-check: ## Type-check and lint the console's page
	cd ui && npm ci --no-audit --no-fund && npm run typecheck && npm run lint

ui-types: ## After changing tyche.api.models: write the API schema and the app's types
	uv run python -m tyche.api.schema ui/src/api/openapi.json
	cd ui && npm run api:types
