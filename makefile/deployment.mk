.PHONY: compose-up
compose-up: local-env ## Build and run Postgres, API, and web through Docker Compose
	$(COMPOSE) up --build postgres api web

.PHONY: compose-up-detached
compose-up-detached: local-env ## Build and run the full Compose stack in the background
	$(COMPOSE) up -d --build postgres api web

.PHONY: compose-down
compose-down: ## Stop the Compose stack without deleting volumes
	$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Follow logs for the Compose stack
	$(COMPOSE) logs -f postgres api web
