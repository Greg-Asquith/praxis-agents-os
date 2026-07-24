# Plan 079: Inbound event receipt spine + Airtable webhooks

> **Executor instructions**: Read this plan fully before changing code. This is
> the first implementation of `docs/architecture/integration-events.md`; record
> any provider-fact deviation back into that living note in the same change.
> Keep the receipt route verification-first, keep webhook secrets behind
> `services/secrets`, and do not add a CSRF exemption. Update the roadmap/status
> docs and move this plan to `docs/plans/complete/` only after every done
> criterion passes.
>
> **Drift check (run first)**:
> `git status --porcelain`, `git log -1 --oneline`,
> `rg -n "event_delivery|IntegrationProviderPlugin" apps/api/services/integrations apps/api/integrations`,
> `rg -n "RUN_TRIGGER_|RunPrincipal|conversations_source_check|agent_runs_trigger_check" apps/api`,
> and `rg -n "integrations.sweep_stale|ensure_integrations_sweep_job" apps/api`.
> Reconcile rather than overwrite unrelated working-tree changes.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH — unauthenticated network receipt, secret verification,
  at-least-once delivery, and unattended-run policy are security boundaries
- **Depends on**: 030, 037–039, 041, 054, 077 (all DONE)
- **Category**: Phase 4a inbound-provider implementation
- **Planned at**: working tree on 2026-07-24, after 041b and 082

## Decisions taken

1. **Adopt the recorded receipt defaults.** Receipt bodies are capped at 1 MiB;
   persisted authenticated payloads are capped at 64 KiB; terminal events are
   retained for 30 days; receipt is limited to 120 requests per minute per
   provider/source-IP pair. These replace the living note's review markers.
2. **Persist webhook registrations separately.** A plain
   `integration_webhooks` row resolves a server-minted opaque receipt id to a
   connection/resource, provider webhook id, secret reference, payload cursor,
   expiry, and lifecycle status. The local id is minted before provider creation
   because Airtable does not return its webhook id until after Praxis submits
   the callback URL. Connection metadata is not a concurrency-safe cursor or
   secret registry.
3. **Correct Airtable receipt dedup to match the current official contract.**
   Airtable's notification body has base id, webhook id, and timestamp; it does
   not contain the payload cursor. Receipt dedup therefore uses a provider-owned
   fingerprint of webhook id + notification timestamp. The webhook row stores
   the payload cursor returned by `list webhook payloads`; payload polling and
   cursor advancement remain idempotent under the event-row lock.
4. **No subscriptions or automatic agent runs yet.** The architecture reserves
   `integration_event_subscriptions` for a later numbered plan and explicitly
   puts subscription management after the receipt contract proves safe.
   This plan lands the `event` run/conversation vocabulary and enforces the
   scheduled-equivalent `require_approval` envelope so that later subscription
   code cannot mint a wider principal. It does not invent an unusable hidden
   subscription surface.
5. **Airtable lifecycle is provider-owned and engine-invoked.** The provider
   contributes verifier, create, refresh, delete, and payload-pull operations
   through the central plugin seam. Creation writes the one-time MAC secret
   immediately through `services/secrets`; only its reference is stored.
   Refresh scheduling rides the generic jobs runner with a 24-hour safety
   margin. No provider route family or timer is added.
6. **Thin receipt, fat job.** The route rate-limits, streams a bounded raw body,
   resolves the enabled plugin and registration, verifies before JSON parsing,
   inserts-or-ignores the compact event, enqueues
   `integrations.process_event`, commits, and returns 204. Airtable payload
   pulling and cursor updates happen only in the job handler.
7. **Rejected requests are safe to observe.** Verification failures record
   `integration_webhook_rejected` in an independent committed security event
   with provider key, webhook-id fingerprint, reason code, request id, and raw
   payload digest only. Raw headers, signatures, bodies, secret values, and
   provider data never enter logs or errors.
8. **Frontend behavior stays honest but minimal.** The existing conversation
   source/agent-run trigger unions gain `event`; event conversations get a
   compact native source indicator and background outputs become unread. There
   is no webhook or subscription UI in this plan.

## Current state

- `IntegrationProviderManifest.event_delivery` already supports
  `none | webhook | pubsub_push`; Airtable declares `webhook`, Google Ads uses
  the default `none`, and Gmail currently regressed to `none` despite the
  completed 041 contract requiring `pubsub_push`.
