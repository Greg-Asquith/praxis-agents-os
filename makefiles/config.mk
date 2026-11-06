API_DIR := apps/api
WEB_DIR := apps/web
ISOLATION_DRIVER_DIR := apps/isolation-driver
MEDIA_RENDERER_DIR := apps/media-renderer
DATA_SCIENCE_DIR := apps/data-science
COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf '%s' 'docker compose'; elif docker-compose version >/dev/null 2>&1; then printf '%s' 'docker-compose'; else printf '%s' 'docker compose'; fi)
# Compose runs the API containers as this user; see docker-compose.yml.
export PRAXIS_UID ?= $(shell id -u)
export PRAXIS_GID ?= $(shell id -g)
DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
API_ENV := set -a; . ./.env; set +a;
API_PORT := 8000
WEB_PORT := 3000
