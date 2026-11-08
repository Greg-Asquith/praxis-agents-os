#!/usr/bin/env bash
# deploy/gcp/deploy.sh

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
GOOGLE_VERTEX_AI=${GOOGLE_VERTEX_AI:-false}
ANTHROPIC_VERTEX_AI=${ANTHROPIC_VERTEX_AI:-false}
ARTIFACT_ALLOW_APP_DOMAIN=${ARTIFACT_ALLOW_APP_DOMAIN:-false}
VERTEX_PARTNER_MODELS_ENABLED=${VERTEX_PARTNER_MODELS_ENABLED:-false}
GOOGLE_VERTEX_LOCATION=${GOOGLE_VERTEX_LOCATION:-auto}
MEDIA_RENDERER_IMAGE_NAME=${MEDIA_RENDERER_IMAGE_NAME:-praxis-media-renderer}
MEDIA_RENDERER_SERVICE_ACCOUNT=${MEDIA_RENDERER_SERVICE_ACCOUNT:-praxis-media-renderer@${GCP_PROJECT_ID}.iam.gserviceaccount.com}
MEDIA_RENDERER_MAX_INSTANCES=${MEDIA_RENDERER_MAX_INSTANCES:-3}
MEDIA_RENDERER_CPU=${MEDIA_RENDERER_CPU:-4}
MEDIA_RENDERER_MEMORY=${MEDIA_RENDERER_MEMORY:-16Gi}
MEDIA_RENDERER_TIMEOUT_SECONDS=${MEDIA_RENDERER_TIMEOUT_SECONDS:-900}
MAX_FILE_SIZE_SOURCE_VIDEO=${MAX_FILE_SIZE_SOURCE_VIDEO:-4294967296}
MAX_FILE_SIZE_AUDIO=${MAX_FILE_SIZE_AUDIO:-104857600}
# One source-video limit for uploads (API), workers, and renderer input.
MEDIA_RENDERER_MAX_INPUT_BYTES=$MAX_FILE_SIZE_SOURCE_VIDEO
MEDIA_RENDERER_MAX_OUTPUT_BYTES=${MEDIA_RENDERER_MAX_OUTPUT_BYTES:-2147483648}
MEDIA_RENDERER_CHILD_MEMORY_BYTES=${MEDIA_RENDERER_CHILD_MEMORY_BYTES:-8589934592}
MEDIA_STAGING_URL_TTL_SECONDS=${MEDIA_STAGING_URL_TTL_SECONDS:-1800}
DATA_SCIENCE_IMAGE_NAME=${DATA_SCIENCE_IMAGE_NAME:-praxis-data-science}
DATA_SCIENCE_SERVICE_ACCOUNT=${DATA_SCIENCE_SERVICE_ACCOUNT:-praxis-data-science@${GCP_PROJECT_ID}.iam.gserviceaccount.com}
DATA_SCIENCE_MAX_INSTANCES=${DATA_SCIENCE_MAX_INSTANCES:-3}
DATA_SCIENCE_CPU=${DATA_SCIENCE_CPU:-2}
DATA_SCIENCE_MEMORY=${DATA_SCIENCE_MEMORY:-4Gi}
DATA_SCIENCE_TIMEOUT_SECONDS=${DATA_SCIENCE_TIMEOUT_SECONDS:-300}
DATA_SCIENCE_CHILD_MEMORY_BYTES=${DATA_SCIENCE_CHILD_MEMORY_BYTES:-3221225472}
FORECAST_MAX_HISTORY_POINTS=${FORECAST_MAX_HISTORY_POINTS:-10000}
FORECAST_MAX_HORIZON=${FORECAST_MAX_HORIZON:-1024}
FORECAST_MAX_COVARIATES=${FORECAST_MAX_COVARIATES:-8}
ANTHROPIC_VERTEX_LOCATION=${ANTHROPIC_VERTEX_LOCATION:-global}
set +a
VERTEX_PARTNER_MODEL_LOCATIONS_YAML=$(python3 "$SCRIPT_DIR/helpers.py" partner-locations)
export VERTEX_PARTNER_MODEL_LOCATIONS_YAML
ANTHROPIC_VERTEX_MODELS_YAML=$(python3 "$SCRIPT_DIR/helpers.py" vertex-models \
  ANTHROPIC_VERTEX_MODELS ANTHROPIC_VERTEX_AI)