- `IntegrationProviderPlugin` has discovery, OAuth, tools, and preview seams,
  but no events contribution.
- There are no integration webhook/event models, routes, verifiers, processors,
  settings, or job kinds.
- `integrations.sweep_stale` is the single integration-retention job and is the
  required home for terminal event deletion.
- Agent-run and conversation checks, runtime principal typing, and frontend
  unions are exhaustive over interactive/direct, scheduled, and delegated.
- `APP_BASE_URL` plus `API_V1_PREFIX` is the existing canonical callback URL
  source. Localhost cannot receive Airtable pushes; webhook creation must fail
  clearly unless the resulting notification URL is public HTTPS, including in
  local development (where an operator may configure a tunnel URL).

## Scope

**In scope:**

- Core migration/models for `integration_webhooks`, `integration_events`, the
  `event` agent-run trigger, and `event` conversation source
- Event settings and validation
- Provider-neutral event contribution contract, receipt service, route,
  processing/refresh job handlers, and retention
- Airtable HMAC verification, webhook create/refresh/delete, payload polling,
  bounded normalization, and cursor advancement
- Security-event vocabulary and bounded receipt rate limiting
- Deterministic service/route/provider/runtime tests, including a suite-local
  synthetic provider
- Minimal frontend source/trigger contract and event source presentation
- Architecture and roadmap/status updates

**Out of scope:**

- `integration_event_subscriptions`, subscription routes/UI, filters,
  coalescing/debounce, quotas, or event-triggered run creation
- Gmail `users.watch`, Pub/Sub OIDC verification, or renewal
- Google Ads push behavior
- New CSRF exemptions, middleware order changes, provider-specific receipt
  routes, queues, or secret stores
- MCP, outbound events, replay/dead-letter UI, or an activity feed

## Implementation steps

### Step 1: Reconcile architecture and contracts

- Update `docs/architecture/integration-events.md` defaults to
  `[implemented: plan 079]`.
- Record the Airtable ping/cursor correction and the
  `integration_webhooks` registration row.
- Add frozen provider-neutral request metadata, normalized receipt, verifier,
  processor, and webhook-lifecycle callables to `IntegrationProviderPlugin`.
  Validate that providers declaring event delivery also contribute the required
  seams once event support is enabled.
- Restore Gmail's manifest posture to `pubsub_push` without adding Gmail event
  code; loader validation must allow a declared future posture with no
  contribution until its implementation plan.

### Step 2: Persist registrations/events and event-principal vocabulary

- Add core migration `0018` with both plain event tables, indexes/checks/FKs,
  trigger/source constraint updates, and a reversible downgrade.
- Add `IntegrationWebhook` and `IntegrationEvent` ORM models and exports.
- Add settings for body/payload caps, retention, receipt rate, processing
  timeout, refresh interval, and refresh safety margin.
- Add `RUN_TRIGGER_EVENT`, conversation source `event`, the
  scheduled-equivalent envelope branch, and background-unread behavior.

### Step 3: Build verification-first receipt

- Add the unauthenticated `POST
  /api/v1/integrations/events/{provider_key}/{webhook_id}` operation in its own
  route file.
- Rate-limit with a bounded provider/source-IP key before reading/verifying.
- Stream and hash the raw body under the receipt cap.
- Resolve only enabled provider plugins and active webhook registrations.
- Verify before parsing or persistence. On rejection, independently commit the
  bounded security event and return a typed non-2xx problem.
- Insert-or-ignore the event and enqueue exactly one process job; duplicates
  return 204 without a second job.

### Step 4: Build Airtable lifecycle and processing

- Extend the Airtable client with create/delete/refresh/list-payload operations.
- Store the creation response's base64 MAC secret immediately via
  `write_secret`; persist only the returned reference and expiry.
- Mint the opaque receipt id before provider creation and build the callback URL
  from `APP_BASE_URL` + `API_V1_PREFIX`; retain Airtable's returned webhook id
  separately for notification-body verification and payload polling.
- Verify `X-Airtable-Content-MAC` as HMAC-SHA256 over the exact raw body using
  the base64-decoded secret and constant-time comparison, then validate the
  body ids against the registration.
- Pull payload pages from the durable cursor (maximum 50 per provider request),
  follow `mightHaveMore` under a bounded page count, persist only bounded
  normalized metadata, atomically advance the cursor, and mark the event
  processed/discarded.
- Register process and refresh job handlers. Refresh active Airtable webhooks
  before the provider expiry margin; terminal failures follow the existing job
  notification path.
