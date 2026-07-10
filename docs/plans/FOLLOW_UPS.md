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
- **Where**: `apps/api/routes/audit_events/list_audit_events.py`,
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

## 3. Email/Slack delivery of scheduled-run results

- **Source**: 2026-07-07 harness-engineering review (roadmap §4 Lane H notes);
  consolidated here by plan 080.
- **Where**: extends the `docs/architecture/governance.md` §6 notification
  policy; rides the existing notifications service and the 030 jobs harness.
- **What**: deliver scheduled-run results (and failures) to email/Slack
  instead of only in-app notifications. Flagged in the roadmap as likely the
  highest-ROI unplanned product feature. Becomes a numbered plan when picked
  up.

## 4. KB ingestion from integration sources

- **Source**: 2026-07-07 harness-engineering review (roadmap §4 Lane H notes);
  consolidated here by plan 080.
- **Where**: the Phase 4a × 4b intersection — Drive/Gmail (041 providers) as
  `kb.sync_source` jobs feeding the 044 ingestion pipeline.
- **What**: ingest documents from connected integration sources into the KB.
  Requires both workstreams landed; the teams executing 037–042 and 043–047
  should keep the seam in mind (source_type vocabulary, provenance, and the
  threat-model §2(g)/(h) channels already cover the content classes). Becomes
  a numbered plan when picked up.

## 5. Workspace-level LLM token budgets

- **Source**: 2026-07-07 harness-engineering review (roadmap §4 Lane H notes);
  consolidated here by plan 080.
- **Where**: `docs/architecture/governance.md` §4 quota counters already exist
  on `agent_runs` hot columns; only the quota surface is missing.
- **What**: admin-visible workspace token budgets with enforcement. Becomes a
  numbered plan when picked up.
