# Plan 077: Inbound integration events — webhooks, verification, and event-triggered runs (design note)

> **Executor instructions**: This is a design-note plan in the 029/061 mold —
> its deliverable is `docs/architecture/integration-events.md` plus two small
> amendment blocks in sibling plans, not code. The code lands through later
> numbered plans that cite the note. Where this plan states a default, adopt
> it in the note and mark it `[default — confirm at review]` so the operator
> can veto cheaply at PR review. When done, update the status row in
> `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git status --porcelain docs/plans/037-integration-core-models-credentials.md docs/plans/041-first-integration-providers.md docs/architecture/`
> plus `grep -E '^\| 03[789] |^\| 04[01] ' docs/plans/000_README.md`. If 037
> has moved to DONE, decision 10 applies: the 037 amendment's schema deltas
> become a follow-up migration note instead of plan edits — do not amend a
> plan whose migration already shipped. If `docs/architecture/
> integration-events.md` already exists, reconcile rather than overwrite.

## Status

- **Priority**: P2
- **Effort**: M (design doc + two small amendment blocks)
- **Risk**: LOW as a doc — it prevents a pull-only architecture from
  ossifying before Phase 4a lands; the seams it reserves are near-free now
  and a migration later
- **Depends on**: 029 (DONE), 061 (DONE — provider packaging; events must
  fit the plugin contract), 030 (DONE — the jobs substrate events dispatch
  onto), 054 (written — envelope posture for unattended runs). **Binds
  before 037/041 execute** — 037's models and 041's providers must leave
  the hooks this note names
- **Category**: Phase 4a structural pre-decision (design note in the
  029/061 mold), added 2026-07-07
- **Planned at**: working tree at commit `6be5491`, 2026-07-07

## Decisions taken

1. **Decide the event architecture before Phase 4a code exists** — the
   plan 061 argument, applied to push instead of packaging. Plans 037–042
   are written 100% pull: no webhook receipt, no signature verification
   story, no event-triggered runs, and nothing reserving the seam. "Agent
   reacts to new email" is a headline agentic use case the architecture
   cannot currently express. Deciding now is a doc; deciding after 041
   lands three providers is a schema and provider-contract migration.
2. **One receipt surface, verification-first, fail-closed.** A single
   webhook route family `POST /api/v1/integrations/events/{provider_key}/
   {webhook_id}` receives every provider push. No session, no bearer, no
   user resolution — the request authenticates solely by the provider's
   cryptographic scheme, and verification runs before any parse, persist,
   or log-with-payload step. An unverifiable event is **dropped and
   audited** (a security event via `safe_record_security_event`, new type
   `integration_webhook_rejected`), never processed, and answered with a
   non-2xx — acknowledging unverified data would mask misconfiguration
   and let redelivery queues drain into silence.
3. **No CSRF exemption is needed, and none may be added.**
   `CSRFMiddleware` enforces only when a `session` cookie is present
   (`apps/api/middleware/csrf.py:60-69`); provider callers never carry
   one, so the webhook family passes untouched with the `exempt_paths`
   list (`csrf.py:45-55`) unmodified. The note must state this explicitly:
   adding the route to `exempt_paths` is both unnecessary and exactly the
   casual widening AGENTS.md forbids. A browser-borne POST carrying a
   session cookie *will* be CSRF-checked and fail — correct, since the
   handler ignores cookies entirely.
4. **Rate-limited receipt.** The route family uses the existing
   Postgres-backed `require_rate_limit` dependency
   (`core/rate_limiting.py:430`) keyed on provider + source IP, with the
   fail-closed posture the auth flows use. Verification failures count
   against the limit; a flood of garbage cannot become a verification
   CPU-burn or an audit-table flood.
