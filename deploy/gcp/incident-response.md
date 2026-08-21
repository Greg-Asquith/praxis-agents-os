# GCP deployment incident response

Before production use, copy this page beside each environment's uncommitted
deployment record. Add every owner and contact path.

| Role                    | Primary | Backup | Contact path |
| ----------------------- | ------- | ------ | ------------ |
| Incident commander      |         |        |              |
| Security lead           |         |        |              |
| GCP/platform owner      |         |        |              |
| Customer decision maker |         |        |              |
| Legal/privacy contact   |         |        |              |

## Severity and first response

- **SEV-1:** active credential/data compromise, cross-workspace exposure, or
  production unavailable. Page immediately and establish an incident channel.
- **SEV-2:** material degradation, repeated worker/migration failure, or a
  contained security control failure. Engage owners within the agreed window.
- **SEV-3:** low-impact defect with no active confidentiality or availability
  impact. Track normally while preserving relevant evidence.

1. Name the incident commander, severity, start time, affected customer/project,
   and known scope of impact.
2. Preserve Cloud Logging, audit/security rows, job execution details, image
   digests, deployed revisions, IAM policy snapshots, and database backup ids.
3. Contain with the narrowest reversible action: revoke an exposed credential,
   stop traffic to a bad revision, disable a compromised integration, or pause
   a schedule. Do not delete evidence or rotate encryption roots without the
   matching convergence procedure.
4. Decide customer/regulator notification with the named privacy/legal owner;
   record the facts, decision, time, and approver.
5. Recover from a known image/backup, validate migrations and tenant isolation,
   and test authentication, chat over server-sent events (SSE), files, and
   schedules.
6. Close only after monitoring is stable, evidence is retained, customer
   commitments are met, and follow-up owners/dates are recorded.

## Triage prompts

- Is the impact isolated to one customer project, one workspace, or global?
- Did any approval, credential, session, storage, or audit boundary fail?
- Which revision/job execution first exhibited the issue?
- Are Cloud SQL point-in-time recovery (PITR) and object versions inside the
  required recovery window?
- Does rollback preserve database compatibility, or is a forward fix safer?
- Are external large language model (LLM), email, OAuth, or integration
  subprocessors involved?

## Post-incident review

Within five working days, record the timeline, root and contributing causes,
detection gaps, customer impact, evidence locations, recovery measurements,
and concrete corrective actions with owners and due dates. Update this runbook
when the contact path or deployment architecture changes.
