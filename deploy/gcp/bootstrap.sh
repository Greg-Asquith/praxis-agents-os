#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: $0 ENV_FILE" >&2
}

die() {
  echo "error: $*" >&2
  exit 1
}

[[ $# -eq 1 ]] || { usage; exit 2; }
ENV_FILE=$1
[[ -f "$ENV_FILE" ]] || die "environment file not found: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required_vars=(
  GCP_PROJECT_ID GCP_PROJECT_NUMBER GCP_REGION CUSTOMER_ID DEPLOYMENT_ENVIRONMENT
  ARTIFACT_REGISTRY_REPOSITORY CLOUD_SQL_INSTANCE CLOUD_SQL_DATABASE_VERSION
  CLOUD_SQL_EDITION CLOUD_SQL_TIER CLOUD_SQL_STORAGE_SIZE CLOUD_SQL_STORAGE_TYPE CLOUD_SQL_DATABASE
  CLOUD_SQL_MAINTENANCE_USER CLOUD_SQL_RUNTIME_USER CLOUD_SQL_BACKUP_START_TIME CLOUD_SQL_DELETION_PROTECTION
  CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE GCS_PUBLIC_ASSETS_BUCKET
  WORKSPACE_BUCKET_PREFIX GCS_WORKSPACE_BUCKET_LOCATION API_SERVICE_ACCOUNT
  WEB_SERVICE_ACCOUNT WORKER_SERVICE_ACCOUNT MIGRATE_SERVICE_ACCOUNT
  SCHEDULER_JOB_NAME
  SCHEDULER_SCHEDULE SCHEDULER_TIME_ZONE LOG_RETENTION_DAYS
  ENCRYPTION_KEYS_SECRET_NAME CREDENTIAL_MASTER_KEY_SECRET_NAME
  PROVIDER_SECRET_LOGICAL_NAMES DATABASE_MAINTENANCE_URL_SECRET_ID
  RUNTIME_SECRET_BINDINGS MIGRATE_SECRET_ENV_NAMES ALLOWED_CORS_ORIGINS
)
for variable_name in "${required_vars[@]}"; do
  [[ -n "${!variable_name:-}" ]] || die "required variable $variable_name is unset or empty"
done

[[ "$DEPLOYMENT_ENVIRONMENT" == "staging" || "$DEPLOYMENT_ENVIRONMENT" == "production" ]] \
  || die "DEPLOYMENT_ENVIRONMENT must be staging or production"
[[ "$WORKSPACE_BUCKET_PREFIX" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] \
  || die "WORKSPACE_BUCKET_PREFIX has invalid characters"
(( ${#WORKSPACE_BUCKET_PREFIX} <= 26 )) || die "WORKSPACE_BUCKET_PREFIX must be at most 26 characters"
[[ "$LOG_RETENTION_DAYS" =~ ^[0-9]+$ ]] || die "LOG_RETENTION_DAYS must be an integer"
for boolean_variable in CLOUD_SQL_DELETION_PROTECTION CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE; do
  [[ "${!boolean_variable}" == "true" || "${!boolean_variable}" == "false" ]] \
    || die "$boolean_variable must be true or false"
done
if [[ "$DEPLOYMENT_ENVIRONMENT" == "production" ]]; then
  (( LOG_RETENTION_DAYS >= 400 )) || die "production LOG_RETENTION_DAYS must be at least 400"
  [[ "$CLOUD_SQL_DELETION_PROTECTION" == "true" ]] \
    || die "production requires CLOUD_SQL_DELETION_PROTECTION=true"
  [[ "$CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE" == "true" ]] \
    || die "production requires CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE=true"
fi
for required_logical_name in "$ENCRYPTION_KEYS_SECRET_NAME" "$CREDENTIAL_MASTER_KEY_SECRET_NAME"; do
  case ",${PROVIDER_SECRET_LOGICAL_NAMES}," in
    *",${required_logical_name},"*) ;;
    *) die "PROVIDER_SECRET_LOGICAL_NAMES must include $required_logical_name" ;;
  esac
done

for command_name in gcloud python3; do
  command -v "$command_name" >/dev/null 2>&1 || die "$command_name is required"
done
[[ -t 0 ]] || die "bootstrap changes APIs, IAM, and billable resources and must run interactively"

actual_project_number=$(gcloud projects describe "$GCP_PROJECT_ID" \
  --format='value(projectNumber)' --quiet)
[[ "$actual_project_number" == "$GCP_PROJECT_NUMBER" ]] \
  || die "GCP_PROJECT_NUMBER does not match project $GCP_PROJECT_ID"

cat <<EOF
This bootstrap will target exactly:
  project:     $GCP_PROJECT_ID
  region:      $GCP_REGION
  customer:    $CUSTOMER_ID
  environment: $DEPLOYMENT_ENVIRONMENT

The run enables APIs, creates or updates billable resources, changes IAM
policies, configures Data Access audit logs, and creates a Scheduler trigger.
Each section below first runs read-only existence checks, then prints the
mutation commands it will run and requires a typed yes before executing them.
Generated secret values are redacted from command previews and are never
printed or written to disk.
EOF

GCS_METRICS_ENVIRONMENT='gcs-skills gcs-skills/1.0 (skill:google-cloud-storage-basics)'

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

gcs_run() {
  printf '+ CLOUDSDK_METRICS_ENVIRONMENT=%q ' "$GCS_METRICS_ENVIRONMENT"
  printf '%q ' gcloud "$@"
  printf '\n'
  CLOUDSDK_METRICS_ENVIRONMENT="$GCS_METRICS_ENVIRONMENT" gcloud "$@"
}

# Mutations are queued per section with plan/plan_gcs, then execute_section
# prints the exact queued commands and requires an interactive yes to run them.
declare -a planned_commands=()
declare -a planned_metrics_env=()

plan() {
  planned_commands+=("$(printf '%q ' "$@")")
  planned_metrics_env+=("")
}

plan_gcs() {
  planned_commands+=("$(printf '%q ' gcloud "$@")")
  planned_metrics_env+=("$GCS_METRICS_ENVIRONMENT")
}

execute_section() {
  local title=$1
  local index section_confirmation
  if (( ${#planned_commands[@]} == 0 )); then
    echo "-- ${title}: nothing to change"
    return
  fi
  echo
  echo "== ${title} will run exactly these commands =="
  for index in "${!planned_commands[@]}"; do
    printf '  %s\n' "${planned_commands[index]}"
  done
  printf 'Type yes to authorize %s: ' "$title"
  read -r section_confirmation
  [[ "$section_confirmation" == "yes" ]] || die "authorization not granted for ${title}"
  for index in "${!planned_commands[@]}"; do
    printf '+ %s\n' "${planned_commands[index]}"
    if [[ -n "${planned_metrics_env[index]}" ]]; then
      CLOUDSDK_METRICS_ENVIRONMENT="${planned_metrics_env[index]}" \
        bash -c "${planned_commands[index]}"
    else
      bash -c "${planned_commands[index]}"
    fi
  done
  planned_commands=()
  planned_metrics_env=()
}

gcs_value() {
  CLOUDSDK_METRICS_ENVIRONMENT="$GCS_METRICS_ENVIRONMENT" gcloud "$@"
}

csv_values() {
  local input=$1
  local value
  local -a values
  IFS=',' read -ra values <<< "$input"
  for value in "${values[@]}"; do
    [[ -n "$value" ]] && printf '%s\n' "$value"
  done
}

binding_secret_id() {
  local env_name=$1
  local binding matched_secret_id=""
  while IFS= read -r binding; do
    if [[ "${binding%%=*}" == "$env_name" ]]; then
      [[ -z "$matched_secret_id" ]] || die "RUNTIME_SECRET_BINDINGS contains duplicate $env_name bindings"
      matched_secret_id=${binding#*=}
    fi
  done < <(csv_values "$RUNTIME_SECRET_BINDINGS")
  [[ -n "$matched_secret_id" ]] \
    || die "RUNTIME_SECRET_BINDINGS must include $env_name"
  printf '%s' "$matched_secret_id"
}

secret_has_enabled_version() {
  local secret_id=$1
  local version
  if ! version=$(gcloud secrets versions list "$secret_id" --project="$GCP_PROJECT_ID" \
    --filter='state=ENABLED' --format='value(name)' --limit=1 --quiet); then
    die "could not inspect Secret Manager versions for $secret_id"
  fi
  [[ -n "$version" ]]
}

confirm_sensitive_section() {
  local title=$1
  local section_confirmation
  printf 'Type yes to authorize %s: ' "$title"
  read -r section_confirmation
  [[ "$section_confirmation" == "yes" ]] || die "authorization not granted for ${title}"
}

run_sensitive() {
  local description=$1
  shift
  printf '+ %s\n' "$description"
  "$@"
}

add_secret_version() {
  local secret_id=$1
  local payload=$2
  printf '+ printf [generated secret] | gcloud secrets versions add %q --data-file=- --project=%q --quiet\n' \
    "$secret_id" "$GCP_PROJECT_ID"
  printf '%s' "$payload" | gcloud secrets versions add "$secret_id" --data-file=- \
    --project="$GCP_PROJECT_ID" --quiet
}

service_account_id() {
  local email=$1
  printf '%s' "${email%@*}"
}

database_url_secret_id=$(binding_secret_id DATABASE_URL)
maintenance_url_secret_id=$(binding_secret_id DATABASE_MAINTENANCE_URL)
secret_key_secret_id=$(binding_secret_id SECRET_KEY)
metrics_token_secret_id=$(binding_secret_id METRICS_TOKEN)
[[ "$maintenance_url_secret_id" == "$DATABASE_MAINTENANCE_URL_SECRET_ID" ]] \
  || die "DATABASE_MAINTENANCE_URL_SECRET_ID must match the DATABASE_MAINTENANCE_URL binding"

echo "Checking required APIs"
apis=(
  run.googleapis.com cloudresourcemanager.googleapis.com
  sqladmin.googleapis.com secretmanager.googleapis.com
  artifactregistry.googleapis.com cloudscheduler.googleapis.com
  iamcredentials.googleapis.com iam.googleapis.com sts.googleapis.com
  logging.googleapis.com monitoring.googleapis.com storage.googleapis.com
  containerscanning.googleapis.com
)
for api in "${apis[@]}"; do
  state=$(gcloud services list --enabled --project="$GCP_PROJECT_ID" \
    --filter="config.name=${api}" --format='value(config.name)' --limit=1 --quiet)
  if [[ "$state" != "$api" ]]; then
    plan gcloud services enable "$api" --project="$GCP_PROJECT_ID" --quiet
  fi
done
execute_section "API enablement"

echo "Checking Secret Manager resources"
secret_ids=()
while IFS= read -r logical_name; do
  secret_id=$(python3 "$SCRIPT_DIR/helpers.py" secret-id "$logical_name")
  secret_ids+=("$secret_id")
  echo "provider secret mapping: $logical_name -> $secret_id"
done < <(csv_values "$PROVIDER_SECRET_LOGICAL_NAMES")
while IFS= read -r binding; do
  [[ "$binding" == *=* ]] || die "invalid RUNTIME_SECRET_BINDINGS entry: $binding"
  secret_id=${binding#*=}
  [[ "$secret_id" =~ ^[a-zA-Z0-9_-]{1,255}$ ]] \
    || die "invalid Secret Manager id in RUNTIME_SECRET_BINDINGS: $binding"
  secret_ids+=("$secret_id")
done < <(csv_values "$RUNTIME_SECRET_BINDINGS")
unique_secret_ids=()
while IFS= read -r secret_id; do
  unique_secret_ids+=("$secret_id")
done < <(printf '%s\n' "${secret_ids[@]}" | LC_ALL=C sort -u)
secret_ids=("${unique_secret_ids[@]}")
for secret_id in "${secret_ids[@]}"; do
  if ! gcloud secrets describe "$secret_id" --project="$GCP_PROJECT_ID" \
    --format='value(name)' --quiet >/dev/null 2>&1; then
    plan gcloud secrets create "$secret_id" --project="$GCP_PROJECT_ID" \
      --replication-policy=user-managed --locations="$GCP_REGION" --quiet
  fi
done
execute_section "Secret Manager resources"

echo "Checking Artifact Registry"
if ! gcloud artifacts repositories describe "$ARTIFACT_REGISTRY_REPOSITORY" \
  --project="$GCP_PROJECT_ID" --location="$GCP_REGION" --format='value(name)' --quiet \
  >/dev/null 2>&1; then
  plan gcloud artifacts repositories create "$ARTIFACT_REGISTRY_REPOSITORY" \
    --project="$GCP_PROJECT_ID" --location="$GCP_REGION" --repository-format=docker \
    --description="Praxis deployment images" --quiet
else
  artifact_format=$(gcloud artifacts repositories describe "$ARTIFACT_REGISTRY_REPOSITORY" \
    --project="$GCP_PROJECT_ID" --location="$GCP_REGION" --format='value(format)' --quiet)
  [[ "$artifact_format" == "DOCKER" ]] \
    || die "existing Artifact Registry repository format $artifact_format is not DOCKER"
fi
execute_section "Artifact Registry"

echo "Checking Cloud SQL"
if ! gcloud sql instances describe "$CLOUD_SQL_INSTANCE" --project="$GCP_PROJECT_ID" \
  --format='value(name)' --quiet >/dev/null 2>&1; then
  sql_create=(
    gcloud sql instances create "$CLOUD_SQL_INSTANCE"
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION"
    --database-version="$CLOUD_SQL_DATABASE_VERSION" --edition="$CLOUD_SQL_EDITION"
    --tier="$CLOUD_SQL_TIER" --storage-size="$CLOUD_SQL_STORAGE_SIZE"
    --storage-type="$CLOUD_SQL_STORAGE_TYPE"
    --availability-type=zonal --assign-ip
    --backup-start-time="$CLOUD_SQL_BACKUP_START_TIME"
    --enable-point-in-time-recovery --retained-backups-count=30 --quiet
  )
  if [[ "$CLOUD_SQL_DELETION_PROTECTION" == "true" ]]; then
    sql_create+=(--deletion-protection)
  else
    sql_create+=(--no-deletion-protection)
  fi
  if [[ "$CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE" == "true" ]]; then
    sql_create+=(--retain-backups-on-delete)
  else
    sql_create+=(--no-retain-backups-on-delete)
  fi
  plan "${sql_create[@]}"
else
  actual_database_version=$(gcloud sql instances describe "$CLOUD_SQL_INSTANCE" \
    --project="$GCP_PROJECT_ID" --format='value(databaseVersion)' --quiet)
  [[ "$actual_database_version" == "$CLOUD_SQL_DATABASE_VERSION" ]] \
    || die "existing Cloud SQL version $actual_database_version does not match $CLOUD_SQL_DATABASE_VERSION"
  actual_sql_region=$(gcloud sql instances describe "$CLOUD_SQL_INSTANCE" \
    --project="$GCP_PROJECT_ID" --format='value(region)' --quiet)
  [[ "$actual_sql_region" == "$GCP_REGION" ]] \
    || die "existing Cloud SQL region $actual_sql_region does not match $GCP_REGION"
  sql_patch=(
    gcloud sql instances patch "$CLOUD_SQL_INSTANCE" --project="$GCP_PROJECT_ID"
    --tier="$CLOUD_SQL_TIER" --edition="$CLOUD_SQL_EDITION"
    --availability-type=zonal --assign-ip
    --backup-start-time="$CLOUD_SQL_BACKUP_START_TIME" --enable-point-in-time-recovery
    --retained-backups-count=30 --quiet
  )
  if [[ "$CLOUD_SQL_DELETION_PROTECTION" == "true" ]]; then
    sql_patch+=(--deletion-protection)
  else
    sql_patch+=(--no-deletion-protection)
  fi
  if [[ "$CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE" == "true" ]]; then
    sql_patch+=(--retain-backups-on-delete)
  else
    sql_patch+=(--no-retain-backups-on-delete)
  fi
  plan "${sql_patch[@]}"
fi
execute_section "Cloud SQL instance"

# The database and user checks need the instance from the section above to
# exist, so they run as their own sections rather than joining it.
if ! gcloud sql databases describe "$CLOUD_SQL_DATABASE" --instance="$CLOUD_SQL_INSTANCE" \
  --project="$GCP_PROJECT_ID" --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud sql databases create "$CLOUD_SQL_DATABASE" --instance="$CLOUD_SQL_INSTANCE" \
    --project="$GCP_PROJECT_ID" --quiet
fi
execute_section "Cloud SQL database"

maintenance_existing_user=$(gcloud sql users list --instance="$CLOUD_SQL_INSTANCE" \
  --project="$GCP_PROJECT_ID" --filter="name=${CLOUD_SQL_MAINTENANCE_USER}" \
  --format='value(name)' --limit=1 --quiet)
runtime_existing_user=$(gcloud sql users list --instance="$CLOUD_SQL_INSTANCE" \
  --project="$GCP_PROJECT_ID" --filter="name=${CLOUD_SQL_RUNTIME_USER}" \
  --format='value(name)' --limit=1 --quiet)

maintenance_credential_required=false
runtime_credential_required=false
if [[ "$maintenance_existing_user" != "$CLOUD_SQL_MAINTENANCE_USER" ]] \
  || ! secret_has_enabled_version "$maintenance_url_secret_id"; then
  maintenance_credential_required=true
fi
if [[ "$runtime_existing_user" != "$CLOUD_SQL_RUNTIME_USER" ]] \
  || ! secret_has_enabled_version "$database_url_secret_id"; then
  runtime_credential_required=true
fi

maintenance_password=""
runtime_password=""
if [[ "$maintenance_credential_required" == "true" || "$runtime_credential_required" == "true" ]]; then
  echo
  echo "== Cloud SQL user credentials will run these commands (generated passwords redacted) =="
  if [[ "$maintenance_credential_required" == "true" ]]; then
    if [[ "$maintenance_existing_user" == "$CLOUD_SQL_MAINTENANCE_USER" ]]; then
      printf '  gcloud sql users set-password %q --instance=%q --password=[generated] --project=%q --quiet\n' \
        "$CLOUD_SQL_MAINTENANCE_USER" "$CLOUD_SQL_INSTANCE" "$GCP_PROJECT_ID"
    else
      printf '  gcloud sql users create %q --instance=%q --type=BUILT_IN --password=[generated] --project=%q --quiet\n' \
        "$CLOUD_SQL_MAINTENANCE_USER" "$CLOUD_SQL_INSTANCE" "$GCP_PROJECT_ID"
    fi
  fi
  if [[ "$runtime_credential_required" == "true" ]]; then
    if [[ "$runtime_existing_user" == "$CLOUD_SQL_RUNTIME_USER" ]]; then
      printf '  gcloud sql users set-password %q --instance=%q --password=[generated] --project=%q --quiet\n' \
        "$CLOUD_SQL_RUNTIME_USER" "$CLOUD_SQL_INSTANCE" "$GCP_PROJECT_ID"
    else
      printf '  gcloud sql users create %q --instance=%q --type=BUILT_IN --password=[generated] --project=%q --quiet\n' \
        "$CLOUD_SQL_RUNTIME_USER" "$CLOUD_SQL_INSTANCE" "$GCP_PROJECT_ID"
    fi
  fi
  confirm_sensitive_section "Cloud SQL user credentials"

  if [[ "$maintenance_credential_required" == "true" ]]; then
    maintenance_password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    if [[ "$maintenance_existing_user" == "$CLOUD_SQL_MAINTENANCE_USER" ]]; then
      run_sensitive \
        "gcloud sql users set-password $CLOUD_SQL_MAINTENANCE_USER --instance=$CLOUD_SQL_INSTANCE --password=[generated] --project=$GCP_PROJECT_ID --quiet" \
        gcloud sql users set-password "$CLOUD_SQL_MAINTENANCE_USER" \
        --instance="$CLOUD_SQL_INSTANCE" --password="$maintenance_password" \
        --project="$GCP_PROJECT_ID" --quiet
    else
      run_sensitive \
        "gcloud sql users create $CLOUD_SQL_MAINTENANCE_USER --instance=$CLOUD_SQL_INSTANCE --type=BUILT_IN --password=[generated] --project=$GCP_PROJECT_ID --quiet" \
        gcloud sql users create "$CLOUD_SQL_MAINTENANCE_USER" \
        --instance="$CLOUD_SQL_INSTANCE" --type=BUILT_IN --password="$maintenance_password" \
        --project="$GCP_PROJECT_ID" --quiet
    fi
  fi
  if [[ "$runtime_credential_required" == "true" ]]; then
    runtime_password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    if [[ "$runtime_existing_user" == "$CLOUD_SQL_RUNTIME_USER" ]]; then
      run_sensitive \
        "gcloud sql users set-password $CLOUD_SQL_RUNTIME_USER --instance=$CLOUD_SQL_INSTANCE --password=[generated] --project=$GCP_PROJECT_ID --quiet" \
        gcloud sql users set-password "$CLOUD_SQL_RUNTIME_USER" \
        --instance="$CLOUD_SQL_INSTANCE" --password="$runtime_password" \
        --project="$GCP_PROJECT_ID" --quiet
    else
      run_sensitive \
        "gcloud sql users create $CLOUD_SQL_RUNTIME_USER --instance=$CLOUD_SQL_INSTANCE --type=BUILT_IN --password=[generated] --project=$GCP_PROJECT_ID --quiet" \
        gcloud sql users create "$CLOUD_SQL_RUNTIME_USER" \
        --instance="$CLOUD_SQL_INSTANCE" --type=BUILT_IN --password="$runtime_password" \
        --project="$GCP_PROJECT_ID" --quiet
    fi
  fi
else
  echo "-- Cloud SQL user credentials: nothing to change"
fi

plan gcloud sql users assign-roles "$CLOUD_SQL_RUNTIME_USER" \
  --instance="$CLOUD_SQL_INSTANCE" --type=BUILT_IN --database-roles= \
  --revoke-existing-roles --project="$GCP_PROJECT_ID" --quiet
execute_section "Cloud SQL runtime user roles"

seed_secret_key=false
seed_metrics_token=false
secret_has_enabled_version "$secret_key_secret_id" || seed_secret_key=true
secret_has_enabled_version "$metrics_token_secret_id" || seed_metrics_token=true
if [[ "$seed_secret_key" == "true" || "$seed_metrics_token" == "true" \
  || "$maintenance_credential_required" == "true" || "$runtime_credential_required" == "true" ]]; then
  echo
  echo "== Generated secret versions will run these commands (payloads redacted) =="
  if [[ "$seed_secret_key" == "true" ]]; then
    printf '  printf [generated secret] | gcloud secrets versions add %q --data-file=- --project=%q --quiet\n' \
      "$secret_key_secret_id" "$GCP_PROJECT_ID"
  fi
  if [[ "$seed_metrics_token" == "true" ]]; then
    printf '  printf [generated secret] | gcloud secrets versions add %q --data-file=- --project=%q --quiet\n' \
      "$metrics_token_secret_id" "$GCP_PROJECT_ID"
  fi
  if [[ "$runtime_credential_required" == "true" ]]; then
    printf '  printf [generated database URL] | gcloud secrets versions add %q --data-file=- --project=%q --quiet\n' \
      "$database_url_secret_id" "$GCP_PROJECT_ID"
  fi
  if [[ "$maintenance_credential_required" == "true" ]]; then
    printf '  printf [generated database URL] | gcloud secrets versions add %q --data-file=- --project=%q --quiet\n' \
      "$maintenance_url_secret_id" "$GCP_PROJECT_ID"
  fi
  confirm_sensitive_section "generated secret versions"

  if [[ "$seed_secret_key" == "true" ]]; then
    add_secret_version "$secret_key_secret_id" \
      "$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
  fi
  if [[ "$seed_metrics_token" == "true" ]]; then
    add_secret_version "$metrics_token_secret_id" \
      "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  fi
  if [[ "$runtime_credential_required" == "true" ]]; then
    printf -v runtime_database_url \
      'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s:%s:%s' \
      "$CLOUD_SQL_RUNTIME_USER" "$runtime_password" "$CLOUD_SQL_DATABASE" \
      "$GCP_PROJECT_ID" "$GCP_REGION" "$CLOUD_SQL_INSTANCE"
    add_secret_version "$database_url_secret_id" "$runtime_database_url"
    unset runtime_database_url runtime_password
  fi
  if [[ "$maintenance_credential_required" == "true" ]]; then
    printf -v maintenance_database_url \
      'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s:%s:%s' \
      "$CLOUD_SQL_MAINTENANCE_USER" "$maintenance_password" "$CLOUD_SQL_DATABASE" \
      "$GCP_PROJECT_ID" "$GCP_REGION" "$CLOUD_SQL_INSTANCE"
    add_secret_version "$maintenance_url_secret_id" "$maintenance_database_url"
    unset maintenance_database_url maintenance_password
  fi
else
  echo "-- Generated secret versions: nothing to change"
fi

echo "Checking public-assets bucket"
public_assets_cors_file=$(mktemp "${TMPDIR:-/tmp}/praxis-public-assets-cors.json.XXXXXX")
trap 'rm -f "${public_assets_cors_file:-}" "${policy_input:-}" "${policy_output:-}"' EXIT
python3 "$SCRIPT_DIR/helpers.py" storage-cors "$ALLOWED_CORS_ORIGINS" \
  "$public_assets_cors_file"
if ! gcs_value storage buckets describe "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
  --project="$GCP_PROJECT_ID" --format='value(name)' --quiet >/dev/null 2>&1; then
  plan_gcs storage buckets create "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
    --project="$GCP_PROJECT_ID" --location="$GCP_REGION" \
    --uniform-bucket-level-access --quiet
else
  actual_bucket_location=$(gcs_value storage buckets describe "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
    --project="$GCP_PROJECT_ID" --format='value(location)' --quiet)
  normalized_bucket_location=$(printf '%s' "$actual_bucket_location" | tr '[:upper:]' '[:lower:]')
  [[ "$normalized_bucket_location" == "$GCP_REGION" ]] \
    || die "existing public-assets bucket location $actual_bucket_location does not match $GCP_REGION"
fi
plan_gcs storage buckets update "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
  --project="$GCP_PROJECT_ID" --uniform-bucket-level-access \
  --cors-file="$public_assets_cors_file" --quiet
plan_gcs storage buckets add-iam-policy-binding "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
  --member=allUsers --role=roles/storage.objectViewer \
  --project="$GCP_PROJECT_ID" --quiet
execute_section "Public-assets bucket"

echo "Checking dedicated service accounts and IAM"
service_accounts=(
  "$API_SERVICE_ACCOUNT" "$WEB_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"
  "$MIGRATE_SERVICE_ACCOUNT"
)
for service_account in "${service_accounts[@]}"; do
  if ! gcloud iam service-accounts describe "$service_account" --project="$GCP_PROJECT_ID" \
    --format='value(email)' --quiet >/dev/null 2>&1; then
    account_id=$(service_account_id "$service_account")
    plan gcloud iam service-accounts create "$account_id" --project="$GCP_PROJECT_ID" \
      --display-name="$account_id" --quiet
  fi
done

echo "Checking custom least-privilege roles"
storage_permissions='storage.buckets.create,storage.buckets.get,storage.buckets.getIamPolicy,storage.buckets.setIamPolicy,storage.buckets.update,storage.objects.create,storage.objects.delete,storage.objects.get,storage.objects.list,storage.objects.update'
if gcloud iam roles describe praxisWorkspaceStorage --project="$GCP_PROJECT_ID" \
  --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud iam roles update praxisWorkspaceStorage --project="$GCP_PROJECT_ID" \
    --title="Praxis workspace storage" --description="Provision and use Praxis workspace buckets" \
    --permissions="$storage_permissions" --stage=GA --quiet
else
  plan gcloud iam roles create praxisWorkspaceStorage --project="$GCP_PROJECT_ID" \
    --title="Praxis workspace storage" --description="Provision and use Praxis workspace buckets" \
    --permissions="$storage_permissions" --stage=GA --quiet
fi
if gcloud iam roles describe praxisWorkerJobInvoker --project="$GCP_PROJECT_ID" \
  --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud iam roles update praxisWorkerJobInvoker --project="$GCP_PROJECT_ID" \
    --title="Praxis worker job invoker" --description="Execute the scheduled Praxis worker job" \
    --permissions=run.jobs.run --stage=GA --quiet
else
  plan gcloud iam roles create praxisWorkerJobInvoker --project="$GCP_PROJECT_ID" \
    --title="Praxis worker job invoker" --description="Execute the scheduled Praxis worker job" \
    --permissions=run.jobs.run --stage=GA --quiet
fi
secret_creator_permissions='secretmanager.secrets.create'
if gcloud iam roles describe praxisSecretCreator --project="$GCP_PROJECT_ID" \
  --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud iam roles update praxisSecretCreator --project="$GCP_PROJECT_ID" \
    --title="Praxis secret creator" \
    --description="Create application-managed Secret Manager resources" \
    --permissions="$secret_creator_permissions" --stage=GA --quiet
else
  plan gcloud iam roles create praxisSecretCreator --project="$GCP_PROJECT_ID" \
    --title="Praxis secret creator" \
    --description="Create application-managed Secret Manager resources" \
    --permissions="$secret_creator_permissions" --stage=GA --quiet
fi
secret_manager_permissions='secretmanager.secrets.delete,secretmanager.secrets.get,secretmanager.versions.access,secretmanager.versions.add'
if gcloud iam roles describe praxisSecretManager --project="$GCP_PROJECT_ID" \
  --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud iam roles update praxisSecretManager --project="$GCP_PROJECT_ID" \
    --title="Praxis secret manager" \
    --description="Manage application-owned Praxis secrets" \
    --permissions="$secret_manager_permissions" --stage=GA --quiet
else
  plan gcloud iam roles create praxisSecretManager --project="$GCP_PROJECT_ID" \
    --title="Praxis secret manager" \
    --description="Manage application-owned Praxis secrets" \
    --permissions="$secret_manager_permissions" --stage=GA --quiet
fi

for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT" "$MIGRATE_SERVICE_ACCOUNT"; do
  plan gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${service_account}" --role=roles/cloudsql.client \
    --condition=None --quiet
done
for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
  plan gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${service_account}" \
    --role="projects/${GCP_PROJECT_ID}/roles/praxisWorkspaceStorage" \
    --condition=None --quiet
done
secret_namespace_condition="expression=(resource.type == 'secretmanager.googleapis.com/Secret' || resource.type == 'secretmanager.googleapis.com/SecretVersion') && resource.name.startsWith('projects/${GCP_PROJECT_NUMBER}/secrets/praxis-'),title=Praxis application secret namespace,description=Manage only application-owned Praxis secrets"
for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
  plan gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${service_account}" \
    --role="projects/${GCP_PROJECT_ID}/roles/praxisSecretCreator" \
    --condition=None --quiet
  plan gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:${service_account}" \
    --role="projects/${GCP_PROJECT_ID}/roles/praxisSecretManager" \
    --condition="$secret_namespace_condition" --quiet
done
plan gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${WORKER_SERVICE_ACCOUNT}" \
  --role="projects/${GCP_PROJECT_ID}/roles/praxisWorkerJobInvoker" \
  --condition=None --quiet
plan gcloud iam service-accounts add-iam-policy-binding "$API_SERVICE_ACCOUNT" \
  --project="$GCP_PROJECT_ID" --member="serviceAccount:${API_SERVICE_ACCOUNT}" \
  --role=roles/iam.serviceAccountTokenCreator --quiet

for secret_id in "${secret_ids[@]}"; do
  for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"; do
    plan gcloud secrets add-iam-policy-binding "$secret_id" --project="$GCP_PROJECT_ID" \
      --member="serviceAccount:${service_account}" \
      --role=roles/secretmanager.secretAccessor --quiet
  done
done
# The migrate job mounts only the MIGRATE_SECRET_ENV_NAMES subset of runtime
# bindings; grant its identity accessor on exactly those physical secrets.
migrate_secret_ids=("$DATABASE_MAINTENANCE_URL_SECRET_ID")
while IFS= read -r migrate_env_name; do
  matched_secret_id=""
  while IFS= read -r binding; do
    [[ "${binding%%=*}" == "$migrate_env_name" ]] && matched_secret_id=${binding#*=}
  done < <(csv_values "$RUNTIME_SECRET_BINDINGS")
  [[ -n "$matched_secret_id" ]] \
    || die "MIGRATE_SECRET_ENV_NAMES entry $migrate_env_name has no RUNTIME_SECRET_BINDINGS binding"
  migrate_secret_ids+=("$matched_secret_id")
done < <(csv_values "$MIGRATE_SECRET_ENV_NAMES")
unique_migrate_secret_ids=()
while IFS= read -r secret_id; do
  unique_migrate_secret_ids+=("$secret_id")
done < <(printf '%s\n' "${migrate_secret_ids[@]}" | LC_ALL=C sort -u)
for secret_id in "${unique_migrate_secret_ids[@]}"; do
  plan gcloud secrets add-iam-policy-binding "$secret_id" \
    --project="$GCP_PROJECT_ID" --member="serviceAccount:${MIGRATE_SERVICE_ACCOUNT}" \
    --role=roles/secretmanager.secretAccessor --quiet
done

execute_section "Service accounts and IAM bindings"

echo "Checking the one-minute Cloud Scheduler trigger"
scheduler_uri="https://run.googleapis.com/v2/projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/jobs/praxis-worker:run"
scheduler_common_args=(
  --location="$GCP_REGION" --project="$GCP_PROJECT_ID"
  --schedule="$SCHEDULER_SCHEDULE" --time-zone="$SCHEDULER_TIME_ZONE"
  --uri="$scheduler_uri" --http-method=POST --message-body='{}'
  --oauth-service-account-email="$WORKER_SERVICE_ACCOUNT"
  --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform --quiet
)
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --location="$GCP_REGION" \
  --project="$GCP_PROJECT_ID" --format='value(name)' --quiet >/dev/null 2>&1; then
  plan gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    "${scheduler_common_args[@]}" --update-headers=Content-Type=application/json
else
  plan gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    "${scheduler_common_args[@]}" --headers=Content-Type=application/json
fi
execute_section "Cloud Scheduler trigger"

echo "Checking Cloud Logging retention and Data Access audit logs"
plan gcloud logging buckets update _Default --location=global --project="$GCP_PROJECT_ID" \
  --retention-days="$LOG_RETENTION_DAYS" --quiet
policy_input=$(mktemp "${TMPDIR:-/tmp}/praxis-policy-input.json.XXXXXX")
policy_output=$(mktemp "${TMPDIR:-/tmp}/praxis-policy-output.json.XXXXXX")
gcloud projects get-iam-policy "$GCP_PROJECT_ID" --format=json --quiet > "$policy_input"
python3 "$SCRIPT_DIR/helpers.py" privileged-members "$policy_input" \
  "${service_accounts[@]/#/serviceAccount:}" \
  || die "the service accounts printed above must not hold project Owner or Editor"
audit_configs_state=$(python3 "$SCRIPT_DIR/helpers.py" audit-policy "$policy_input" "$policy_output")
if [[ "$audit_configs_state" == "changed" ]]; then
  plan gcloud projects set-iam-policy "$GCP_PROJECT_ID" "$policy_output" --quiet
fi
execute_section "Logging retention and audit configuration"

echo "Read-back verification"
run gcloud artifacts repositories describe "$ARTIFACT_REGISTRY_REPOSITORY" \
  --project="$GCP_PROJECT_ID" --location="$GCP_REGION" \
  --format='yaml(name,format,mode)'
run gcloud sql instances describe "$CLOUD_SQL_INSTANCE" --project="$GCP_PROJECT_ID" \
  --format='yaml(name,region,databaseVersion,settings.tier,settings.backupConfiguration,settings.deletionProtectionEnabled)'
gcs_run storage buckets describe "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
  --project="$GCP_PROJECT_ID" --format='yaml(name,location,iamConfiguration,cors_config)'
gcs_run storage buckets get-iam-policy "gs://${GCS_PUBLIC_ASSETS_BUCKET}" \
  --project="$GCP_PROJECT_ID" --format='yaml(bindings)'
run gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --location="$GCP_REGION" \
  --project="$GCP_PROJECT_ID" --format='yaml(name,schedule,timeZone,httpTarget)'
run gcloud logging buckets describe _Default --location=global --project="$GCP_PROJECT_ID" \
  --format='yaml(name,retentionDays)'
run gcloud projects get-iam-policy "$GCP_PROJECT_ID" \
  --flatten='auditConfigs[]' \
  --filter='auditConfigs.service:(secretmanager.googleapis.com storage.googleapis.com cloudsql.googleapis.com)' \
  --format='yaml(auditConfigs)' --quiet

echo "Bootstrap complete. Generated database credentials and core secret versions are populated."
echo "Populate the remaining provider and application key-ring secrets with the commands in deploy/gcp/README.md, then deploy."
