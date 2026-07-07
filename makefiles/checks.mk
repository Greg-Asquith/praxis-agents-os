.PHONY: api-lint
api-lint: ## Run backend lint checks
	cd $(API_DIR) && uv run ruff check .

.PHONY: api-format-check
api-format-check: ## Check backend formatting
	cd $(API_DIR) && uv run ruff format --check .

.PHONY: api-test
api-test: test-db ## Run backend tests against the local test database
	cd $(API_DIR) && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest

.PHONY: api-migrations-check
api-migrations-check: local-env ## Check Alembic migration drift
	cd $(API_DIR) && $(API_ENV) uv run alembic check

.PHONY: web-check
web-check: ## Run the frontend local gate
	cd $(WEB_DIR) && pnpm check

.PHONY: check
check: api-lint api-format-check api-migrations-check api-test web-check ## Run the main backend and frontend checks
