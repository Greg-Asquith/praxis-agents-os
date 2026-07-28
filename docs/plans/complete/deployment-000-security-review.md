<!-- docs/plans/complete/deployment-000-security-review.md -->

# 000 — Security review: passing customer InfoSec questionnaires

Status: Complete (2026-07-28)
Written: 2026-07-28
Depends on: nothing to read this; individual tasks amend 001/002/TEMPLATE and
`000_README.md` and should land with (or before) the stage they harden.

## Goal

Customer deployments will face InfoSec questionnaires (SOC 2 / SIG / CAIQ
style) and external scans/pentests. This plan records the gaps found in a
2026-07-28 security review of the deployment plans, plus the decisions that
turn engineering choices into questionnaire answers. Each task names the plan
or file it amends. When a task is done, fold its content into the target plan
and tick it here; when a risk is accepted instead, record the acceptance
inline — an explicit written answer beats an improvised one.

What the plans already answer well (no action needed): Workload Identity
Federation with no long-lived keys, per-runtime service accounts with least
privilege, no default compute SA, Secret Manager for all secrets, non-root
images with locked dependencies, Artifact Registry scanning from day one,
roll-forward migrations with rehearsed rollback, and STOP conditions that
forbid loosening cookie/CSRF/CORS policy.

## Decisions

- **SD1 — Tenancy: dedicated GCP project per customer.** Decided 2026-07-28.
  Every customer deployment gets its own Cloud Project (own Cloud SQL
  instance, buckets, secrets, service accounts). This is the strongest
  available isolation answer and the plan structure supports it cheaply —
  scale-to-zero means an idle customer costs roughly one small Cloud SQL
  instance. Consequences to carry into 002:
  - The 002 Stage 1 project decision ("single project vs project-per-env")
    becomes project-per-env *per customer* (e.g. `praxis-<customer>-prod`);
    staging can stay a single shared internal project.
  - Customer offboarding = project deletion: a clean, provable
    data-destruction answer. Document the offboarding step (project delete +
    30-day pending-deletion window) in `deploy/gcp/README`.
  - Per-customer projects multiply the one-time Stage 1 work — the D9
    bootstrap script must be parameterized by customer/project from the
    start, not written as a one-off.
  - Questionnaire answers unlocked: tenant isolation (project boundary),
    blast radius (per-customer), encryption scope (per-project keys),
    data deletion (project deletion).

## Tasks

### High priority — before any customer deployment

- [x] **Reject known placeholder secrets outside local.**
      Previously, `core/settings/security.py` validated `SECRET_KEY` only by
      length and `ENCRYPTION_KEY` only as valid Fernet, so the public examples
      passed. Completed 2026-07-28 through Lane P launch hardening: the
      combined settings guard now rejects both example secrets and
      `SECURE_COOKIES=false` outside local.
- [x] **Add security headers to the web tier.** `apps/web/nginx.conf` serves
      the SPA with no HSTS, CSP, `X-Content-Type-Options`,
      `frame-ancestors`/`X-Frame-Options`, or `Referrer-Policy`. The API has
      `SecurityHeadersMiddleware`, but the HTML document browsers load comes
      from nginx — missing HSTS/CSP on `app.<domain>` is an automatic finding
      on any external scan. Amend: 001 Stage 2 (nginx.conf) and verify
      headers survive in the 002 Stage 2 smoke test.
- [x] **Verify client IP integrity behind Cloud Run in v1.**
      `TRUSTED_PROXY_CIDRS` currently only appears in 002's growth-path LB
      section, but the problem exists without the LB: if
      `core/rate_limiting.py` and audit/security-event logging read
      `X-Forwarded-For` naively, clients can spoof their IP (defeating
      brute-force limits, polluting audit trails); if they ignore it, every
      client looks like Google's frontend. Verify and configure for Cloud
      Run's proxy layer. Amend: 002 Stage 2.
- [x] **Set retention numbers.** Cloud Logging `_Default` bucket keeps 30
      days; questionnaires typically want 90 days–1 year for audit-relevant
      logs. Pick numbers, configure the log bucket, and decide retention for
      the in-app `audit_events`/`security_events` tables (currently
      unbounded — also a growth problem). Amend: 002 Stage 2 observability
      floor; add audit-log retention as contract capability #10 in
      `000_README.md` so every provider target inherits it.
- [x] **Enable Data Access audit logs** for Secret Manager, GCS, and Cloud
      SQL (Admin Activity is on by default; "who read the secret" is a
      standard question). Amend: 002 Stage 1.

### Medium priority — decide and record

- [x] **Backup/DR targets and a restore rehearsal.** 002 Stage 1 has
      "automated backups + PITR on for prod" but no RPO/RTO numbers, no
      rehearsed restore (rollback is rehearsed; restore deserves the same),
      no Cloud SQL deletion protection, no GCS versioning/soft-delete on the
      private bucket. Single-region + max-1-instance API means the honest
      availability answer is modest — write it down. Amend: 002 Stages 1–3.
