.PHONY: bootstrap
bootstrap: local-env install ## Create local env files and install app dependencies

.PHONY: local-env
local-env: ## Create local env files and storage folders if they are missing
	@mkdir -p .local/generated .local/targets .local/storage
	@if [ ! -s "$(API_DIR)/.env" ]; then \
		cp "$(API_DIR)/.env.example" "$(API_DIR)/.env"; \
		echo "Created $(API_DIR)/.env"; \
	fi
	@if [ ! -s ".local/generated/local.api.env" ]; then \
		cp "$(API_DIR)/.env.example" ".local/generated/local.api.env"; \
		echo "Created .local/generated/local.api.env"; \
	fi
	@if [ ! -f ".local/generated/local.web.env" ]; then \
		printf '%s\n' 'VITE_API_BASE_URL=http://localhost:8000/api/v1' > ".local/generated/local.web.env"; \
		echo "Created .local/generated/local.web.env"; \
	fi
	@touch .local/targets/local.secrets.env

.PHONY: install
install: api-install web-install ## Install backend and frontend dependencies

.PHONY: api-install
api-install: ## Install backend dependencies with uv
	cd $(API_DIR) && uv sync

.PHONY: web-install
web-install: ## Install frontend dependencies with pnpm
	cd $(WEB_DIR) && pnpm install

.PHONY: dev
dev: local-env ## Start Postgres, migrate, then run API, worker, and web dev servers
	@$(MAKE) db-up
	@$(MAKE) db-wait
	@$(MAKE) migrate
	@$(MAKE) -j3 api-dev worker-dev web-dev

.PHONY: dev-kill
dev-kill: ## Stop local API and web dev servers on their configured ports
	@pids="$$(lsof -tiTCP:$(API_PORT) -sTCP:LISTEN) $$(lsof -tiTCP:$(WEB_PORT) -sTCP:LISTEN)"; \
	pids="$$(printf '%s\n' "$$pids" | tr ' ' '\n' | awk 'NF' | sort -u)"; \
	if [ -z "$$pids" ]; then \
		echo "No local API or web dev listeners found."; \
	else \
		echo "Stopping local API/web listener PIDs:"; \
		printf '  %s\n' $$pids; \
		kill $$pids; \
	fi

.PHONY: db-up
db-up: local-env ## Start local Postgres in Docker
	$(COMPOSE) up -d postgres

.PHONY: db-wait
db-wait: ## Wait for local Postgres to accept connections
	@printf 'Waiting for Postgres'
	@for i in $$(seq 1 30); do \
		if $(COMPOSE) exec -T postgres pg_isready -U postgres -d postgres >/dev/null 2>&1; then \
			printf '\nPostgres is ready\n'; \
			exit 0; \
		fi; \
		printf '.'; \
		sleep 1; \
	done; \
	printf '\nPostgres did not become ready in time\n'; \
	exit 1

.PHONY: migrate
migrate: local-env ## Apply all Alembic migrations
	cd $(API_DIR) && $(API_ENV) uv run alembic upgrade heads

.PHONY: api-dev
api-dev: local-env ## Run the FastAPI development server on http://localhost:8000
	cd $(API_DIR) && uv run uvicorn main:app --reload --host 127.0.0.1 --port $(API_PORT)

.PHONY: worker-dev
worker-dev: local-env ## Run the scheduled agent runner
	cd $(API_DIR) && uv run python -m workers.main

.PHONY: web-dev
web-dev: local-env ## Run the Vite development server on http://localhost:3000
	cd $(WEB_DIR) && pnpm dev --host 127.0.0.1 --port $(WEB_PORT)