5. **Verification is per-provider, via the plugin contract.** The 061
   `IntegrationProviderPlugin` gains an optional event-verifier seam:
   Airtable webhooks carry an HMAC over the payload keyed by a
   per-webhook MAC secret (compare with `hmac`-safe helpers —
   `utils/security.py::verify_hmac_signature` uses
   `secrets.compare_digest`, line 232); Gmail delivers via Google Pub/Sub
   push, where the endpoint verifies a Google-signed OIDC JWT (audience =
   our endpoint URL; `pyjwt>=2.13` is already a dep,
   `pyproject.toml:20`). Timestamp/replay posture: OIDC token expiry
   bounds Pub/Sub; HMAC schemes get a bounded acceptance window where the
   provider signs a timestamp, and the dedup key (decision 6) makes
   replays idempotent regardless. Per-connection webhook secrets are
   stored through 037's existing secret seams — `services/secrets`
   references under `integrations/{provider}/{connection_id}/webhook/*`
   (governance §5 references-only law; composes with plan 068's
   encryption posture — no new secret mechanism).
6. **Thin receipt, fat processing.** The HTTP handler does exactly:
   verify → insert one compact `integration_events` row → enqueue an
   `integrations.process_event` job on the 030 harness → return 2xx.
   Columns: `provider_key`, `connection_id` FK, `external_event_id`,
   `external_resource_id` (nullable), `event_type`, `payload_digest`
   (sha256, always), `payload` JSONB **bounded** (persist the body only up
   to `INTEGRATIONS_EVENT_PAYLOAD_MAX_BYTES`, default 64 KiB — push
   notifications are thin by design; oversize bodies keep digest only and
   the processor re-pulls from the provider), `dedup_key` (unique index),
   `received_at`, `status` (`received`/`processed`/`discarded`),
   `processed_at`. Plain rows (`Base + UUIDMixin + TimestampMixin`, the
   037 discovery-run composition) — an append-mostly log needs no
   soft-delete.
7. **Idempotency under at-least-once redelivery.** The `dedup_key` is
   computed by the provider verifier (Pub/Sub `messageId`; Airtable
   webhook id + notification cursor), unique-indexed, insert-or-ignore —
   a redelivered event returns 2xx without a second row or a second job.
   The processing job is idempotent by construction, 030's contract.
   Retention: a sweep clause deletes terminal event rows older than
   `INTEGRATIONS_EVENT_RETENTION_DAYS` (default 30), riding the
   `integrations.sweep_stale` kind plan 039 registers — one sweep, one
   more clause, the 039 pattern.
8. **Event-triggered runs are unattended by construction** — the named
   safety decision of this note. The v1 trigger shape is a new
   subscription object (`integration_event_subscriptions`, reserved not
   built: connection + resource + event type → agent + prompt template),
   NOT an overload of agent schedules — schedules are croniter/
   `next_run_at`-keyed and shoehorning events in would corrupt the
   worker's claim predicates. The processor mints runs through the
   existing run-creation seam with a new trigger value `event` (the
   `agent_runs` CHECK at `models/agent_run.py:101-103` grows one member),
   and plan 054's `build_run_envelope` derives the same posture for
   `event` as for `scheduled`: side-effect policy defaults to
   `require_approval`, so **an event-triggered run cannot perform an
   external write without a human approving it** — enforced by the
   envelope, not by per-agent configuration discipline. No separate
   settings knob in v1; divergence from the scheduled default is a
   future plan with a product reason.
9. **Provider reality for the D4 trio** (recorded honestly; this note
   reserves seams, implementation is a later numbered plan per
   provider): **Gmail** = `users.watch` + a Pub/Sub topic + a renewal
   job — watches expire after ~7 days, so a renewal sweep kind rides the
   jobs harness; lands first (the headline use case). **Airtable** =
   webhooks API with per-webhook MAC secrets and its own expiry/refresh
   cycle; notification pings are thin and the processor pulls actual
   change payloads from the payloads endpoint — a natural fit for thin
   receipt. **Google Ads** = no push surface at all; poll-only, stated
   plainly so nobody waits for a webhook that will never exist.
10. **037-executed contingency (drift decision).** If 037 has executed
    before this plan runs, its amendment cannot change a shipped
    migration: the `integration_events` table and the manifest
    `event_delivery` field become a "follow-up migration" note appended
    to 037's Maintenance notes instead of edits to its Steps, and the
    implementing plan owns the migration. Same posture for 041.

