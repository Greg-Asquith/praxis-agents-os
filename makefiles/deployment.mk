.PHONY: compose-dev
compose-dev: local-env ## Run the full dev stack in Docker with bind mounts and hot reload
	$(DEV_COMPOSE) up --build

.PHONY: compose-dev-detached
compose-dev-detached: local-env ## Run the Docker dev stack in the background
	$(DEV_COMPOSE) up -d --build

.PHONY: quickstart-setup
quickstart-setup:
	@command -v docker >/dev/null 2>&1 || { echo "Docker is required: https://docs.docker.com/get-docker/"; exit 1; }
	@$(COMPOSE) version >/dev/null 2>&1 || { echo "Docker Compose is required: https://docs.docker.com/compose/install/"; exit 1; }
	@$(COMPOSE) run --rm init
	@key="$${OPENAI_API_KEY:-$${ANTHROPIC_API_KEY:-$${GOOGLE_API_KEY:-}}}"; \
	[ -n "$$key" ] || key="$$(awk -F= '/^(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY)=.+/ { print substr($$0, index($$0, "=") + 1); exit }' .local/targets/local.secrets.env)"; \
	if [ -z "$$key" ]; then \
		if [ ! -t 0 ]; then \
			echo "An LLM API key is required. Export OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY, or save one in .local/targets/local.secrets.env (see \"Run a scripted install\" in README.md), then rerun make quickstart."; \
			exit 1; \
		fi; \
		printf 'OpenAI, Anthropic, or Google API key: '; \
		stty -echo; IFS= read -r key; stty echo; printf '\n'; \
		case "$$key" in \
			sk-or-*) ;; \
			sk-ant-*) key_var=ANTHROPIC_API_KEY ;; \
			sk-*) key_var=OPENAI_API_KEY ;; \
			AIza*) key_var=GOOGLE_API_KEY ;; \
			*) echo "That does not look like an OpenAI (sk-...), Anthropic (sk-ant-...), or Google (AIza...) API key."; exit 1 ;; \
		esac; \
	fi; \
	case "$$key" in \
		sk-or-*) echo "OpenRouter keys (sk-or-...) are not supported. Use an OpenAI, Anthropic, or Google API key."; exit 1 ;; \
	esac; \
	[ -z "$${key_var:-}" ] || printf '%s\n' "$$key" | sh apps/api/bin/replace_env_value.sh \
		.local/targets/local.secrets.env "$$key_var"
	$(COMPOSE) build

.PHONY: quickstart
quickstart: quickstart-setup ## Start the production-image local stack with Docker only
	@echo "Starting Praxis. Open http://localhost:$${PRAXIS_WEB_PORT:-3000}, sign up, then create your first workspace. Stop with Ctrl+C."
	$(COMPOSE) up

.PHONY: quickstart-detached
quickstart-detached: quickstart-setup ## Start the production-image local stack in the background
	$(COMPOSE) up -d
	@echo "Praxis is running at http://localhost:$${PRAXIS_WEB_PORT:-3000}. Follow logs with make compose-logs; stop with make compose-down."

.PHONY: compose-down
compose-down: ## Stop the Compose stack without deleting volumes
	$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Follow logs for the Compose stack
	$(COMPOSE) logs -f

.PHONY: gcp-bootstrap
gcp-bootstrap: ## Bootstrap one GCP environment (requires ENV_FILE=... and interactive approval)
	@test -n "$(ENV_FILE)" || { echo "ENV_FILE is required"; exit 2; }
	deploy/gcp/bootstrap.sh "$(ENV_FILE)"

.PHONY: gcp-deploy
gcp-deploy: ## Build, migrate, and deploy one GCP environment (requires ENV_FILE=...)
	@test -n "$(ENV_FILE)" || { echo "ENV_FILE is required"; exit 2; }
	deploy/gcp/deploy.sh "$(ENV_FILE)" $(GIT_SHA)

.PHONY: gcp-check
gcp-check: ## Validate GCP helpers and render fake manifests
	deploy/gcp/tests/test.sh
