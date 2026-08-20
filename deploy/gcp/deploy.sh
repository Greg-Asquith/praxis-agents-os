#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
  echo "Usage: $0 [--render-only OUTPUT_DIR] ENV_FILE [GIT_SHA]" >&2
}

die() {
  echo "error: $*" >&2
  exit 1
}

RENDER_ONLY=false
OUTPUT_DIR=""
if [[ "${1:-}" == "--render-only" ]]; then
  [[ $# -ge 3 ]] || { usage; exit 2; }
  RENDER_ONLY=true
  OUTPUT_DIR=$2
  shift 2
fi
[[ $# -ge 1 && $# -le 2 ]] || { usage; exit 2; }

ENV_FILE=$1
[[ -f "$ENV_FILE" ]] || die "environment file not found: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

GIT_SHA=${2:-}
if [[ -z "$GIT_SHA" ]]; then
  GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
fi
[[ "$GIT_SHA" =~ ^[0-9a-fA-F]{7,64}$ ]] || die "GIT_SHA must be a 7-64 character hexadecimal commit id"

required_vars=(
  GCP_PROJECT_ID GCP_PROJECT_NUMBER GCP_REGION ARTIFACT_REGISTRY_REPOSITORY
  API_IMAGE_NAME WEB_IMAGE_NAME CLOUD_SQL_INSTANCE API_SERVICE_ACCOUNT
  WEB_SERVICE_ACCOUNT WORKER_SERVICE_ACCOUNT MIGRATE_SERVICE_ACCOUNT
  DATABASE_MAINTENANCE_URL_SECRET_ID RUNTIME_SECRET_BINDINGS
  MIGRATE_SECRET_ENV_NAMES
  DEPLOYMENT_ENVIRONMENT GCS_PUBLIC_ASSETS_BUCKET GCS_WORKSPACE_BUCKET_LOCATION
  WORKSPACE_BUCKET_PREFIX PUBLIC_ASSETS_BASE_URL APP_BASE_URL FRONTEND_URL
  ALLOWED_CORS_ORIGINS COOKIE_DOMAIN ARTIFACT_ORIGIN
  ARTIFACT_SHARING_ENABLED ALLOW_SIGNUP SUPER_ADMIN_EMAILS ALLOW_WORKSPACE_CREATION
  EMAIL_AUTH_ENABLED GOOGLE_OAUTH_ENABLED GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_REDIRECT_URI
  GITHUB_OAUTH_ENABLED GITHUB_OAUTH_CLIENT_ID GITHUB_OAUTH_REDIRECT_URI
  MICROSOFT_OAUTH_ENABLED MICROSOFT_OAUTH_CLIENT_ID MICROSOFT_OAUTH_REDIRECT_URI EMAIL_PROVIDER
  EMAIL_ENABLED EMAIL_REPLY_TO INTEGRATIONS_ENABLED_PROVIDERS
  INTEGRATIONS_OAUTH_REDIRECT_URI ENCRYPTION_KEYS_SECRET_NAME
  CREDENTIAL_MASTER_KEY_SECRET_NAME DEFAULT_MODEL_PROVIDER DEFAULT_MODEL
  CONVERSATION_NAMING_PROVIDER CONVERSATION_NAMING_MODEL
  AGENT_HISTORY_SUMMARY_MODEL_PROVIDER AGENT_HISTORY_SUMMARY_MODEL
  EMBEDDINGS_PROVIDER EMBEDDINGS_MODEL EMBEDDINGS_DIMENSIONS METRICS_ENABLED
  TRUSTED_PROXY_CIDRS AUDIT_EVENTS_RETENTION_DAYS SECURITY_EVENTS_RETENTION_DAYS
  AGENT_RUN_APPROVAL_EXPIRY_DAYS API_CPU API_MEMORY WEB_CPU WEB_MEMORY JOB_CPU
  JOB_MEMORY DB_POOL_SIZE DB_POOL_MAX_OVERFLOW DB_MAINTENANCE_POOL_SIZE
  DB_MAINTENANCE_POOL_MAX_OVERFLOW WORKER_DRAIN_MAX_SECONDS WORKER_TASK_TIMEOUT_SECONDS
  WORKER_MAX_CONCURRENT_RUNS
  WORKER_MAX_RETRIES VITE_API_BASE_URL WEB_PUBLIC_ASSET_ORIGINS WEB_HTTPS_ONLY
)
for variable_name in "${required_vars[@]}"; do
  [[ -n "${!variable_name:-}" ]] || die "required variable $variable_name is unset or empty"
done

[[ "$DEPLOYMENT_ENVIRONMENT" == "staging" || "$DEPLOYMENT_ENVIRONMENT" == "production" ]] \
  || die "DEPLOYMENT_ENVIRONMENT must be staging or production"
[[ "$WORKSPACE_BUCKET_PREFIX" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] \
  || die "WORKSPACE_BUCKET_PREFIX has invalid characters"
(( ${#WORKSPACE_BUCKET_PREFIX} <= 26 )) || die "WORKSPACE_BUCKET_PREFIX must be at most 26 characters"
[[ "$WORKER_DRAIN_MAX_SECONDS" =~ ^[0-9]+$ ]] || die "WORKER_DRAIN_MAX_SECONDS must be an integer number of seconds"
[[ "$WORKER_TASK_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "WORKER_TASK_TIMEOUT_SECONDS must be an integer number of seconds (no unit suffix)"
[[ "$WORKER_MAX_CONCURRENT_RUNS" =~ ^[1-9][0-9]*$ ]] \
  || die "WORKER_MAX_CONCURRENT_RUNS must be a positive integer"
for pool_size_variable in DB_POOL_SIZE DB_MAINTENANCE_POOL_SIZE; do
  [[ "${!pool_size_variable}" =~ ^[1-9][0-9]*$ ]] \
    || die "$pool_size_variable must be a positive integer"
done
for pool_overflow_variable in DB_POOL_MAX_OVERFLOW DB_MAINTENANCE_POOL_MAX_OVERFLOW; do
  [[ "${!pool_overflow_variable}" =~ ^[0-9]+$ ]] \
    || die "$pool_overflow_variable must be a non-negative integer"
done
worker_runtime_pool_capacity=$(( DB_POOL_SIZE + DB_POOL_MAX_OVERFLOW ))
worker_maintenance_pool_capacity=$(( DB_MAINTENANCE_POOL_SIZE + DB_MAINTENANCE_POOL_MAX_OVERFLOW ))
worker_pool_limit=$(( worker_runtime_pool_capacity < worker_maintenance_pool_capacity \
  ? worker_runtime_pool_capacity - 1 \
  : worker_maintenance_pool_capacity - 1 ))
(( WORKER_MAX_CONCURRENT_RUNS <= worker_pool_limit )) \
  || die "WORKER_MAX_CONCURRENT_RUNS must not exceed the smaller runtime or maintenance database pool capacity minus one ($worker_pool_limit)"
(( WORKER_TASK_TIMEOUT_SECONDS > WORKER_DRAIN_MAX_SECONDS )) \
  || die "WORKER_TASK_TIMEOUT_SECONDS must exceed WORKER_DRAIN_MAX_SECONDS to leave shutdown headroom"

memory_to_mib() {
  local variable_name=$1
  local value=${!variable_name}
  if [[ "$value" =~ ^([0-9]+)Mi$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$value" =~ ^([0-9]+)Gi$ ]]; then
    printf '%s' "$(( BASH_REMATCH[1] * 1024 ))"
  else
    die "$variable_name must use a whole-number Mi or Gi value"
  fi
}

for memory_variable in API_MEMORY WEB_MEMORY JOB_MEMORY; do
  memory_mib=$(memory_to_mib "$memory_variable")
  (( memory_mib >= 512 )) \
    || die "$memory_variable must be at least 512Mi for the Cloud Run gen2 execution environment"
done

API_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${API_IMAGE_NAME}:${GIT_SHA}"
WEB_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${WEB_IMAGE_NAME}:${GIT_SHA}"
CLOUD_SQL_CONNECTION_NAME="${GCP_PROJECT_ID}:${GCP_REGION}:${CLOUD_SQL_INSTANCE}"
export API_IMAGE WEB_IMAGE CLOUD_SQL_CONNECTION_NAME

# Literal allowlist consumed by helpers.py render-template; expansion here would defeat the guard.
# shellcheck disable=SC2016
TEMPLATE_VARIABLES='${GCP_PROJECT_ID} ${GCP_PROJECT_NUMBER} ${GCP_REGION} ${API_IMAGE} ${WEB_IMAGE} ${CLOUD_SQL_CONNECTION_NAME} ${API_SERVICE_ACCOUNT} ${WEB_SERVICE_ACCOUNT} ${WORKER_SERVICE_ACCOUNT} ${MIGRATE_SERVICE_ACCOUNT} ${DATABASE_MAINTENANCE_URL_SECRET_ID} ${DEPLOYMENT_ENVIRONMENT} ${GCS_PUBLIC_ASSETS_BUCKET} ${GCS_WORKSPACE_BUCKET_LOCATION} ${WORKSPACE_BUCKET_PREFIX} ${PUBLIC_ASSETS_BASE_URL} ${APP_BASE_URL} ${FRONTEND_URL} ${ALLOWED_CORS_ORIGINS} ${COOKIE_DOMAIN} ${ARTIFACT_ORIGIN} ${ARTIFACT_SHARING_ENABLED} ${ALLOW_SIGNUP} ${SUPER_ADMIN_EMAILS} ${ALLOW_WORKSPACE_CREATION} ${EMAIL_AUTH_ENABLED} ${GOOGLE_OAUTH_ENABLED} ${GOOGLE_OAUTH_CLIENT_ID} ${GOOGLE_OAUTH_REDIRECT_URI} ${GITHUB_OAUTH_ENABLED} ${GITHUB_OAUTH_CLIENT_ID} ${GITHUB_OAUTH_REDIRECT_URI} ${MICROSOFT_OAUTH_ENABLED} ${MICROSOFT_OAUTH_CLIENT_ID} ${MICROSOFT_OAUTH_REDIRECT_URI} ${EMAIL_PROVIDER} ${EMAIL_ENABLED} ${EMAIL_REPLY_TO} ${INTEGRATIONS_ENABLED_PROVIDERS} ${INTEGRATIONS_OAUTH_REDIRECT_URI} ${ENCRYPTION_KEYS_SECRET_NAME} ${CREDENTIAL_MASTER_KEY_SECRET_NAME} ${DEFAULT_MODEL_PROVIDER} ${DEFAULT_MODEL} ${CONVERSATION_NAMING_PROVIDER} ${CONVERSATION_NAMING_MODEL} ${AGENT_HISTORY_SUMMARY_MODEL_PROVIDER} ${AGENT_HISTORY_SUMMARY_MODEL} ${EMBEDDINGS_PROVIDER} ${EMBEDDINGS_MODEL} ${EMBEDDINGS_DIMENSIONS} ${METRICS_ENABLED} ${TRUSTED_PROXY_CIDRS} ${AUDIT_EVENTS_RETENTION_DAYS} ${SECURITY_EVENTS_RETENTION_DAYS} ${AGENT_RUN_APPROVAL_EXPIRY_DAYS} ${API_CPU} ${API_MEMORY} ${WEB_CPU} ${WEB_MEMORY} ${JOB_CPU} ${JOB_MEMORY} ${DB_POOL_SIZE} ${DB_POOL_MAX_OVERFLOW} ${DB_MAINTENANCE_POOL_SIZE} ${DB_MAINTENANCE_POOL_MAX_OVERFLOW} ${WORKER_DRAIN_MAX_SECONDS} ${WORKER_TASK_TIMEOUT_SECONDS} ${WORKER_MAX_CONCURRENT_RUNS} ${WORKER_MAX_RETRIES} ${RUNTIME_SECRET_ENV_YAML} ${RUNTIME_SECRET_ANNOTATION} ${MIGRATE_SECRET_ENV_YAML} ${MIGRATE_SECRET_ANNOTATION}'

secret_env_yaml() {
  local indent=$1
  local bindings_csv=$2
  local binding env_name secret_id
  local result=""
  IFS=',' read -ra bindings <<< "$bindings_csv"
  for binding in "${bindings[@]}"; do
    env_name=${binding%%=*}
    secret_id=${binding#*=}
    [[ "$binding" == *=* && "$env_name" =~ ^[A-Z][A-Z0-9_]*$ ]] \
      || die "invalid RUNTIME_SECRET_BINDINGS entry: $binding"
    [[ "$secret_id" =~ ^[a-zA-Z0-9_-]{1,255}$ ]] \
      || die "invalid Secret Manager id in RUNTIME_SECRET_BINDINGS: $binding"
    result+="${indent}- name: ${env_name}"$'\n'
    result+="${indent}  valueFrom:"$'\n'
    result+="${indent}    secretKeyRef:"$'\n'
    result+="${indent}      name: ${secret_id}"$'\n'
    result+="${indent}      key: latest"$'\n'
  done
  printf '%s' "${result%$'\n'}"
}

secret_annotation() {
  local bindings_csv=$1
  local binding secret_id
  local result=""
  IFS=',' read -ra bindings <<< "$bindings_csv"
  for binding in "${bindings[@]}"; do
    secret_id=${binding#*=}
    [[ -z "$result" ]] || result+=","
    result+="${secret_id}:projects/${GCP_PROJECT_NUMBER}/secrets/${secret_id}"
  done
  printf '%s' "$result"
}

# The migrate job mounts only the secrets settings validation needs, not the
# full runtime set (LLM provider keys stay off the migrate identity).
migrate_secret_bindings() {
  local env_name binding matched
  local result=""
  IFS=',' read -ra migrate_names <<< "$MIGRATE_SECRET_ENV_NAMES"
  IFS=',' read -ra bindings <<< "$RUNTIME_SECRET_BINDINGS"
  for env_name in "${migrate_names[@]}"; do
    matched=""
    for binding in "${bindings[@]}"; do
      [[ "${binding%%=*}" == "$env_name" ]] && matched=$binding
    done
    [[ -n "$matched" ]] \
      || die "MIGRATE_SECRET_ENV_NAMES entry $env_name has no RUNTIME_SECRET_BINDINGS binding"
    [[ -z "$result" ]] || result+=","
    result+="$matched"
  done
  printf '%s' "$result"
}
MIGRATE_SECRET_BINDINGS=$(migrate_secret_bindings)

render_template() {
  local input=$1
  local output=$2
  local indent=$3
  RUNTIME_SECRET_ENV_YAML=$(secret_env_yaml "$indent" "$RUNTIME_SECRET_BINDINGS")
  RUNTIME_SECRET_ANNOTATION=$(secret_annotation "$RUNTIME_SECRET_BINDINGS")
  MIGRATE_SECRET_ENV_YAML=$(secret_env_yaml "$indent" "$MIGRATE_SECRET_BINDINGS")
  MIGRATE_SECRET_ANNOTATION=$(secret_annotation "$MIGRATE_SECRET_BINDINGS")
  export RUNTIME_SECRET_ENV_YAML RUNTIME_SECRET_ANNOTATION
  export MIGRATE_SECRET_ENV_YAML MIGRATE_SECRET_ANNOTATION
  python3 "$SCRIPT_DIR/helpers.py" render-template "$input" "$output" "$TEMPLATE_VARIABLES"
  if grep -Eq '\$\{[A-Za-z_][A-Za-z0-9_]*\}' "$output"; then
    die "unrendered template variable remains in $output"
  fi
  [[ -s "$output" ]] || die "rendered template is empty: $output"
}

command -v python3 >/dev/null 2>&1 || die "python3 is required"

cleanup_output=false
if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/praxis-gcp-render.XXXXXX")
  cleanup_output=true
fi
mkdir -p "$OUTPUT_DIR/services" "$OUTPUT_DIR/jobs"
if [[ "$cleanup_output" == true ]]; then
  trap 'rm -rf "$OUTPUT_DIR"' EXIT
fi

render_template "$SCRIPT_DIR/services/praxis-api.yaml.tmpl" "$OUTPUT_DIR/services/praxis-api.yaml" "            "
render_template "$SCRIPT_DIR/services/praxis-web.yaml.tmpl" "$OUTPUT_DIR/services/praxis-web.yaml" "            "
render_template "$SCRIPT_DIR/jobs/praxis-migrate.yaml.tmpl" "$OUTPUT_DIR/jobs/praxis-migrate.yaml" "                "
render_template "$SCRIPT_DIR/jobs/praxis-worker.yaml.tmpl" "$OUTPUT_DIR/jobs/praxis-worker.yaml" "                "

if [[ "$RENDER_ONLY" == true ]]; then
  echo "Rendered Cloud Run manifests to $OUTPUT_DIR"
  exit 0
fi

for command_name in docker gcloud; do
  command -v "$command_name" >/dev/null 2>&1 || die "$command_name is required"
done

REGISTRY_HOST="${GCP_REGION}-docker.pkg.dev"
gcloud auth configure-docker "$REGISTRY_HOST" --quiet

docker build --platform linux/amd64 --target production --build-arg CLOUD_EXTRA=gcp \
  --tag "$API_IMAGE" "$REPO_ROOT/apps/api"
docker build --platform linux/amd64 --target production \
  --build-arg VITE_API_BASE_URL="$VITE_API_BASE_URL" \
  --build-arg WEB_PUBLIC_ASSET_ORIGINS="$WEB_PUBLIC_ASSET_ORIGINS" \
  --build-arg WEB_HTTPS_ONLY="$WEB_HTTPS_ONLY" --tag "$WEB_IMAGE" "$REPO_ROOT/apps/web"
docker push "$API_IMAGE"
docker push "$WEB_IMAGE"

previous_api_revision=$(gcloud run services describe praxis-api --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet 2>/dev/null || true)
previous_web_revision=$(gcloud run services describe praxis-web --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet 2>/dev/null || true)

gcloud run services replace "$OUTPUT_DIR/services/praxis-api.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --dry-run --quiet >/dev/null
gcloud run services replace "$OUTPUT_DIR/services/praxis-web.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --dry-run --quiet >/dev/null

gcloud run jobs replace "$OUTPUT_DIR/jobs/praxis-migrate.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --quiet
gcloud run jobs execute praxis-migrate --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --wait --quiet

gcloud run services replace "$OUTPUT_DIR/services/praxis-api.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --quiet
gcloud run services replace "$OUTPUT_DIR/services/praxis-web.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --quiet
gcloud run jobs replace "$OUTPUT_DIR/jobs/praxis-worker.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --quiet

api_revision=$(gcloud run services describe praxis-api --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet)
web_revision=$(gcloud run services describe praxis-web --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet)
echo "Deployed praxis-api revision: $api_revision"
echo "Deployed praxis-web revision: $web_revision"
if [[ -n "$previous_api_revision" ]]; then
  echo "API rollback: gcloud run services update-traffic praxis-api --to-revisions=${previous_api_revision}=100 --project=${GCP_PROJECT_ID} --region=${GCP_REGION} --quiet"
fi
if [[ -n "$previous_web_revision" ]]; then
  echo "Web rollback: gcloud run services update-traffic praxis-web --to-revisions=${previous_web_revision}=100 --project=${GCP_PROJECT_ID} --region=${GCP_REGION} --quiet"
fi
