#!/bin/sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
sh "$script_dir/validate_sourceable_env.sh" /config/generated/local.api.env
sh "$script_dir/validate_sourceable_env.sh" /config/targets/local.secrets.env

host_openai_api_key="${OPENAI_API_KEY:-}"
host_anthropic_api_key="${ANTHROPIC_API_KEY:-}"
host_google_api_key="${GOOGLE_API_KEY:-}"
host_azure_openai_api_key="${AZURE_OPENAI_API_KEY:-}"

set -a
. /config/generated/local.api.env
. /config/targets/local.secrets.env
set +a

[ -z "$host_openai_api_key" ] || export OPENAI_API_KEY="$host_openai_api_key"
[ -z "$host_anthropic_api_key" ] || export ANTHROPIC_API_KEY="$host_anthropic_api_key"
[ -z "$host_google_api_key" ] || export GOOGLE_API_KEY="$host_google_api_key"
[ -z "$host_azure_openai_api_key" ] || export AZURE_OPENAI_API_KEY="$host_azure_openai_api_key"

export DATABASE_URL="postgresql+asyncpg://postgres:postgres@postgres:5432/postgres"
export LOCAL_SECRET_STORE_PATH="/data/secrets.enc.json"
export LOCAL_STORAGE_ROOT="/data/storage"

case "${1:-}" in
  api)
    exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log
    ;;
  api-reload)
    exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}" --reload --reload-dir /app --no-access-log
    ;;
  migrate)
    exec alembic upgrade heads
    ;;
  worker)
    exec python -m workers.main
    ;;
  *)
    echo "Unknown compose process: ${1:-missing}" >&2
    exit 64
    ;;
esac
