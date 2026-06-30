.PHONY: api-lint
api-lint: ## Run backend lint checks
	cd $(API_DIR) && uv run ruff check .

.PHONY: api-test
api-test: ## Run backend tests
	cd $(API_DIR) && uv run pytest

.PHONY: api-migrations-check
api-migrations-check: local-env ## Check Alembic migration drift
	cd $(API_DIR) && $(API_ENV) uv run alembic check

.PHONY: web-check
web-check: ## Run the frontend local gate
	cd $(WEB_DIR) && pnpm check

.PHONY: check
check: api-lint api-migrations-check web-check ## Run the main backend and frontend checks
