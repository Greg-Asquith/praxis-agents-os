.PHONY: bootstrap
bootstrap: doctor local-env install ## Check tools, create local env files, and install dependencies

.PHONY: local-env
local-env: ## Create local env files and storage folders if they are missing
	@$(COMPOSE) run --rm init

.PHONY: doctor
doctor: ## Check local contributor tool versions and print actionable install hints
	@failed=0; \
	if ! docker --version >/dev/null 2>&1; then \
		echo "Missing Docker. Install Docker Desktop: https://docs.docker.com/desktop/"; failed=1; \
	elif ! $(COMPOSE) version >/dev/null 2>&1; then \
		echo "Missing Docker Compose. Install the Compose plugin or docker-compose: https://docs.docker.com/compose/install/"; failed=1; \
	else \
		echo "Docker: $$(docker --version)"; \
		echo "Compose: $$($(COMPOSE) version --short 2>/dev/null || $(COMPOSE) version)"; \
	fi; \
	if ! command -v uv >/dev/null 2>&1; then \
		echo "Missing uv. Install it from https://docs.astral.sh/uv/getting-started/installation/"; failed=1; \
	else \
		echo "uv: $$(uv --version)"; \
		if [ -x "$(API_DIR)/.venv/bin/python" ] && "$(API_DIR)/.venv/bin/python" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then \
			echo "Python: $$($(API_DIR)/.venv/bin/python --version) (project environment)"; \
		elif uv python find 3.12 >/dev/null 2>&1; then \
			echo "Python: $$(uv python find 3.12)"; \
		else \
			echo "Python 3.12 is required. Run: uv python install 3.12"; failed=1; \
		fi; \
	fi; \
	if ! command -v node >/dev/null 2>&1; then \
		echo "Missing Node.js 24. Install it from https://nodejs.org/"; failed=1; \
	elif ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) === 24 ? 0 : 1)'; then \
		echo "Node.js 24 is required; found $$(node --version)."; failed=1; \
	else echo "Node: $$(node --version)"; fi; \
	if ! command -v pnpm >/dev/null 2>&1; then \
		echo "Missing pnpm. Run: corepack enable"; failed=1; \
	else echo "pnpm: $$(pnpm --version)"; fi; \
	exit $$failed

.PHONY: install
install: api-install web-install ## Install backend and frontend dependencies

.PHONY: api-install
api-install: ## Install backend dependencies with uv
	cd $(API_DIR) && uv sync

.PHONY: web-install
web-install: ## Install frontend dependencies with pnpm
	cd $(WEB_DIR) && pnpm install

.PHONY: dev
dev: doctor local-env ## Start Postgres, migrate, then run API, worker, and web dev servers
	@$(MAKE) db-up
	@$(MAKE) db-wait
	@$(MAKE) migrate
	@$(MAKE) -j3 api-dev worker-dev web-dev

.PHONY: dev-kill
dev-kill: ## Stop local API, worker, and web dev processes
	@pids="$$(lsof -tiTCP:$(API_PORT) -sTCP:LISTEN) $$(lsof -tiTCP:$(WEB_PORT) -sTCP:LISTEN)"; \
	pids="$$(printf '%s\n' "$$pids" | tr ' ' '\n' | awk 'NF' | sort -u)"; \
	if [ -z "$$pids" ]; then \
		echo "No local API or web dev listeners found."; \
	else \
		echo "Stopping local API/web listener PIDs:"; \
		printf '  %s\n' $$pids; \
		kill $$pids; \
	fi; \
	worker_pid_file=".local/generated/worker.pid"; \
	if [ -s "$$worker_pid_file" ]; then \
		worker_pid="$$(cat "$$worker_pid_file")"; \
		worker_command="$$(ps -p "$$worker_pid" -o command= 2>/dev/null || true)"; \
		case "$$worker_command" in \
			*"watchfiles"*"workers.main"*) \
				echo "Stopping local worker PID $$worker_pid"; \
				kill "$$worker_pid" ;; \
			*) \
				echo "Ignoring stale worker PID file." ;; \
		esac; \
		rm -f "$$worker_pid_file"; \
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

.PHONY: test-db
test-db: db-up db-wait ## Ensure the praxis_test database exists
	@$(COMPOSE) exec -T postgres psql -U postgres -tAc \
		"SELECT 1 FROM pg_database WHERE datname = 'praxis_test'" | grep -q 1 || \
		$(COMPOSE) exec -T postgres createdb -U postgres praxis_test

.PHONY: migrate
migrate: local-env ## Apply all Alembic migrations
	cd $(API_DIR) && $(API_ENV) uv run alembic upgrade heads

.PHONY: api-dev
api-dev: local-env ## Run the FastAPI development server on http://localhost:8000
	cd $(API_DIR) && uv run uvicorn main:app --reload --host 127.0.0.1 --port $(API_PORT) --no-access-log

.PHONY: worker-dev
worker-dev: local-env ## Run the scheduled agent runner with auto-reload
	@cd $(API_DIR); \
	worker_pid_file="../../.local/generated/worker.pid"; \
	uv run watchfiles "python -m workers.main" workers services models core utils integrations .env & \
	worker_pid="$$!"; \
	printf '%s\n' "$$worker_pid" > "$$worker_pid_file"; \
	trap 'kill "$$worker_pid" 2>/dev/null || true; rm -f "$$worker_pid_file"' 0 1 2 15; \
	wait "$$worker_pid"

.PHONY: web-dev
web-dev: local-env ## Run the Vite development server on http://localhost:3000
	cd $(WEB_DIR) && pnpm dev --host 127.0.0.1 --port $(WEB_PORT)