- Extend `integrations.sweep_stale` to delete terminal events older than the
  configured retention.

### Step 5: Keep the web contract honest

- Add `event` to conversation-source and run-trigger types.
- Map live event conversations to the event trigger.
- Render one compact, accessible event source indicator in list/detail
  surfaces using existing tokens, density, iconography, and copy.
- Add focused frontend tests; do not add a management screen.

### Step 6: Verify and close

- Run focused API tests for models, event receipt, Airtable provider behavior,
  jobs/retention, security/CSRF/rate limiting, and runtime envelopes.
- Run Ruff format/lint, Alembic check plus upgrade/downgrade/upgrade on the test
  database, and the complete database-backed API gate.
- Run focused Vitest/typecheck and `pnpm check`.
- Update both roadmap documents, mark 079 DONE with verification evidence, and
  move this plan into `docs/plans/complete/`.

## Test plan

- Registration/model constraints, secret-reference-only persistence, unique
  provider webhook ids/dedup keys, and migration round trip
- Route: valid 204, duplicate 204/no second job, unknown/disabled provider,
  unknown webhook, bad/missing MAC, forged body ids, over-limit body, bounded
  rate key, no session/bearer/workspace dependency, and cookie-bearing CSRF
  rejection with no exemption
- Security event contains only allowlisted metadata and survives rejection
- Airtable exact-byte HMAC, invalid base64 secret, create secret storage,
  refresh/delete, pagination/cursor advancement, spurious empty ping, bounded
  pages/payload persistence, retry/idempotency, and discarded stale connection
- Generic synthetic-provider coverage proves the engine never imports Airtable
- Event envelope always uses `require_approval`; an external write suspends
  while internal work remains available
- Retention deletes only old terminal events
- Frontend trigger mapping and event source presentation

## Done criteria

- [x] Architecture defaults are marked implemented and the Airtable cursor
      correction is recorded
- [x] Verification occurs before payload parsing/persistence/logging
- [x] Receipt is bounded, fail-closed, rate-limited on a bounded key, and
      deduplicated
- [x] Airtable MAC secrets are reference-only and never exposed
- [x] Airtable create/verify/pull/refresh/delete behavior is implemented and
      deterministic under retries
- [x] Processing and retention ride the existing jobs/sweep harness
- [x] `event` runs cannot widen beyond the scheduled unattended envelope
- [x] No CSRF exemption, provider-specific route family, subscription surface,
      Gmail event implementation, or Google Ads placeholder was added
- [x] Relevant focused and full gates pass
- [x] Roadmap/status docs are current and this plan is under
      `docs/plans/complete/`

## STOP conditions

Stop and report back instead of improvising if:

- Airtable's current official notification MAC or payload-cursor contract cannot
  be reconciled with verification-first receipt and durable cursor advancement.
- The current secret provider cannot durably store the one-time Airtable MAC
  secret without persisting its value in a model.
- The generic jobs transaction model cannot make event status/cursor advancement
  idempotent under retry.
- Adding `event` would require weakening the scheduled unattended envelope,
  approval dispatch, CSRF, CORS, cookie, or rate-limit posture.
- A subscription schema or UI is required to make the receipt spine internally
  correct; that is explicitly a later product slice and needs maintainer scope.

## Maintenance notes

- The next inbound-event plan is Gmail `users.watch` + Pub/Sub OIDC receipt and
  renewal. Subscription management follows only after this receipt contract has
  operational evidence.
- Airtable webhooks expire after seven days; listing payloads or refreshing an
  active hook extends expiry by seven days. Payloads remain available for one
  week and cursor values do not reset.
- A future subscription creator calls the provider-neutral webhook lifecycle
  seam, then mints event runs through the trigger/envelope vocabulary landed
  here. It must not call Airtable directly from a route.

## Completion evidence

Completed 2026-07-24.

- Focused backend coverage: 36 tests passed across Airtable lifecycle/MAC/payload
  polling, receipt/dedup/CSRF, provider-neutral processing, retention, plugin
  loading, model constraints, and event envelopes.
- Migration `core_0018` passed downgrade/upgrade, and `alembic check` reported no
  drift after the local database upgrade.
- Complete API gate: 936 tests passed.
- Complete web gate: 65 test files / 322 tests passed, plus typecheck, ESLint,
  Prettier, dead-code, dependency-architecture, and production-build checks.
- Ruff formatting and lint passed across all 885 backend files.