## Why this matters

The integration slice was designed from the donor's strongest pull
patterns — discovery jobs, credential refresh, fan-out reads — and it
shows: every data flow starts with Praxis asking. But the product's
headline agentic story is reactive ("when a new email arrives, my agent
triages it"), and reactive requires receipt, verification, dedup, and an
unattended-run trigger that today have no reserved seam anywhere: no
route family, no event table, no trigger vocabulary, no manifest field
saying whether a provider can push at all. This is the same shape of
problem 061 solved for packaging: free to decide while zero provider
code exists, a migration afterwards. The safety half is the sharper
reason to decide early — an event-triggered run is a machine acting on
external input with nobody watching, and 054's principal-derived
envelope is exactly the mechanism that makes it safe, but only if the
trigger vocabulary and derivation rule are agreed before 041 ships tools
whose writes send email and spend money.

## Scope

**In scope:**

- `docs/architecture/integration-events.md` (create — the design note)
- Amendment blocks in `docs/plans/037-integration-core-models-credentials.md`
  and `docs/plans/041-first-integration-providers.md` (seam reservations,
  not implementations)
- `docs/plans/000_README.md` row + the reserved follow-up plan slot

**Out of scope:**

- Any code. Routes, verifiers, the `integration_events` table, the
  subscription object, the `event` trigger, and the renewal sweeps all
  land through implementing plans citing the note.
- MCP anything — deferred by roadmap decision D7 and unrelated to this
  note; this plan is about provider webhooks/push events only.
- Amending 054 — its derivation table gains the `event` row when the
  implementing plan lands the trigger; the note records the rule.
- Outbound eventing, user-facing activity feeds, or notification policy
  changes (governance §6 stands).

## Git workflow

- Branch: `advisor/077-inbound-integration-events`
- Commit: `Docs - Inbound Integration Events Design Note`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write `docs/architecture/integration-events.md`

Front matter per the 029 rule: status (living document), and the rule
that implementing plans cite sections and record deviations back into
the note in the same PR. Sections:

1. Problem & non-goals (pull-only gap; MCP out of scope per D7)
2. Receipt surface (route family, no-session posture, the CSRF
   non-exemption argument from decision 3, rate limiting)
3. Verification (per-provider schemes, constant-time comparison, replay
   windows, webhook-secret storage, drop+audit rule)
4. Event persistence & dedup (the decision 6 columns, bounded payload
   vs digest, at-least-once idempotency, retention)
5. Processing pipeline (`integrations.process_event` on the 030
   harness; thin receipt, fat processing)
6. Event-triggered runs (subscription shape, `event` trigger, the 054
   envelope law — the note's single most important safety statement)
7. Provider posture matrix (gmail `pubsub_push` + watch renewal;
   airtable `webhook` + secret refresh; google_ads `none`; fake provider
   gets a synthetic push for tests)
8. Rollout order & revisit triggers (Gmail first; per-workspace event
   quotas; subscription UI)

Every stated default carries `[default — confirm at review]`.

### Step 2: Append the 037 amendment

Append to `docs/plans/037-integration-core-models-credentials.md`,
directly after the plan-068 amendment block, verbatim:

> **Amendment (2026-07-07, plan 077 — inbound integration events)**: per
> `docs/architecture/integration-events.md`, reserve the event seams —
> nothing here implements events:
>
> 1. **Manifest field.** `IntegrationProviderManifest` gains
>    `event_delivery: Literal["none", "webhook", "pubsub_push"] =
>    "none"` (data only; the loader and plugin contract are unchanged).
>    Decision 6's entries set gmail `"pubsub_push"`, airtable
>    `"webhook"`, google_ads `"none"`, fake `"none"` (041 flips fake to
>    a synthetic value when its test harness needs one).
> 2. **Webhook secrets ride the existing seams.** Per-webhook MAC
>    secrets are `services/secrets` references named
>    `integrations/{provider_key}/{connection_id}/webhook/{webhook_id}`
>    — no new column, table, or encryption mechanism (the plan-068
>    posture is unaffected). Note this in the credential service's
>    docstring so the implementing plan finds one seam, not two.
> 3. **`integration_events` is a reserved table decision, not scope.**
>    The note §4 fixes its shape (plain rows, dedup unique index,
>    bounded payload); the migration lands with the first event
>    implementation plan, on the core branch. Do not create it here —
>    but do not claim its name for anything else either.

If 037 is already DONE (decision 10), append points 1–3 reworded as a
"follow-up migration" entry in 037's Maintenance notes instead.

### Step 3: Append the 041 amendment

Append to `docs/plans/041-first-integration-providers.md`, directly
after the plan-068 amendment block, verbatim:

> **Amendment (2026-07-07, plan 077 — inbound integration events)**: per
> `docs/architecture/integration-events.md`, record each provider's
> event posture so the packages leave hooks — no event code lands here:
>
> 1. Manifest entries carry the 037-amendment `event_delivery` values:
>    gmail `"pubsub_push"` (`users.watch` + Pub/Sub + ~7-day renewal —
>    a later plan's sweep kind), airtable `"webhook"` (per-webhook MAC
>    secrets + refresh cycle; thin pings, payloads pulled), google_ads
>    `"none"` (no push surface exists — poll-only, permanently until
>    Google ships one).
> 2. The 061 package layout reserves an `events.py` module slot per
>    provider (verifier + watch/webhook management); leave it absent,
>    not stubbed. Provider clients must not acquire push-registration
>    calls here.

## Test plan

Not applicable (documentation) — tests land through the implementing
plans. This plan's verification is Step 1's citation accuracy (every
code anchor re-checked against HEAD) plus operator review of every
`[default — confirm at review]` marker.

## Done criteria

- [ ] `docs/architecture/integration-events.md` exists and covers §1–§8
      with every default marked for review
- [ ] 037 carries the plan-077 amendment block (or, per decision 10, the
      follow-up migration note) — `grep -c "plan 077" docs/plans/037-*.md`
      ≥ 1
- [ ] 041 carries the plan-077 amendment block —
      `grep -c "plan 077" docs/plans/041-*.md` ≥ 1
- [ ] The amendments compose with (reference, never contradict or
      duplicate) the existing 061/067/068 amendment blocks
- [ ] `docs/plans/000_README.md` row for 077 added, and the first
      implementation slice has a reserved, named plan slot recorded there
      (079 — inbound event receipt spine + Airtable webhooks)
- [ ] No code changed

## STOP conditions

Stop and report back (do not improvise) if:

- 037 or 041 has started executing mid-flight (branch exists, partial
  code landed) — reconcile with the landed code first instead of
  amending plans that no longer match; decision 10 covers the
  cleanly-DONE case only.
- `docs/architecture/integration-packaging.md`'s plugin contract has
  changed shape such that an event-verifier seam no longer fits it —
  reconcile with 061's note first.
- Plan 054 has been executed with a trigger/envelope shape that cannot
  accommodate an `event` principal (e.g. the trigger CHECK became an
  enum consumed exhaustively elsewhere) — the envelope law is the point
  of this note; do not weaken it to fit.
- You find yourself writing route, model, or verifier code — wrong plan.

## Maintenance notes

- The note is living: implementing plans record deviations back into it
  in the same PR (029 rule). The first implementation slice is reserved
  as plan 079 (receipt spine + Airtable webhooks — the cheapest full
  path through verify/persist/dedup/process); Gmail watch + Pub/Sub and
  its renewal sweep follow as their own plan; Google Ads never gets one.
- The subscription object is deliberately minimal in v1 (agent + prompt
  template). Filters, batching/debounce windows, and per-subscription
  envelope overrides are named revisit triggers in the note, not v1
  scope — each adds a permission or safety surface that deserves its
  own plan.
- Reviewers should scrutinize: that the CSRF exempt list is untouched by
  any implementing plan, that no handler path touches the payload before
  verification, that the `event` trigger inherits the scheduled envelope
  posture (the decision 8 law), and that webhook secrets never appear
  outside the `services/secrets` reference seam.
