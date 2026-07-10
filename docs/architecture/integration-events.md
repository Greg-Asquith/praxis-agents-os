# Inbound Integration Events

- **Status**: living document (binds inbound provider events and event-triggered runs)
- **Written**: 2026-07-10 (plan 077)
- **Rule**: implementing plans cite the section they implement and record any
  deviation back into this note in the same PR. Defaults stay visibly marked
  `[default — confirm at review]` until an implementing plan lands and replaces
  the marker with `[implemented: plan NNN]`.
- This note reserves architecture and safety seams. It does not implement routes,
  models, provider clients, subscriptions, or run creation.

## 1. Problem and non-goals

The Phase 4a integration design is pull-first: Praxis discovers resources and
calls provider APIs, but providers cannot notify Praxis that something changed.
That leaves reactive workflows such as “triage a new email” without an honest
receipt, verification, deduplication, or unattended-run model.

Inbound events use the existing provider-package, jobs, audit, and agent-runtime
foundations. They do not create a second integration engine or policy path.

Non-goals:

- MCP transport or MCP notifications. Roadmap decision D7 remains unchanged.
- Outbound events, a general activity feed, or changes to notification policy.
- Reusing cron schedules as event subscriptions. Schedules remain
  `next_run_at`/croniter-driven.
- Provider-specific route families, queues, secret stores, or run-envelope
  policies.
- Building filters, batching, debounce windows, per-subscription envelope
  overrides, quotas, or subscription UI in the first receipt slice.

## 2. Receipt surface

All provider push traffic enters one route family:

`POST /api/v1/integrations/events/{provider_key}/{webhook_id}`

The handler resolves the enabled provider package and webhook registration from
the path, then performs only this sequence:

1. Apply the receipt rate limit.
2. Read the bounded raw request body required by the provider verifier.
3. Verify the request before parsing provider payload fields or writing any
   payload-derived log or row.
4. Insert one compact event row, enqueue `integrations.process_event`, commit,
   and return 2xx.

The route has no session dependency, bearer dependency, user resolution, or
workspace-header contract. Provider cryptographic verification is its sole
authentication mechanism. Cookies and bearer headers are ignored by the
handler. A browser request that includes a `session` cookie is still subject to
the normal CSRF middleware and should fail without a valid origin and CSRF token.

No CSRF exemption is added. `CSRFMiddleware` only enforces unsafe methods when a
`session` cookie is present (`apps/api/middleware/csrf.py`), so genuine provider
requests already pass without weakening the exemption list. Adding the webhook
prefix to that list would unnecessarily exempt browser-borne cookie requests.

Receipt uses the existing Postgres-backed rate limiter with a fail-closed
posture. Its key is bounded to provider key plus trusted source IP; it must not
include attacker-controlled webhook ids or event ids. The first implementation
adds an `integration_webhook_receipts` limit type and limit of 120 requests per
minute per provider/source-IP pair `[default — confirm at review]`. Rejected
requests, including verification failures, consume the same budget so invalid
traffic cannot become unbounded cryptographic or audit work.

## 3. Verification

Verification belongs to the provider package behind a central engine contract.
The packaging law still holds: routes and workers call a published integration
seam; core code never imports a concrete provider. When event delivery is
implemented, `IntegrationProviderPlugin` gains an optional verifier/watch seam
whose input is provider-neutral request metadata plus raw bytes and whose output
is a normalized, already-authenticated receipt. Providers with
`event_delivery="none"` expose no verifier.

The normalized verifier result contains only data needed before processing:
`connection_id`, `external_event_id`, optional `external_resource_id`,
`event_type`, `dedup_key`, and provider-safe metadata. Provider payload parsing
that is not required for authentication happens after verification.

Rules:

- Verification is fail-closed and precedes payload parsing, persistence, job
  enqueueing, and payload-bearing logs.
- HMAC signatures use constant-time comparison. The existing
  `utils/security.py::verify_hmac_signature` is the local precedent; an
  implementing provider may need a provider-specific canonical message but not
  a weaker comparison primitive.
