#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GCP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$GCP_DIR/../.." && pwd)"
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/praxis-gcp-test.XXXXXX")
trap 'rm -rf "$TEST_TMP"' EXIT

bash -n "$GCP_DIR/bootstrap.sh" "$GCP_DIR/deploy.sh" "$SCRIPT_DIR/test.sh"
if grep -Eq 'declare[[:space:]]+-A' "$GCP_DIR/bootstrap.sh"; then
  echo "bootstrap must remain compatible with macOS Bash 3.2" >&2
  exit 1
fi

if grep -R -E -i \
  'workload.identity|WIF_POOL|WIF_PROVIDER|GITHUB_ALLOWED|DEPLOY_SERVICE_ACCOUNT' \
  "$GCP_DIR/bootstrap.sh" "$GCP_DIR/.env.example" "$GCP_DIR/README.md"; then
  echo "GCP deployment must remain operator-driven without GitHub Actions WIF" >&2
  exit 1
fi

# Cloud Run replacement resolves project resources through Cloud Resource
# Manager, so bootstrap must enable it before the first deployment.
grep -Fq -- 'cloudresourcemanager.googleapis.com' "$GCP_DIR/bootstrap.sh"

# Workspace bucket hardening changes IAM-governed settings such as Public
# Access Prevention. The runtime storage role therefore needs both sides of
# bucket IAM policy access in addition to bucket metadata updates.
grep -Fq -- 'storage.buckets.getIamPolicy' "$GCP_DIR/bootstrap.sh"
grep -Fq -- 'storage.buckets.setIamPolicy' "$GCP_DIR/bootstrap.sh"
grep -Fq -- '--role=roles/iam.serviceAccountTokenCreator' "$GCP_DIR/bootstrap.sh"
grep -Fq -- 'helpers.py" storage-cors "$ALLOWED_CORS_ORIGINS"' "$GCP_DIR/bootstrap.sh"
grep -Fq -- '--cors-file="$public_assets_cors_file"' "$GCP_DIR/bootstrap.sh"
if grep -Fq -- '"origin": ["*"]' "$GCP_DIR/bootstrap.sh"; then
  echo "public-assets bucket CORS must not allow wildcard origins" >&2
  exit 1
fi

# PostgreSQL built-in users require a password at creation time. Keep generated
# credentials redacted from previews and ensure the matching database URLs are
# written directly to Secret Manager rather than left as a manual runbook step.
grep -Fq -- '--type=BUILT_IN --password="$maintenance_password"' "$GCP_DIR/bootstrap.sh"
grep -Fq -- '--type=BUILT_IN --password="$runtime_password"' "$GCP_DIR/bootstrap.sh"
grep -Fq -- "'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s:%s:%s'" \
  "$GCP_DIR/bootstrap.sh"
grep -Fq -- 'add_secret_version "$database_url_secret_id" "$runtime_database_url"' \
  "$GCP_DIR/bootstrap.sh"
grep -Fq -- 'add_secret_version "$maintenance_url_secret_id" "$maintenance_database_url"' \
  "$GCP_DIR/bootstrap.sh"
if grep -Fq -- '--password="$ADMIN_PW"' "$GCP_DIR/README.md"; then
  echo "database credential generation must not remain a manual runbook step" >&2
  exit 1
fi
if grep -Fq -- 'from cryptography.fernet import Fernet' "$GCP_DIR/README.md"; then
  echo "GCP bootstrap follow-up commands must not require the API virtualenv" >&2
  exit 1
fi
grep -Fq -- 'base64.urlsafe_b64encode(secrets.token_bytes(32))' "$GCP_DIR/README.md"

cd "$REPO_ROOT/apps/api"
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN="$REPO_ROOT/apps/api/.venv/bin/python"
  "$PYTHON_BIN" "$SCRIPT_DIR/test_helpers.py"
else
  UV_CACHE_DIR="$TEST_TMP/uv-cache" uv run python "$SCRIPT_DIR/test_helpers.py"
  PYTHON_BIN="uv run python"
fi
cd "$REPO_ROOT"