VERTEX_PARTNER_MODELS_YAML=$(python3 "$SCRIPT_DIR/helpers.py" vertex-models \
  VERTEX_PARTNER_MODELS VERTEX_PARTNER_MODELS_ENABLED)
export ANTHROPIC_VERTEX_MODELS_YAML VERTEX_PARTNER_MODELS_YAML

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
  DEPLOYMENT_ENVIRONMENT GCS_PUBLIC_ASSETS_BUCKET GCS_PLATFORM_PRIVATE_BUCKET GCS_WORKSPACE_BUCKET_LOCATION
  WORKSPACE_BUCKET_PREFIX PUBLIC_ASSETS_BASE_URL APP_BASE_URL FRONTEND_URL
  ALLOWED_CORS_ORIGINS COOKIE_DOMAIN
  ARTIFACT_SHARING_ENABLED ALLOW_SIGNUP SUPER_ADMIN_EMAILS ALLOW_WORKSPACE_CREATION
  EMAIL_AUTH_ENABLED GOOGLE_OAUTH_ENABLED GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_REDIRECT_URI
  GITHUB_OAUTH_ENABLED GITHUB_OAUTH_CLIENT_ID GITHUB_OAUTH_REDIRECT_URI
  MICROSOFT_OAUTH_ENABLED MICROSOFT_OAUTH_CLIENT_ID MICROSOFT_OAUTH_REDIRECT_URI EMAIL_PROVIDER
  EMAIL_ENABLED EMAIL_REPLY_TO INTEGRATIONS_ENABLED_PROVIDERS
  INTEGRATIONS_OAUTH_REDIRECT_URI
  ENCRYPTION_KEYS_SECRET_NAME
  CREDENTIAL_MASTER_KEY_SECRET_NAME DEFAULT_MODEL_PROVIDER DEFAULT_MODEL
  GOOGLE_VERTEX_AI GOOGLE_VERTEX_LOCATION
  ANTHROPIC_VERTEX_AI ANTHROPIC_VERTEX_LOCATION ANTHROPIC_VERTEX_MODELS_YAML
  VERTEX_PARTNER_MODELS_ENABLED VERTEX_PARTNER_MODELS_YAML VERTEX_PARTNER_MODEL_LOCATIONS_YAML
  CONVERSATION_NAMING_PROVIDER CONVERSATION_NAMING_MODEL
  AGENT_HISTORY_SUMMARY_MODEL_PROVIDER AGENT_HISTORY_SUMMARY_MODEL
  KB_ANNOTATION_PROVIDER KB_ANNOTATION_MODEL
  EMBEDDINGS_PROVIDER EMBEDDINGS_MODEL EMBEDDINGS_DIMENSIONS METRICS_ENABLED
  TRUSTED_PROXY_CIDRS AUDIT_EVENTS_RETENTION_DAYS SECURITY_EVENTS_RETENTION_DAYS
  AGENT_RUN_APPROVAL_EXPIRY_DAYS AGENT_RUN_PROGRESS_REVIEW_MAX_GRANTS
  AGENT_RUN_PROGRESS_REVIEW_TIMEOUT_SECONDS AGENT_RUN_PROGRESS_REVIEW_PROVIDER
  AGENT_RUN_PROGRESS_REVIEW_MODEL AGENT_RUN_PROGRESS_REVIEW_MIN_CONFIDENCE API_CPU API_MEMORY WEB_CPU WEB_MEMORY JOB_CPU
  JOB_MEMORY DB_POOL_SIZE DB_POOL_MAX_OVERFLOW DB_MAINTENANCE_POOL_SIZE
  DB_MAINTENANCE_POOL_MAX_OVERFLOW AI_USAGE_DB_POOL_SIZE AGENT_RUN_MAX_CONCURRENT_TURNS
  WORKER_DRAIN_MAX_SECONDS WORKER_TASK_TIMEOUT_SECONDS
  WORKER_MAX_CONCURRENT_RUNS
  WORKER_MAX_RETRIES MEDIA_RENDERER_IMAGE_NAME MEDIA_RENDERER_SERVICE_ACCOUNT
  DATA_SCIENCE_IMAGE_NAME DATA_SCIENCE_SERVICE_ACCOUNT VITE_API_BASE_URL WEB_PUBLIC_ASSET_ORIGINS WEB_HTTPS_ONLY
)
for variable_name in "${required_vars[@]}"; do
  [[ -n "${!variable_name:-}" ]] || die "required variable $variable_name is unset or empty"