- Signed timestamps use a five-minute acceptance window
  `[default — confirm at review]` when the provider supplies one. Schemes without
  signed timestamps rely on their token lifetime plus deduplication.
- Google Pub/Sub push verifies the Google-signed OIDC JWT, issuer, signature,
  expiry, and audience equal to the exact webhook endpoint URL. Token expiry is
  its replay window.
- Airtable verifies its payload MAC using the per-webhook MAC secret, then uses
  the webhook id plus notification cursor as its dedup identity.
- Per-webhook secrets are references through `services/secrets`, named
  `integrations/{provider_key}/{connection_id}/webhook/{webhook_id}`. Secret
  values never enter model rows, application logs, audit details, or exception
  text. This composes with the credential key-separation posture; it does not
  add another encryption mechanism.

An unverifiable request is dropped, never acknowledged as accepted, and returns
non-2xx. It records a committed security event through
`safe_record_security_event_committed` with event type
`integration_webhook_rejected`; details are limited to provider key, webhook id
fingerprint, reason code, request id, and payload digest. Raw headers, tokens,
signatures, bodies, and provider data are excluded. Rate limiting happens before
verification so rejected floods cannot create an unbounded audit-table flood.

## 4. Event persistence and deduplication

`integration_events` is a reserved core-branch table name. It is append-mostly
and uses plain `Base + UUIDMixin + TimestampMixin` rows without soft-delete
columns. The first event implementation owns the migration.

| Column                 | Contract                                                     |
| ---------------------- | ------------------------------------------------------------ |
| `provider_key`         | Enabled provider key                                         |
| `connection_id`        | FK to the verified integration connection                    |
| `external_event_id`    | Provider event/message/cursor identifier                     |
| `external_resource_id` | Nullable provider resource identifier                        |
| `event_type`           | Provider-normalized event vocabulary                         |
| `payload_digest`       | SHA-256 of the complete raw body, always stored              |
| `payload`              | Nullable bounded JSONB containing authenticated payload data |
| `dedup_key`            | Provider-verifier output with a unique index                 |
| `received_at`          | Receipt timestamp                                            |
| `status`               | `received`, `processed`, or `discarded`                      |
| `processed_at`         | Nullable terminal-processing timestamp                       |

Payload persistence is capped by `INTEGRATIONS_EVENT_PAYLOAD_MAX_BYTES`, 64 KiB
`[default — confirm at review]`. The HTTP layer also rejects bodies beyond a
separate hard receipt cap of 1 MiB `[default — confirm at review]`, preventing
unbounded reads. An authenticated body above the persistence cap stores only its
digest and normalized envelope; processing re-pulls authoritative data from the
provider. Payloads are untrusted external data even after transport
authentication and never become instructions directly.

Delivery is at least once. `dedup_key` is verifier-owned and unique:

- Pub/Sub uses the message id from the authenticated push envelope.
- Airtable uses webhook id plus notification cursor.
- The fake provider uses a deterministic synthetic event id.

Receipt uses insert-or-ignore. A duplicate returns 2xx and creates neither a
second row nor a second job. `integrations.process_event` remains idempotent under
job retry and checks the row status before effects.

Terminal event rows are retained for 30 days `[default — confirm at review]`.
Plan 039's `integrations.sweep_stale` job gains one deletion clause; receipt does
not introduce a second sweeper.

## 5. Processing pipeline

The route is thin and the job is fat. `integrations.process_event` runs on the
existing registered jobs harness with the event row as its durable subject. The
handler:

1. Locks or otherwise claims the event idempotently and exits if terminal.
2. Loads the enabled provider plugin and verified connection.
3. Pulls authoritative provider state when the notification is thin or its body
   was not persisted.
4. Normalizes resource changes and applies provider lifecycle updates through
   central integration services.
5. Matches enabled subscriptions and mints at most one run per subscription and
   dedup key.
6. Marks the event `processed`, or `discarded` with a bounded reason when the
   connection/subscription no longer applies.