"$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/rendered" "$GCP_DIR/.env.example" abcdef0123456789
test -s "$TEST_TMP/rendered/services/praxis-api.yaml"
test -s "$TEST_TMP/rendered/services/praxis-web.yaml"
test -s "$TEST_TMP/rendered/jobs/praxis-migrate.yaml"
test -s "$TEST_TMP/rendered/jobs/praxis-worker.yaml"
if grep -R -E '\$\{[A-Za-z_][A-Za-z0-9_]*\}' "$TEST_TMP/rendered"; then
  echo "rendered manifest contains an unexpanded variable" >&2
  exit 1
fi
if [[ "$PYTHON_BIN" == "uv run python" ]]; then
  (cd "$REPO_ROOT/apps/api" && UV_CACHE_DIR="$TEST_TMP/uv-cache" uv run python \
    "$SCRIPT_DIR/validate_manifests.py" "$TEST_TMP/rendered")
else
  "$PYTHON_BIN" "$SCRIPT_DIR/validate_manifests.py" "$TEST_TMP/rendered"
fi
grep -q 'autoscaling.knative.dev/maxScale: "1"' "$TEST_TMP/rendered/services/praxis-api.yaml"
grep -q 'run.googleapis.com/cpu-throttling: "false"' "$TEST_TMP/rendered/services/praxis-api.yaml"
grep -q 'path: /healthz' "$TEST_TMP/rendered/services/praxis-api.yaml"
if grep -q '/readyz' "$TEST_TMP/rendered/services/praxis-api.yaml"; then
  echo "API lifecycle probes must not use /readyz" >&2
  exit 1
fi
grep -q 'value: drain' "$TEST_TMP/rendered/jobs/praxis-worker.yaml"
for manifest in \
  "$TEST_TMP/rendered/services/praxis-api.yaml" \
  "$TEST_TMP/rendered/jobs/praxis-worker.yaml"; do
  grep -A1 'name: GOOGLE_VERTEX_AI' "$manifest" | grep -q 'value: "false"'
  grep -A1 'name: GOOGLE_VERTEX_LOCATION' "$manifest" | grep -q 'value: auto'
done
grep -Fq -- 'apis+=(aiplatform.googleapis.com)' "$GCP_DIR/bootstrap.sh"
grep -Fq -- '--role=roles/aiplatform.user' "$GCP_DIR/bootstrap.sh"
test "$(grep -Fc -- '--role=roles/aiplatform.user' "$GCP_DIR/bootstrap.sh")" -eq 1
grep -B3 -F -- '--role=roles/aiplatform.user' "$GCP_DIR/bootstrap.sh" \
  | grep -Fq 'for service_account in "$API_SERVICE_ACCOUNT" "$WORKER_SERVICE_ACCOUNT"'
grep -A1 'name: WORKER_MAX_CONCURRENT_RUNS' "$TEST_TMP/rendered/jobs/praxis-worker.yaml" \
  | grep -q 'value: "2"'
grep -A1 'name: DB_MAINTENANCE_POOL_SIZE' "$TEST_TMP/rendered/jobs/praxis-worker.yaml" \
  | grep -q 'value: "1"'
grep -A1 'name: DB_MAINTENANCE_POOL_MAX_OVERFLOW' "$TEST_TMP/rendered/jobs/praxis-worker.yaml" \
  | grep -q 'value: "2"'
# The API validates worker concurrency against the same pool sizes, so it
# must receive every pool value the worker receives.
for env_name in DB_POOL_SIZE DB_POOL_MAX_OVERFLOW DB_MAINTENANCE_POOL_SIZE \
  DB_MAINTENANCE_POOL_MAX_OVERFLOW AI_USAGE_DB_POOL_SIZE AGENT_RUN_MAX_CONCURRENT_TURNS \
  WORKER_MAX_CONCURRENT_RUNS; do
  grep -q "name: ${env_name}$" "$TEST_TMP/rendered/services/praxis-api.yaml"
done
grep -A1 'name: AGENT_RUN_MAX_CONCURRENT_TURNS' "$TEST_TMP/rendered/services/praxis-api.yaml" \
  | grep -q 'value: "3"'