done

[[ "$GCS_PLATFORM_PRIVATE_BUCKET" != "$GCS_PUBLIC_ASSETS_BUCKET" ]] \
  || die "GCS_PLATFORM_PRIVATE_BUCKET must differ from GCS_PUBLIC_ASSETS_BUCKET"
[[ "$GCS_PLATFORM_PRIVATE_BUCKET" != "$WORKSPACE_BUCKET_PREFIX-"* ]] \
  || die "GCS_PLATFORM_PRIVATE_BUCKET must not use the workspace bucket prefix"

[[ "$DEPLOYMENT_ENVIRONMENT" == "staging" || "$DEPLOYMENT_ENVIRONMENT" == "production" ]] \
  || die "DEPLOYMENT_ENVIRONMENT must be staging or production"
for boolean_variable in GOOGLE_VERTEX_AI ANTHROPIC_VERTEX_AI VERTEX_PARTNER_MODELS_ENABLED \
  ARTIFACT_ALLOW_APP_DOMAIN; do
  [[ "${!boolean_variable}" == "true" || "${!boolean_variable}" == "false" ]] \
    || die "$boolean_variable must be true or false"
done
# Share links fall back to APP_BASE_URL only when the operator opts in.
ARTIFACT_ORIGIN=${ARTIFACT_ORIGIN:-}
[[ -n "$ARTIFACT_ORIGIN" || "$ARTIFACT_ALLOW_APP_DOMAIN" == "true" ]] \
  || die "ARTIFACT_ORIGIN may be empty only when ARTIFACT_ALLOW_APP_DOMAIN=true"
