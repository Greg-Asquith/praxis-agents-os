#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GCP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$GCP_DIR/../.." && pwd)"
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/praxis-gcp-test.XXXXXX")
trap 'rm -rf "$TEST_TMP"' EXIT

bash -n "$GCP_DIR/bootstrap.sh" "$GCP_DIR/deploy.sh" "$SCRIPT_DIR/test.sh"

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

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$GCP_DIR/bootstrap.sh" "$GCP_DIR/deploy.sh" "$SCRIPT_DIR/test.sh"
else
  echo "shellcheck not installed; run the documented manual command before deployment"
fi
