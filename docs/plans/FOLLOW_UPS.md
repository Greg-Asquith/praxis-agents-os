# Follow-Ups

Deferred work and known caveats surfaced during plan reviews. Each item notes
where it came from and what needs to happen before the affected code is trusted
in production.

## 1. GCS V4 signed URLs under Application Default Credentials

- **Source**: Plan 003 (cloud storage providers) review.
- **Where**: `apps/api/services/storage/providers/gcs.py` (`create_signed_upload`,
  `create_signed_download` via `blob.generate_signed_url`).
- **Problem**: V4 signed URL generation needs a signing credential. On Cloud
  Run/GCE with bare metadata-server ADC (no private key), signing only works if
  the runtime service account has `iam.serviceAccounts.signBlob` and the client
  falls back to the IAM SignBlob API. Without that permission,
  `generate_signed_url` raises "you need a private key to sign credentials".
- **Action before first GCS deploy**:
  - Grant the runtime service account `iam.serviceAccounts.signBlob` (e.g. the
    Service Account Token Creator role on itself), and confirm signed
    upload/download URLs generate against a real bucket.
  - Document the required IAM role alongside the bucket/CORS/CDN infra docs.
  - Optionally add a live smoke test (skipped unless GCS credentials are set)
    that exercises signed URL generation.

## 2. Tool audit list filters

- **Source**: Plan 027 (registry-driven tool catalog in the agent form).
- **Where**: `apps/api/routes/audit_events/list.py`,
  `apps/web/src/features/audit/`.
- **Problem**: Plan 027 could display tool labels and providers from
  `audit_events.tool_name` / `audit_events.tool_provider`, but the existing
  audit list route does not accept `tool_name` or `tool_provider` query
  parameters. Adding frontend filters before the backend supports them would
  create a misleading no-op control.
- **Action before first large integration-tool rollout**:
  - Add typed backend filters for `tool_name` and `tool_provider` to the audit
    list service and route.
  - Expose matching controls in the audit viewer filter bar.
  - Cover the route/service filters with the same workspace-scope expectations
    as the existing audit filters.