grep -q 'maxRetries: 0' "$TEST_TMP/rendered/jobs/praxis-worker.yaml"
if grep -R -q --exclude='test.sh' 'PUBLIC_ASSET_PREFIX\|/assets$' "$GCP_DIR"; then
  echo "deployment helpers must preserve the application's existing public object keys" >&2
  exit 1
fi

sed '/^GCP_PROJECT_ID=/d' "$GCP_DIR/.env.example" > "$TEST_TMP/missing.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/missing-render" "$TEST_TMP/missing.env" abcdef0123456789 \
  >"$TEST_TMP/missing.out" 2>&1; then
  echo "render unexpectedly succeeded with GCP_PROJECT_ID missing" >&2
  exit 1
fi
grep -q 'required variable GCP_PROJECT_ID is unset or empty' "$TEST_TMP/missing.out"

sed 's/^WEB_MEMORY=512Mi$/WEB_MEMORY=256Mi/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/undersized-web.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/undersized-web-render" \
  "$TEST_TMP/undersized-web.env" abcdef0123456789 \
  >"$TEST_TMP/undersized-web.out" 2>&1; then
  echo "render unexpectedly accepted unsupported Cloud Run gen2 memory" >&2
  exit 1
fi
grep -q 'WEB_MEMORY must be at least 512Mi' "$TEST_TMP/undersized-web.out"

sed 's/^WORKER_MAX_CONCURRENT_RUNS=2$/WORKER_MAX_CONCURRENT_RUNS=0/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/invalid-worker-concurrency.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/invalid-worker-concurrency-render" \
  "$TEST_TMP/invalid-worker-concurrency.env" abcdef0123456789 \
  >"$TEST_TMP/invalid-worker-concurrency.out" 2>&1; then
  echo "render unexpectedly accepted zero worker concurrency" >&2
  exit 1
fi
grep -q 'WORKER_MAX_CONCURRENT_RUNS must be a positive integer' \
  "$TEST_TMP/invalid-worker-concurrency.out"

sed 's/^GOOGLE_VERTEX_AI=false$/GOOGLE_VERTEX_AI=enabled/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/invalid-vertex-flag.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/invalid-vertex-flag-render" \
  "$TEST_TMP/invalid-vertex-flag.env" abcdef0123456789 \
  >"$TEST_TMP/invalid-vertex-flag.out" 2>&1; then
  echo "render unexpectedly accepted an invalid Vertex AI flag" >&2
  exit 1
fi
grep -q 'GOOGLE_VERTEX_AI must be true or false' "$TEST_TMP/invalid-vertex-flag.out"

sed -e 's/^GOOGLE_VERTEX_AI=false$/GOOGLE_VERTEX_AI=true/' \
  -e 's/^GOOGLE_VERTEX_LOCATION=auto$/GOOGLE_VERTEX_LOCATION=europe-west2/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/vertex.env"
"$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/vertex-render" \
  "$TEST_TMP/vertex.env" abcdef0123456789
for manifest in \
  "$TEST_TMP/vertex-render/services/praxis-api.yaml" \
  "$TEST_TMP/vertex-render/jobs/praxis-worker.yaml"; do
  grep -A1 'name: GOOGLE_VERTEX_AI' "$manifest" | grep -q 'value: "true"'
  grep -A1 'name: GOOGLE_VERTEX_LOCATION' "$manifest" | grep -q 'value: europe-west2'
done

sed -e '/^GOOGLE_VERTEX_AI=/d' -e '/^GOOGLE_VERTEX_LOCATION=/d' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/legacy.env"
GOOGLE_VERTEX_AI=true GOOGLE_VERTEX_LOCATION=us-central1 \
  "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/legacy-render" \
  "$TEST_TMP/legacy.env" abcdef0123456789
for manifest in \
  "$TEST_TMP/legacy-render/services/praxis-api.yaml" \
  "$TEST_TMP/legacy-render/jobs/praxis-worker.yaml"; do
  grep -A1 'name: GOOGLE_VERTEX_AI' "$manifest" | grep -q 'value: "false"'
  grep -A1 'name: GOOGLE_VERTEX_LOCATION' "$manifest" | grep -q 'value: auto'
