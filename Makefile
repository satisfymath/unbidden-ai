.PHONY: setup check test lint typecheck web web-build web-check dist

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

# A release's files: the wheel and sdist with the built web workspace inside, and their checksums (docs/INSTALL.md).
dist: web-build
	rm -rf dist
	uv build
	cd dist && (command -v sha256sum >/dev/null 2>&1 && sha256sum *.whl *.tar.gz || shasum -a 256 *.whl *.tar.gz) > SHA256SUMS
	unzip -l dist/*.whl | grep -q unbidden/web/static/index.html
	unzip -l dist/*.whl | grep -q unbidden/distribution/install.sh
	cat dist/SHA256SUMS
