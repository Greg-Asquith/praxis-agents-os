<!-- docs/implementation/security.md -->

# Authentication, encryption, and audit

Read this before changing authentication, invitations, encryption rotation,
or audit persistence. Also read the
[threat model](../architecture/threat-model.md). Backend paths are relative
to `apps/api/`; frontend paths to `apps/web/`.

## Authentication and request handling

The following contracts apply in this area:

- Auth accepts the `session` cookie first, then `Authorization: Bearer`;
  internal HS256 JWTs authenticate scheduled runs and are pinned to their
  workspace.
- The active workspace resolves from the `X-Workspace` header via membership
  lookup; RBAC uses the `require_role`/`require_owner`/`require_editor`/
  `require_read` dependencies.
- CSRF is enforced when a session cookie is present (Origin check plus
  HMAC-signed `X-CSRF-Token`). Rate limiting is Postgres-backed and
  fail-closed for auth flows: general requests consume minute and hour
  budgets; login failures consume a client-IP-and-account budget while
  successful logins don't; pre-account TOTP and OAuth failures use separate
  per-flow IP buckets that don't block requests with a resolved account;
  registration and password reset remain per IP.
  Trust forwarded client IPs only from `TRUSTED_PROXY_CIDRS`. Keep Argon2
  work on the async `User` helpers so it runs outside the event loop. Do not
  widen exempt lists casually.
- OAuth login state is bound to the initiating browser with a short-lived,
  HttpOnly, host-only cookie. Keep that check at the API callback boundary.
- Workspace invitations are delivered only through the operator-shared link;
  email and in-app notification delivery are pending. A pending,
  unexpired invitation permits account creation while `ALLOW_SIGNUP=false`:
  OAuth matches a provider-verified email (Google, GitHub's verified-email
  result, or Microsoft UPN), while password registration requires the raw
  invitation token. Full OAuth sign-in auto-accepts matching invitations.
- When `ARTIFACT_ORIGIN` is set, `ArtifactHostMiddleware` partitions routes by
  host: the artifact host serves only `/artifacts/view/*` and
  `/artifacts/shared/*`, and every other host refuses those paths.
- Preserve auditability for sensitive operations. Workspace, security,
  approval, credential, notification, and schedule flows should leave enough
  context to debug later.

## Return paths

Protected-route redirects preserve a validated same-origin relative path in
the `redirect` search parameter. Login, registration, OAuth state/callback,
and post-TOTP navigation must carry that value; invalid or absolute targets
fall back to `/`. Invitation registration also derives its token only from a
validated `/invitations/accept?token=...` return path.

## Audit retention and correlation

The following contracts apply in this area:

- Append-only `audit_events` and `security_events` are retained through
  independent system jobs. Their settings default to 400 days, production
  rejects values below 400, and staging may explicitly use a shorter positive
  window such as 90 days. The sweepers delete only rows strictly older than a
  cutoff computed once per run, work in bounded batches with immediate
  continuation when capped, and record deletion counts in the completed job
  payload without emitting replacement audit events.
- Audit roll-up correlation is materialised in trigger-owned
  `audit_rollup_run_id` and `audit_rollup_tool_call_id` columns. The trigger
  derives the run ID from `details`, uses `resource_id` for tool calls and
  `details.tool_call_id` for integration-resource events, and leaves incomplete
  or unrelated identities outside the partial composite index. Writers must not
  treat those columns as inputs or weaken the `(workspace_id, run_id,
  tool_call_id)` lookup contract.

## Encryption rotation

Application encryption uses a newest-first Fernet key ring loaded from
`ENCRYPTION_KEYS` or the configured secret provider via
`ENCRYPTION_KEYS_SECRET_NAME`. API and worker startup load the ring before
serving work. Manual `security.converge_application_encryption` jobs rotate
all durable user/TOTP/OAuth ciphertext in locked batches; a check pass must
report zero stale and undecryptable values before an old key is removed, and
both modes retain their count reports in the global audit log.

## Integration audit presentation

Integration-operation audit detail parses only the canonical pending/terminal
contract. Pending intent must not imply an outcome. Terminal summaries use
one intent-count line with status badges; concrete effect counts stay in the
evidence contract and item detail instead of creating a second operator-facing
summary. Humanise machine tokens such as reason codes before display.

## Conversation audience

Private conversations remain owner-readable, including for workspace managers.
Explicit workspace sharing permits active members to read an eligible root
chat through a safe display projection. Sharing never grants execution,
approval, integration, or delegated-child access. Personal-workspace sharing
is rejected. Owner departure does not transfer ownership or remove an existing
share; membership removal prevents further reads.

Share and revoke transitions require normal authentication and CSRF protection.
They lock the conversation and use the strict audit writer in the same
transaction. Audit failure rolls back the visibility change. Routine audit
operations retain their existing best-effort behaviour. Confirmed viewer access
loss clears cached content. See the [sharing decision](../architecture/workspace-chat-sharing.md).

## Platform content audit contract

`services/audit_events/platform_content_events.py` defines strict global events
for Knowledge, Files, and Artifacts. They require a maintenance transaction and
remain hidden from workspace audit queries. The writer records actor identity,
resource identity, operation, revision IDs, and bounded changed-field names.
Optional source workspace, resource, and revision IDs stay in the restricted
event rather than the published resource response. Content, credentials, and
signed URLs are not accepted detail fields.

Lifecycle events require a configured super admin. The `publish_revision`
Artifact event additionally admits an active workspace editor for the matching
published Artifact, recording the editor as the actor. This represents a save
that immediately publishes a new version to every workspace. Audit failures
propagate so the caller's maintenance transaction rolls back. Platform Knowledge
management uses strict events for creation, updates, reprocessing, publication,
withdrawal, and deletion. Its jobs revalidate active super-admin authority and
the expected unpublished document version before saving results. Artifact
mutation APIs remain pending. Platform File management
uses this strict writer for draft confirmation, metadata edits, restoration,
publication, withdrawal, and deletion. Each event commits in the same maintenance
transaction as its mutation. Ordinary skill audit handling is unchanged.