done
grep -Fq 'unset GOOGLE_VERTEX_AI GOOGLE_VERTEX_LOCATION' "$GCP_DIR/bootstrap.sh"

sed 's/^WORKER_MAX_CONCURRENT_RUNS=2$/WORKER_MAX_CONCURRENT_RUNS=3/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/oversized-worker-concurrency.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/oversized-worker-concurrency-render" \
  "$TEST_TMP/oversized-worker-concurrency.env" abcdef0123456789 \
  >"$TEST_TMP/oversized-worker-concurrency.out" 2>&1; then
  echo "render unexpectedly accepted worker concurrency without pool headroom" >&2
  exit 1
fi
grep -q 'WORKER_MAX_CONCURRENT_RUNS must not exceed the smaller runtime or maintenance database pool capacity minus one (2)' \
  "$TEST_TMP/oversized-worker-concurrency.out"

sed 's/^AGENT_RUN_MAX_CONCURRENT_TURNS=3$/AGENT_RUN_MAX_CONCURRENT_TURNS=4/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/oversized-turns.env"
if "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/oversized-turns-render" \
  "$TEST_TMP/oversized-turns.env" abcdef0123456789 \
  >"$TEST_TMP/oversized-turns.out" 2>&1; then
  echo "render unexpectedly accepted turn concurrency without pool headroom" >&2
  exit 1
fi
grep -q 'AGENT_RUN_MAX_CONCURRENT_TURNS must not exceed the runtime database pool capacity minus four (3)' \
  "$TEST_TMP/oversized-turns.out"

sed -e 's/^DEPLOYMENT_ENVIRONMENT=staging$/DEPLOYMENT_ENVIRONMENT=production/' \
  -e 's/^LOG_RETENTION_DAYS=90$/LOG_RETENTION_DAYS=400/' \
  -e 's/^CLOUD_SQL_DELETION_PROTECTION=false$/CLOUD_SQL_DELETION_PROTECTION=true/' \
  "$GCP_DIR/.env.example" > "$TEST_TMP/unsafe-production.env"
if "$GCP_DIR/bootstrap.sh" "$TEST_TMP/unsafe-production.env" \
  >"$TEST_TMP/unsafe-production.out" 2>&1; then
  echo "bootstrap unexpectedly accepted production without retained backups" >&2
  exit 1
fi
grep -q 'production requires CLOUD_SQL_RETAIN_BACKUPS_ON_DELETE=true' \
  "$TEST_TMP/unsafe-production.out"

for flag in ANTHROPIC_VERTEX_AI VERTEX_PARTNER_MODELS_ENABLED; do
  sed "s/^${flag}=false$/${flag}=true/" "$GCP_DIR/.env.example" > "$TEST_TMP/partner.env"
  "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/partner-render" \
    "$TEST_TMP/partner.env" abcdef0123456789
  for manifest in "$TEST_TMP/partner-render/services/praxis-api.yaml" \
    "$TEST_TMP/partner-render/jobs/praxis-worker.yaml"; do
    grep -A1 'name: GOOGLE_VERTEX_AI' "$manifest" | grep -q 'value: "false"'
    grep -A1 "name: $flag" "$manifest" | grep -q 'value: "true"'
    grep -A1 'name: ANTHROPIC_VERTEX_LOCATION' "$manifest" | grep -q 'value: "global"'
    grep -A1 'name: VERTEX_PARTNER_MODEL_LOCATIONS' "$manifest" | grep -q 'value: "{}"'
  done
  sed "s/^${flag}=false$/${flag}=invalid/" "$GCP_DIR/.env.example" > "$TEST_TMP/invalid-partner.env"
  for script in deploy bootstrap; do
    if (
      if [[ "$script" == deploy ]]; then
        "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/invalid-partner-render" \
          "$TEST_TMP/invalid-partner.env"
      else
        "$GCP_DIR/bootstrap.sh" "$TEST_TMP/invalid-partner.env"
      fi
    ) >"$TEST_TMP/invalid-partner.out" 2>&1; then
      echo "$script unexpectedly accepted an invalid $flag" >&2
      exit 1
    fi
    grep -q "$flag must be true or false" "$TEST_TMP/invalid-partner.out"
  done