- [x] **Secret and key rotation runbook.** D7 lists the secrets; no rotation
      cadence or procedure. Record the hard cases: rotating `SECRET_KEY`
      was initially assumed to invalidate sessions (verification found that
      persisted sessions use random hashed tokens, while signed transient and
      CSRF tokens rotate); rotating
      `ENCRYPTION_KEY`/`credential-master-key` requires re-encrypting stored
      credentials — the plural
      `CREDENTIAL_MASTER_KEYS` suggests multi-key rotation support exists;
      verify and document it. Amend: 002 D7 + `deploy/gcp/README`.
- [x] **Data residency and subprocessors.** Reframe the 002 region choice as
      a residency commitment (record region per customer under SD1). Agent
      conversations flow to LLM providers — a UK/EU customer's first
      data-flow question. The subprocessor list (providers + their regions)
      is not deployment work but the deployment plan pins the region half;
      note the dependency and where the list will live. Amend: 002 Stage 1.
- [x] **Security monitoring floor.** The 002 observability floor covers 5xx,
      uptime, and worker failures but nothing security-shaped. Add a
      log-based alert on `security_events` spikes (failed logins) and a
      one-page incident-response runbook (contact path, triage steps) so the
      "security monitoring / IR process?" answers are yes. Amend: 002
      Stage 2.

### Lower priority — accepted risks to document explicitly

- [x] **WAF/DDoS deferral (D1 growth path).** Legitimate for v1; write the
      accepted-risk line now: "edge protection is Google Front End TLS
      termination + application-level rate limiting; Cloud Armor adopted at
      [trigger]". Amend: 002 D1.
- [x] **Supply chain paragraph.** Locked deps and pinned toolchain are good.
      Gaps: base images pinned by tag not digest, no SBOM, scanning enabled
      but no patch SLA ("criticals within X days"). One paragraph in 002
      D8/Stage 3 covers it.
- [x] **Public metrics endpoint.** `/api/metrics` behind `METRICS_TOKEN` on
      a public origin is acceptable; note it and fold into the growth-path
      ingress tightening. Amend: 002 growth path.
- [x] **Public assets bucket constraints.** Stage 1 constrains the private
      bucket; mirror for the public one: uniform access, no bucket listing,
      only intended object paths public. Amend: 002 Stage 1.
- [x] **CI/CD hardening.** GitHub environment protection rules on the prod
      environment remain part of 002 Stage 3. Third-party Actions were pinned
      by SHA in Lane P on 2026-07-28 and must not be duplicated there.

## Completion record

Completed 2026-07-28 as the intended pre-execution amendment slice:

- 001 now owns an exact nginx header policy, the nginx inheritance trap, and
  container/header verification across shell, fallback, and asset paths.
- 002 carries SD1 as D11 and makes the bootstrap customer-aware. D12 fixes
  production/staging provider-log retention at 400/90 days and application
  audit/security retention at 400 days; deployment contract capability #10
  and the provider template carry the same law.
- 002 Stage 0 now owns the two provider-independent code gaps found by the
  review: audit/security sweepers and safe rotation for the single-key
  application `ENCRYPTION_KEY`. The credential-root path was verified in the
  current tree: newest-first roots, `MultiFernet`, `encryption_key_id`, and
  the audited `integrations.rotate_credential_encryption` convergence job
  already exist.
- Current client-IP handling was verified to reject forwarding headers unless
  the socket peer is in `TRUSTED_PROXY_CIDRS`. Because Google does not publish
  a stable direct-Cloud-Run socket-peer contract in the reviewed material,
  002 requires a staging chain probe, forged-header test, and an explicit
  Cloud Run chain mode if exact trusted CIDRs cannot be established. Wildcard
  proxy trust is forbidden.
- D13 fixes the customer production targets at 15-minute RPO / 4-hour RTO,
  quarterly isolated restore rehearsal, single-region/max-one-instance
  availability, and a per-customer residency/subprocessor record. D7 records
  annual root rotation, 90-day provider-credential rotation where supported,
  immediate compromise rotation, and the distinct convergence procedures.
- D1/D8/D12 and Stages 1–3 now carry the remaining decisions: explicit WAF
  deferral triggers, Data Access logs, security alerts and incident response,
  public-metrics and public-bucket constraints, digest/SBOM/7-day critical
  patch posture, and protected production CI environments.

This plan completes when those requirements are bound into the target plans;
their runtime/cloud execution and the external staging scan remain acceptance
work for 001/002, not work silently claimed by this amendment.

## Verification

Amendment gate (completed):

- Every task above is folded into its target plan and ticked, or recorded as
  an explicit accepted risk with a revisit trigger.
- Tenancy, encryption at rest/in transit, key rotation, backup/restore
  targets, retention, incident response, residency, and subprocessors each
  have a written source in 001/002/template rather than an improvised answer.

Downstream deployment gates (owned by 001/002 and not claimed here):

- External scan of a staging deployment (headers, TLS, exposed endpoints)
  comes back clean or with only documented accepted risks.
- The dry-run questionnaire attaches runtime/cloud evidence: restore timing,
  retention and Data Access read-backs, client-IP spoof test, incident
  runbook, and subprocessor record.

## STOP conditions

- STOP if any task tempts weakening `validate_runtime_provider_config`,
  cookie/CSRF/CORS policy, or lease/claim semantics — same rule as 001/002.
- STOP before adopting the full hardened network posture (LB + Cloud Armor +
  PSC) as a side effect of a task here — that is 002's growth path, taken
  as one coherent move, not piecemeal.