Provider packages supply verification, watch/webhook management, and normalized
pull operations; central services own persistence, status transitions,
subscription matching, run creation, retries, audit, and retention. A provider
may not create agent runs directly.

## 6. Event-triggered runs

Event subscriptions are a new object, not a schedule mode. The reserved
`integration_event_subscriptions` shape maps an enabled connection, optional
resource, and event type to an agent and prompt template. The exact schema and
RBAC land with a later numbered plan. Filters, batching/debounce, and
per-subscription side-effect overrides are explicit revisit triggers.

The processor creates an `AgentRun` through the existing run-creation seam with
trigger `event`. The database CHECK, `services.agent_runs.domain` trigger set,
runtime principal literal, and every exhaustive trigger branch must grow
together in the implementing migration.

The safety law is non-negotiable: an `event` run is unattended and receives the
same side-effect posture as a scheduled run. Its server-minted envelope defaults
to `require_approval` `[default — confirm at review]`; therefore an event-triggered
run cannot execute an unapproved external write. Internal Praxis writes remain
available, and tools that always require approval remain stricter. No client or
prompt field can widen the envelope. There is no event-specific policy setting
in v1 `[default — confirm at review]`; any future divergence requires a product
decision and its own plan.

## 7. Provider posture

| Provider   | Manifest `event_delivery`                                             | Verification and lifecycle                                                                                | First implementation posture                                                       |
| ---------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Gmail      | `pubsub_push`                                                         | Google Pub/Sub OIDC push; `users.watch`; watches renew before their roughly seven-day expiry              | First reactive-email provider after the receipt spine                              |
| Airtable   | `webhook`                                                             | Per-webhook MAC secret; notification cursor dedup; pull payloads endpoint; refresh expiring webhook state | First full receipt slice because it exercises verify/persist/dedup/process cheaply |
| Google Ads | `none`                                                                | Google Ads has no push surface                                                                            | Poll-only; do not create a webhook placeholder                                     |
| Fake       | `none` in plan 037; synthetic event support in the event test package | Deterministic signature and event id, local/test only                                                     | Exercises rejection, duplicate, retry, and event-run envelope tests                |

Gmail watch renewal and Airtable webhook refresh ride registered job kinds, not
API-process timers. Gmail renewal runs daily `[default — confirm at review]`,
matching Google's current recommendation while remaining inside the seven-day
maximum. Airtable refresh follows the provider-reported expiry with a 24-hour
safety margin where supported `[default — confirm at review]`. Failures use the
existing connection status and notification policy rather than a
provider-specific alert path.

Provider facts were re-verified on 2026-07-10 against the official
[Gmail push guide](https://developers.google.com/workspace/gmail/api/guides/push),
[Pub/Sub authenticated-push guide](https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions),
and [Airtable Webhooks overview](https://support.airtable.com/docs/airtable-webhooks-api-overview).
Re-check them when the implementing provider plan starts; the manifest's
`google_ads="none"` value remains the explicit product posture until an official
Google Ads push surface is documented.

## 8. Rollout order and revisit triggers

Rollout order:

1. Plan 079: central receipt spine plus Airtable webhooks — route,
   verification contract, persistence/dedup, processing job, security audit,
   retention, and synthetic-provider coverage.
2. Gmail `users.watch` + Pub/Sub verification, renewal, and reactive-email
   subscription path.
3. Subscription management routes and UI after the trigger contract has proven
   safe operationally.

Revisit only with observed need:

- Per-workspace event quotas and admin visibility after receipt volume is known.
- Filters, coalescing, batching, and debounce after duplicate/noisy-provider data
  exists.
- Subscription UI beyond the smallest agent + prompt-template flow.
- Per-subscription envelope overrides only with an explicit permission model and
  audit design.
- External provider wheels only through the integration-packaging entry-point
  seam; event support does not justify a second plugin system.
- A dead-letter/replay operator surface after retry exhaustion data shows the
  required controls and retention period.
