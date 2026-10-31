.PHONY: setup check test lint typecheck

setup:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run pyright

test:
	uv run pytest -q

check: lint typecheck test

# The optional web workspace (docs/frontend/). Nothing here is needed by the CLI.
web:
	uv run python -m unbidden.web --demo --dev

web-build:
	cd frontend && npm ci && npm run build

web-check:
	cd frontend && npm run lint && npm run typecheck && npm test
	uv run pytest tests/web -q