done

python3 - "$GCP_DIR/bootstrap.sh" <<'PYTEST'
import itertools
import pathlib
import re
import subprocess
import sys

source = pathlib.Path(sys.argv[1]).read_text()
blocks = re.findall(r'if \[\[ "\$GOOGLE_VERTEX_AI".*?\nfi', source, re.S)
assert len(blocks) == 2
for google, anthropic, partner in itertools.product(("false", "true"), repeat=3):
    setup = (
        f"GOOGLE_VERTEX_AI={google}\nANTHROPIC_VERTEX_AI={anthropic}\n"
        f"VERTEX_PARTNER_MODELS_ENABLED={partner}\n"
        "apis=()\nAPI_SERVICE_ACCOUNT=api\nWORKER_SERVICE_ACCOUNT=worker\n"
        "GCP_PROJECT_ID=test-project\nplan() { echo \"$*\"; }\n"
    )
    result = subprocess.run(
        ["bash", "-c", setup + "\n".join(blocks) + '\nprintf "%s" "${apis[*]}"'],
        check=True, capture_output=True, text=True,
    ).stdout
    enabled = "true" in (google, anthropic, partner)
    assert ("aiplatform.googleapis.com" in result) == enabled
    assert result.count("--role=roles/aiplatform.user") == (2 if enabled else 0)
PYTEST

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$GCP_DIR/bootstrap.sh" "$GCP_DIR/deploy.sh" "$SCRIPT_DIR/test.sh"
else
  echo "shellcheck not installed; run the documented manual command before deployment"
fi

# Override JSON must survive both runtime manifests as the same string value.
cp "$GCP_DIR/.env.example" "$TEST_TMP/model-locations.env"
cat >> "$TEST_TMP/model-locations.env" <<'ENV'
VERTEX_PARTNER_MODEL_LOCATIONS='{"mistral:mistral-small-2503":"europe-west4"}'
ENV
"$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/model-locations-render" \
  "$TEST_TMP/model-locations.env" abcdef0123456789
python3 - "$TEST_TMP/model-locations-render" <<'PY'
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
for name in ("services/praxis-api.yaml", "jobs/praxis-worker.yaml"):
    text = (root / name).read_text()
    scalar = text.split("name: VERTEX_PARTNER_MODEL_LOCATIONS\n", 1)[1].splitlines()[0].strip().removeprefix("value: ")
    assert json.loads(json.loads(scalar)) == {"mistral:mistral-small-2503": "europe-west4"}
    assert "name: VERTEX_PARTNER_LOCATION\n" not in text
PY
for invalid in 'VERTEX_PARTNER_MODEL_LOCATIONS=broken' \
  "VERTEX_PARTNER_MODEL_LOCATIONS='[]'" \
  "VERTEX_PARTNER_MODEL_LOCATIONS='{\"mistral:mistral-small-2503\":2}'" \
  'VERTEX_PARTNER_LOCATION=us-central1'; do
  cp "$GCP_DIR/.env.example" "$TEST_TMP/invalid-location.env"
  printf '\n%s\n' "$invalid" >> "$TEST_TMP/invalid-location.env"
  for script in deploy bootstrap; do
    if (
      if [[ "$script" == deploy ]]; then
        "$GCP_DIR/deploy.sh" --render-only "$TEST_TMP/invalid-location-render" "$TEST_TMP/invalid-location.env"
      else
        "$GCP_DIR/bootstrap.sh" "$TEST_TMP/invalid-location.env"
      fi
    ) > "$TEST_TMP/invalid-location.out" 2>&1; then
      echo "$script unexpectedly accepted invalid model locations" >&2
      exit 1
    fi
    grep -q 'VERTEX_PARTNER_' "$TEST_TMP/invalid-location.out"
  done
done
