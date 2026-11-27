.PHONY: verify fmt test

UV ?= uv

verify:  ## lint and test (must be green before any PR)
	$(UV) run ruff format --check .
	$(UV) run ruff check .
	$(UV) run pytest -q

fmt:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test:
	$(UV) run pytest -q
