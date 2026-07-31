.PHONY: compose-dev
compose-dev: local-env ## Run the full dev stack in Docker with bind mounts and hot reload
	$(DEV_COMPOSE) up --build

.PHONY: compose-dev-detached
compose-dev-detached: local-env ## Run the Docker dev stack in the background
	$(DEV_COMPOSE) up -d --build

.PHONY: quickstart
quickstart: ## Start the production-image local stack with Docker only
	@command -v docker >/dev/null 2>&1 || { echo "Docker is required: https://docs.docker.com/desktop/"; exit 1; }
	@$(COMPOSE) version >/dev/null 2>&1 || { echo "Docker Compose is required: https://docs.docker.com/compose/install/"; exit 1; }
	@$(COMPOSE) run --rm init
	@key="$${OPENAI_API_KEY:-$${ANTHROPIC_API_KEY:-$${GOOGLE_API_KEY:-}}}"; \
	[ -n "$$key" ] || key="$$(awk -F= '/^(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY)=.+/ { print substr($$0, index($$0, "=") + 1); exit }' .local/targets/local.secrets.env)"; \
	if [ -z "$$key" ]; then \
		if [ ! -t 0 ]; then \
			echo "An LLM API key is required. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY in .local/targets/local.secrets.env or the shell, then rerun make quickstart."; \
			exit 1; \
		fi; \
		printf 'OpenAI, Anthropic, or Google API key: '; \
		stty -echo; IFS= read -r key; stty echo; printf '\n'; \
		case "$$key" in \
			sk-ant-*) key_var=ANTHROPIC_API_KEY ;; \
			sk-*) key_var=OPENAI_API_KEY ;; \
			AIza*) key_var=GOOGLE_API_KEY ;; \
			*) echo "That does not look like an OpenAI (sk-...), Anthropic (sk-ant-...), or Google (AIza...) API key."; exit 1 ;; \
		esac; \
		printf '%s\n' "$$key" | sh apps/api/bin/replace_env_value.sh \
			.local/targets/local.secrets.env "$$key_var"; \
	fi
	$(COMPOSE) build
	@echo "Starting Praxis. Open http://localhost:$${PRAXIS_WEB_PORT:-3000}, sign up, then create your first workspace."
	$(COMPOSE) up

.PHONY: compose-down
compose-down: ## Stop the Compose stack without deleting volumes
	$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Follow logs for the Compose stack
	$(COMPOSE) logs -f
