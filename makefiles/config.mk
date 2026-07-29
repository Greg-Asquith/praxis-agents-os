API_DIR := apps/api
WEB_DIR := apps/web
COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf '%s' 'docker compose'; elif docker-compose version >/dev/null 2>&1; then printf '%s' 'docker-compose'; else printf '%s' 'docker compose'; fi)
DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
API_ENV := set -a; . ./.env; set +a;
API_PORT := 8000
WEB_PORT := 3000