[[ "$WORKSPACE_BUCKET_PREFIX" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] \
  || die "WORKSPACE_BUCKET_PREFIX has invalid characters"
(( ${#WORKSPACE_BUCKET_PREFIX} <= 26 )) || die "WORKSPACE_BUCKET_PREFIX must be at most 26 characters"
[[ "$WORKER_DRAIN_MAX_SECONDS" =~ ^[0-9]+$ ]] || die "WORKER_DRAIN_MAX_SECONDS must be an integer number of seconds"
[[ "$WORKER_TASK_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "WORKER_TASK_TIMEOUT_SECONDS must be an integer number of seconds (no unit suffix)"
[[ "$WORKER_MAX_CONCURRENT_RUNS" =~ ^[1-9][0-9]*$ ]] \
  || die "WORKER_MAX_CONCURRENT_RUNS must be a positive integer"
for media_integer_variable in MEDIA_RENDERER_MAX_INSTANCES MEDIA_RENDERER_TIMEOUT_SECONDS \
  MEDIA_RENDERER_MAX_INPUT_BYTES MEDIA_RENDERER_MAX_OUTPUT_BYTES \
  MEDIA_RENDERER_CHILD_MEMORY_BYTES MEDIA_STAGING_URL_TTL_SECONDS DATA_SCIENCE_MAX_INSTANCES \
  DATA_SCIENCE_TIMEOUT_SECONDS DATA_SCIENCE_CHILD_MEMORY_BYTES; do
  [[ "${!media_integer_variable}" =~ ^[1-9][0-9]*$ ]] \
    || die "$media_integer_variable must be a positive integer"
done
# Bounds match apps/api/core/settings, so a bad value fails here rather than at API startup.
require_integer_range() {
  local variable_name=$1 minimum=$2 maximum=$3
  (( ${!variable_name} >= minimum && ${!variable_name} <= maximum )) \
    || die "$variable_name must be between $minimum and $maximum"
}
require_integer_range MEDIA_RENDERER_TIMEOUT_SECONDS 30 3000
require_integer_range MEDIA_RENDERER_MAX_OUTPUT_BYTES 1048576 5368709120
require_integer_range MEDIA_STAGING_URL_TTL_SECONDS 60 7200
require_integer_range MEDIA_RENDERER_MAX_INPUT_BYTES 1048576 21474836480
require_integer_range MAX_FILE_SIZE_AUDIO 1048576 524288000
(( MAX_FILE_SIZE_AUDIO <= MEDIA_RENDERER_MAX_INPUT_BYTES )) \
  || die "MAX_FILE_SIZE_AUDIO must be at most MEDIA_RENDERER_MAX_INPUT_BYTES so the renderer can read every audio File"
require_integer_range DATA_SCIENCE_TIMEOUT_SECONDS 30 900
for forecast_integer_variable in FORECAST_MAX_HISTORY_POINTS FORECAST_MAX_HORIZON \
  FORECAST_MAX_COVARIATES; do
  [[ "${!forecast_integer_variable}" =~ ^[0-9]+$ ]] \
    || die "$forecast_integer_variable must be a whole number"
done
require_integer_range FORECAST_MAX_HISTORY_POINTS 16 32768
require_integer_range FORECAST_MAX_HORIZON 1 1024
require_integer_range FORECAST_MAX_COVARIATES 0 8
(( MEDIA_STAGING_URL_TTL_SECONDS >= MEDIA_RENDERER_TIMEOUT_SECONDS + 60 )) \
  || die "MEDIA_STAGING_URL_TTL_SECONDS must be at least MEDIA_RENDERER_TIMEOUT_SECONDS + 60 so output uploads don't expire mid-render"
for pool_size_variable in DB_POOL_SIZE DB_MAINTENANCE_POOL_SIZE AI_USAGE_DB_POOL_SIZE \
  AGENT_RUN_MAX_CONCURRENT_TURNS; do
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
turn_pool_limit=$(( worker_runtime_pool_capacity - 4 ))
(( AGENT_RUN_MAX_CONCURRENT_TURNS <= turn_pool_limit )) \
  || die "AGENT_RUN_MAX_CONCURRENT_TURNS must not exceed the runtime database pool capacity minus four ($turn_pool_limit)"
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

for memory_variable in API_MEMORY WEB_MEMORY JOB_MEMORY MEDIA_RENDERER_MEMORY DATA_SCIENCE_MEMORY; do
  memory_mib=$(memory_to_mib "$memory_variable")
  (( memory_mib >= 512 )) \
    || die "$memory_variable must be at least 512Mi for the Cloud Run gen2 execution environment"
done
# The renderer's disk is its memory, shared by its inputs, one output, and the isolated child.
renderer_need_mib=$(( (MEDIA_RENDERER_MAX_INPUT_BYTES + MEDIA_RENDERER_MAX_OUTPUT_BYTES \
  + MEDIA_RENDERER_CHILD_MEMORY_BYTES) / 1048576 ))
(( renderer_need_mib <= $(memory_to_mib MEDIA_RENDERER_MEMORY) )) \
  || die "MEDIA_RENDERER_MEMORY must cover MAX_FILE_SIZE_SOURCE_VIDEO, MEDIA_RENDERER_MAX_OUTPUT_BYTES, and MEDIA_RENDERER_CHILD_MEMORY_BYTES (${renderer_need_mib}Mi)"
# The data science child holds PyTorch and the model; the driver needs headroom beside it.
data_science_need_mib=$(( DATA_SCIENCE_CHILD_MEMORY_BYTES / 1048576 + 512 ))
(( data_science_need_mib <= $(memory_to_mib DATA_SCIENCE_MEMORY) )) \
  || die "DATA_SCIENCE_MEMORY must cover DATA_SCIENCE_CHILD_MEMORY_BYTES plus 512Mi (${data_science_need_mib}Mi)"

API_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${API_IMAGE_NAME}:${GIT_SHA}"
WEB_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${WEB_IMAGE_NAME}:${GIT_SHA}"
MEDIA_RENDERER_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${MEDIA_RENDERER_IMAGE_NAME}:${GIT_SHA}"
DATA_SCIENCE_IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REGISTRY_REPOSITORY}/${DATA_SCIENCE_IMAGE_NAME}:${GIT_SHA}"
CLOUD_SQL_CONNECTION_NAME="${GCP_PROJECT_ID}:${GCP_REGION}:${CLOUD_SQL_INSTANCE}"
# Cloud Run gives every service the stable URL https://SERVICE-PROJECT_NUMBER.REGION.run.app,
# so the API and worker can receive it before the renderer exists.
MEDIA_RENDERER_URL="https://praxis-media-renderer-${GCP_PROJECT_NUMBER}.${GCP_REGION}.run.app"
# The request timeout leaves headroom over the longest render for upload and teardown.
MEDIA_RENDERER_REQUEST_TIMEOUT_SECONDS=$(( MEDIA_RENDERER_TIMEOUT_SECONDS + 60 ))
DATA_SCIENCE_URL="https://praxis-data-science-${GCP_PROJECT_NUMBER}.${GCP_REGION}.run.app"
DATA_SCIENCE_REQUEST_TIMEOUT_SECONDS=$(( DATA_SCIENCE_TIMEOUT_SECONDS + 60 ))
# Quoted so an empty origin renders as an empty string, which render-template would otherwise refuse.
ARTIFACT_ORIGIN_YAML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$ARTIFACT_ORIGIN")
export API_IMAGE WEB_IMAGE MEDIA_RENDERER_IMAGE CLOUD_SQL_CONNECTION_NAME MEDIA_RENDERER_URL
export ARTIFACT_ORIGIN_YAML
export MEDIA_RENDERER_REQUEST_TIMEOUT_SECONDS
export DATA_SCIENCE_IMAGE DATA_SCIENCE_URL DATA_SCIENCE_REQUEST_TIMEOUT_SECONDS

# Literal allowlist consumed by helpers.py render-template; expansion here would defeat the guard.
# shellcheck disable=SC2016
TEMPLATE_VARIABLES='${GCP_PROJECT_ID} ${GCP_PROJECT_NUMBER} ${GCP_REGION} ${API_IMAGE} ${WEB_IMAGE} ${CLOUD_SQL_CONNECTION_NAME} ${API_SERVICE_ACCOUNT} ${WEB_SERVICE_ACCOUNT} ${WORKER_SERVICE_ACCOUNT} ${MIGRATE_SERVICE_ACCOUNT} ${DATABASE_MAINTENANCE_URL_SECRET_ID} ${DEPLOYMENT_ENVIRONMENT} ${GCS_PUBLIC_ASSETS_BUCKET} ${GCS_PLATFORM_PRIVATE_BUCKET} ${GCS_WORKSPACE_BUCKET_LOCATION} ${WORKSPACE_BUCKET_PREFIX} ${PUBLIC_ASSETS_BASE_URL} ${APP_BASE_URL} ${FRONTEND_URL} ${ALLOWED_CORS_ORIGINS} ${COOKIE_DOMAIN} ${ARTIFACT_ORIGIN_YAML} ${ARTIFACT_ALLOW_APP_DOMAIN} ${ARTIFACT_SHARING_ENABLED} ${ALLOW_SIGNUP} ${SUPER_ADMIN_EMAILS} ${ALLOW_WORKSPACE_CREATION} ${EMAIL_AUTH_ENABLED} ${GOOGLE_OAUTH_ENABLED} ${GOOGLE_OAUTH_CLIENT_ID} ${GOOGLE_OAUTH_REDIRECT_URI} ${GITHUB_OAUTH_ENABLED} ${GITHUB_OAUTH_CLIENT_ID} ${GITHUB_OAUTH_REDIRECT_URI} ${MICROSOFT_OAUTH_ENABLED} ${MICROSOFT_OAUTH_CLIENT_ID} ${MICROSOFT_OAUTH_REDIRECT_URI} ${EMAIL_PROVIDER} ${EMAIL_ENABLED} ${EMAIL_REPLY_TO} ${INTEGRATIONS_ENABLED_PROVIDERS} ${INTEGRATIONS_OAUTH_REDIRECT_URI} ${MICROSOFT_GRAPH_ENV_YAML} ${ENCRYPTION_KEYS_SECRET_NAME} ${CREDENTIAL_MASTER_KEY_SECRET_NAME} ${DEFAULT_MODEL_PROVIDER} ${DEFAULT_MODEL} ${GOOGLE_VERTEX_AI} ${GOOGLE_VERTEX_LOCATION} ${CONVERSATION_NAMING_PROVIDER} ${CONVERSATION_NAMING_MODEL} ${AGENT_HISTORY_SUMMARY_MODEL_PROVIDER} ${AGENT_HISTORY_SUMMARY_MODEL} ${EMBEDDINGS_PROVIDER} ${EMBEDDINGS_MODEL} ${EMBEDDINGS_DIMENSIONS} ${METRICS_ENABLED} ${TRUSTED_PROXY_CIDRS} ${AUDIT_EVENTS_RETENTION_DAYS} ${SECURITY_EVENTS_RETENTION_DAYS} ${AGENT_RUN_APPROVAL_EXPIRY_DAYS} ${AGENT_RUN_PROGRESS_REVIEW_MAX_GRANTS} ${AGENT_RUN_PROGRESS_REVIEW_TIMEOUT_SECONDS} ${AGENT_RUN_PROGRESS_REVIEW_PROVIDER} ${AGENT_RUN_PROGRESS_REVIEW_MODEL} ${AGENT_RUN_PROGRESS_REVIEW_MIN_CONFIDENCE} ${API_CPU} ${API_MEMORY} ${WEB_CPU} ${WEB_MEMORY} ${JOB_CPU} ${JOB_MEMORY} ${DB_POOL_SIZE} ${DB_POOL_MAX_OVERFLOW} ${DB_MAINTENANCE_POOL_SIZE} ${DB_MAINTENANCE_POOL_MAX_OVERFLOW} ${WORKER_DRAIN_MAX_SECONDS} ${WORKER_TASK_TIMEOUT_SECONDS} ${WORKER_MAX_CONCURRENT_RUNS} ${WORKER_MAX_RETRIES} ${RUNTIME_SECRET_ENV_YAML} ${RUNTIME_SECRET_ANNOTATION} ${MIGRATE_SECRET_ENV_YAML} ${MIGRATE_SECRET_ANNOTATION} ${ANTHROPIC_VERTEX_AI} ${ANTHROPIC_VERTEX_LOCATION} ${ANTHROPIC_VERTEX_MODELS_YAML} ${VERTEX_PARTNER_MODELS_ENABLED} ${VERTEX_PARTNER_MODELS_YAML} ${VERTEX_PARTNER_MODEL_LOCATIONS_YAML} ${KB_ANNOTATION_PROVIDER} ${KB_ANNOTATION_MODEL} ${AI_USAGE_DB_POOL_SIZE} ${AGENT_RUN_MAX_CONCURRENT_TURNS} ${MEDIA_RENDERER_IMAGE} ${MEDIA_RENDERER_SERVICE_ACCOUNT} ${MEDIA_RENDERER_MAX_INSTANCES} ${MEDIA_RENDERER_CPU} ${MEDIA_RENDERER_MEMORY} ${MEDIA_RENDERER_TIMEOUT_SECONDS} ${MEDIA_RENDERER_REQUEST_TIMEOUT_SECONDS} ${MEDIA_RENDERER_MAX_INPUT_BYTES} ${MEDIA_RENDERER_MAX_OUTPUT_BYTES} ${MEDIA_RENDERER_CHILD_MEMORY_BYTES} ${MEDIA_STAGING_URL_TTL_SECONDS} ${MEDIA_RENDERER_URL} ${MAX_FILE_SIZE_SOURCE_VIDEO} ${MAX_FILE_SIZE_AUDIO} ${DATA_SCIENCE_IMAGE} ${DATA_SCIENCE_URL} ${DATA_SCIENCE_SERVICE_ACCOUNT} ${DATA_SCIENCE_MAX_INSTANCES} ${DATA_SCIENCE_CPU} ${DATA_SCIENCE_MEMORY} ${DATA_SCIENCE_TIMEOUT_SECONDS} ${DATA_SCIENCE_REQUEST_TIMEOUT_SECONDS} ${DATA_SCIENCE_CHILD_MEMORY_BYTES} ${FORECAST_MAX_HISTORY_POINTS} ${FORECAST_MAX_HORIZON} ${FORECAST_MAX_COVARIATES}'

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
  MICROSOFT_GRAPH_ENV_YAML=$(python3 "$SCRIPT_DIR/helpers.py" microsoft-graph-env "$indent")
  export MICROSOFT_GRAPH_ENV_YAML
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
render_template "$SCRIPT_DIR/services/praxis-media-renderer.yaml.tmpl" "$OUTPUT_DIR/services/praxis-media-renderer.yaml" "            "
render_template "$SCRIPT_DIR/services/praxis-data-science.yaml.tmpl" "$OUTPUT_DIR/services/praxis-data-science.yaml" "            "
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
docker build --platform linux/amd64 --target production \
  --build-context driver="$REPO_ROOT/apps/isolation-driver" --tag "$MEDIA_RENDERER_IMAGE" \
  "$REPO_ROOT/apps/media-renderer"
docker build --platform linux/amd64 --target production \
  --build-context driver="$REPO_ROOT/apps/isolation-driver" --tag "$DATA_SCIENCE_IMAGE" \
  "$REPO_ROOT/apps/data-science"
docker push "$API_IMAGE"
docker push "$WEB_IMAGE"
docker push "$MEDIA_RENDERER_IMAGE"
docker push "$DATA_SCIENCE_IMAGE"

previous_api_revision=$(gcloud run services describe praxis-api --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet 2>/dev/null || true)
previous_web_revision=$(gcloud run services describe praxis-web --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)' --quiet 2>/dev/null || true)

gcloud run services replace "$OUTPUT_DIR/services/praxis-api.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --dry-run --quiet >/dev/null
gcloud run services replace "$OUTPUT_DIR/services/praxis-web.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --dry-run --quiet >/dev/null
gcloud run services replace "$OUTPUT_DIR/services/praxis-media-renderer.yaml" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --dry-run --quiet >/dev/null
gcloud run services replace "$OUTPUT_DIR/services/praxis-data-science.yaml" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --dry-run --quiet >/dev/null

gcloud run jobs replace "$OUTPUT_DIR/jobs/praxis-migrate.yaml" --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --quiet
gcloud run jobs execute praxis-migrate --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --wait --quiet

# Isolated services deploy first so the API and worker never point at a missing service.
# Invoker IAM is each service's caller check: only the API and worker identities may call it.
deploy_isolated_service() {
  local service_name=$1
  local invokers expected_invokers caller_service_account
  gcloud run services replace "$OUTPUT_DIR/services/${service_name}.yaml" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --quiet
  for caller_service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
    echo "+ granting roles/run.invoker on ${service_name} to ${caller_service_account}"
    gcloud run services add-iam-policy-binding "$service_name" \
      --member="serviceAccount:${caller_service_account}" --role=roles/run.invoker \
      --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --quiet >/dev/null
  done
  # Read the policy back: any other invoker, including allUsers, stops the deploy.
  invokers=$(gcloud run services get-iam-policy "$service_name" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
    --flatten='bindings[].members' --filter='bindings.role=roles/run.invoker' \
    --format='value(bindings.members)' --quiet | LC_ALL=C sort)
  expected_invokers=$(printf '%s\n' "serviceAccount:${API_SERVICE_ACCOUNT}" \
    "serviceAccount:${WORKER_SERVICE_ACCOUNT}" | LC_ALL=C sort)
  [[ "$invokers" == "$expected_invokers" ]] \
    || die "${service_name} invokers must be exactly the API and worker accounts; found: $invokers"
}
deploy_isolated_service praxis-media-renderer
deploy_isolated_service praxis-data-science

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
echo "Deployed praxis-media-renderer at: $MEDIA_RENDERER_URL"
echo "Deployed praxis-data-science at: $DATA_SCIENCE_URL"
if [[ -n "$previous_api_revision" ]]; then
  echo "API rollback: gcloud run services update-traffic praxis-api --to-revisions=${previous_api_revision}=100 --project=${GCP_PROJECT_ID} --region=${GCP_REGION} --quiet"
fi
if [[ -n "$previous_web_revision" ]]; then
  echo "Web rollback: gcloud run services update-traffic praxis-web --to-revisions=${previous_web_revision}=100 --project=${GCP_PROJECT_ID} --region=${GCP_REGION} --quiet"
fi
