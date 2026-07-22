# Plan 041b: Rich provider tool UI — presenter rows, provenance display, safe content preview

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `docs/plans/000_README.md`.
>
> **Notes pre-flight**: re-read
> `docs/architecture/integration-packaging.md` §2 principle 2
> (default-first UI, custom rows only if earned), §5 (frontend layout —
> the `IntegrationUiModule` seam this plan is the first real consumer
> of), and `docs/architecture/threat-model.md` §3 (the shared framing
> standard whose markers this plan surfaces in the UI). The notes win
> over this plan if they diverge.
>
> **Sibling-plan pre-flight**: 041 Slice A (Gmail provider) and 042
> (integrations UI, including the `src/integrations/` lazy-module seam)
> must be DONE. Slice C of this plan additionally requires 041 Slices
> B/C (Google Ads, Airtable); do not start Slice C before they land.

## Status

- **Priority**: P1
- **Effort**: M-L
- **Risk**: MEDIUM-HIGH (renders attacker-authored email HTML in the
  operator's browser; a sanitization gap is an XSS against the
  workspace session — treat the preview slice like an auth surface)
- **Depends on**: 041 Slice A (hard, DONE), 042 (hard, DONE); Slice C
  only: 041 Slices B/C
- **Category**: Phase 4a integrations (packaging note §2 principle 2,
  §5.2–5.4; threat-model §3/§4)
- **Planned at**: 2026-07-22, tree with 041 Slice A present
  (uncommitted work in progress on `main`).

## Problem

041's Gmail tools work, but the conversation renders them through the
generic declarative row: the model-visible result — a fan-out entry
list whose free text is wrapped in raw `<<<PRAXIS_UNTRUSTED_CONTENT
...>>>` frames — is shown nearly verbatim. Operators see framing
markers, base64-flavoured ids, and flattened plain text instead of an
email. There is no way to see the actual HTML message, no affordance to
reply, and nothing that generalizes to Ads reports or Airtable records.

The packaging note anticipated exactly this: principle 2 says the
default row must render every tool *acceptably*, and custom presenter
rows are "opt-in polish for the few tools that earn it (rich previews,
domain widgets)". Reading email in a chat transcript is the canonical
case that earns it. This plan builds the two missing layers and uses
Gmail to set the pattern every later provider copies.

## Decisions taken

1. **Two layers, strictly separated.**
   - *Layer 1 — presenter rows*: custom `ToolRowPresenter`s that render
     the **existing** tool-result payload richly (message list for
     search, formatted message view for read, an email-shaped approval
     card for send). Zero backend change; pure consumers of the shipped
     `IntegrationUiModule` seam.
   - *Layer 2 — on-demand content preview*: full HTML email (and later
     provider blobs) is fetched **user-initiated, at view time**,
     through a new engine seam — never by fattening tool results. The
     model-visible result deliberately excludes HTML (Gate G6 framing +
     plan 076 truncation); those constraints are not negotiable for UI
     convenience. Preview responses are ephemeral: never persisted,
     never entered into model context.
2. **The untrusted-frame vocabulary becomes a published display
   contract.** 041 declared the carrier/markers "runtime-internal, not
   SSE payload contracts", but the framed strings already reach the
   client verbatim inside stored tool-result parts — the client renders
   them today, badly. This plan records the deviation (in the packaging
   note §5.3 area and threat-model §3): the marker vocabulary and
   `source_kind`/`source_ref` attribute shape are now also a
   client-side *display* contract. A single shared helper
   (`src/lib/untrusted-frames.ts`) parses frames out of display strings
   and returns `{ content, sourceKind, sourceRef }` spans; UI renders
   the content inside a visually distinct "external content" container
   with a provenance chip ("Gmail message · 18c…"), never the raw
   markers. Parsing is forgiving: unmatched or forged (neutralized)
   markers render as plain text; a parse failure can never hide
   content. Changing the vocabulary now requires touching both sides —
   that is the cost of surfacing provenance as a UI asset, and it is
   pinned by tests on both sides.
3. **Preview seam shape (Layer 2).** `IntegrationProviderPlugin` gains
   one optional attribute — `previews: tuple[IntegrationPreviewDefinition, ...]`,
   default `()` — following the (withdrawn) §9 `oauth_operations`
   mechanism: contribution through the loaded plugin, resolution
   loader-only, §4.6 import laws unchanged. Each definition is
   `(kind: str, fetch: PreviewFetchFn)` where `fetch(client_credentials,
   external_ref)` returns a typed `IntegrationPreviewPayload`
   (`kind`, `content_type: "html" | "text"`, `content`, `meta: dict`).
   One generic core route serves every provider:
   `GET /api/v1/workspaces/{workspace_id}/integrations/connections/{connection_id}/previews/{kind}?ref=...`
   — engine-owned auth (`require_read` + workspace membership +
   connection-in-workspace check, mirroring
   `routes/integrations/list_connection_resources.py`), engine-owned
   response size bound, and one audit event per preview via
   `record_integration_operation_audit_event` (operation
   `preview_<kind>`, the user as actor, external ref = the `ref`; never
   content in audit details). The rationale bar for membership-level
   access: the same member already sees the full plain-text body in the
   transcript.
4. **HTML safety is defense in depth, and scripts never run.**
   - *Server*: sanitize with `nh3` (new dependency, rust ammonia
     bindings — allowlist-based) before the payload leaves the API:
     strip `script`/`style` event handlers, forms, `object`/`embed`/
     `iframe`, `meta` refresh, and javascript: URLs. The sanitized
     output is the only HTML the client ever receives.
   - *Client*: render in an opaque-origin `<iframe sandbox="" srcDoc>`
     (NO `allow-scripts` — this is stricter than
     `FileContentView`'s `allow-scripts`, deliberately: file HTML is
     workspace-authored, email HTML is attacker-authored) with an
     injected `<meta http-equiv="Content-Security-Policy">` of
     `default-src 'none'; img-src data:` — remote images blocked by
     default (tracking-pixel posture), with a per-message "Load remote
     images" action that re-renders with `img-src data: https:`.
   - *Threat model*: browser rendering of provider content is a new
     surface (§2's channel table is model-context only). This plan adds
     a new threat-model section for it with the mechanical defenses
     above and a hostile-HTML fixture (script, event handler, form,
     meta refresh, remote tracking pixel, javascript: link) asserted
     sanitized server-side; the fixture lives with the shared corpus
     directory.
5. **Reply stays inside the governance loop.** The read-message
   presenter's "Reply" affordance pre-fills the conversation composer
   with a structured instruction (recipient, subject, quoted context)
   so the send flows through `gmail_send_message` and its
   approval-default policy; the approval card's editable fields
   (`ToolUiField.editable`) are the editing surface. No user-direct
   write path ships in this plan: direct actions (send-as-user, file/
   archive/label) require operations outside 041 decision 10's curated
   surface AND a new user-principal action category with its own
   envelope/audit story — record in `docs/plans/FOLLOW_UPS.md`, do not
   grow this plan. "Open in Gmail" deep links
   (`https://mail.google.com/mail/#all/<message_id>`) cover the
   escape-hatch cases meanwhile.
6. **No protocol growth.** No new SSE event types, no new
   `ToolFieldFormat` values, no `ToolPresentation` schema changes
   (packaging §2 principle 5). Everything rides presenters, the one new
   preview route, and the one plugin attribute.
7. **The pattern is the deliverable.** Slice C applies it to Google Ads
   (report → sortable table presenter) and Airtable (records → field
   table presenter) once 041 B/C land, and amends packaging §8 so the
   provider N+1 checklist asks the presenter question explicitly
   ("does any tool return content a human would want to *see* rather
   than read about? If yes, presenter + preview kinds are part of the
   provider's package").

## Why this matters

The target operator is non-technical. A tool row that prints framing
markers and JSON-shaped text reads as broken, and "the agent found the
email but you cannot look at it" kills trust in the whole integration
story at first contact. This is also the moment to set the pattern:
Gmail is the first provider a real user connects, and every later
provider (Drive, Meta, Microsoft) will have the same split between
model-visible summary and human-visible artifact. Getting the seam
right once — presenters over existing data, ephemeral audited preview
for the rest, provenance rendered as a chip instead of noise — is what
keeps principle 2 true as the catalog grows.

## Current state

Anchors verified 2026-07-22.

- **Frontend seam (042, delivered)**: `apps/web/src/integrations/
  contract.ts` (`IntegrationUiModule`, `ToolRowPresenter`,
  `ToolRowPresenterProps` with `activity`, `approvalDecision`,
  `compact`, `live`, `providerKey`), `registry.ts` (lazy loaders keyed
  by provider, `integrationToolRowPresenters`,
  `useIntegrationUiModule`). All three provider modules are empty
  stubs (`gmail/index.ts` exports only `providerKey`).
- **Dispatch order**: `tool-call-row.tsx:58` consults
  `renderCustomToolCallRow` (which checks integration presenters,
  `tool-call-row-registry.tsx:96-99`) BEFORE the approval short-circuit
  at `tool-call-row.tsx:94` — presenters receive `approvalDecision` and
  can own the approval experience for their tools.
- **Data reaching the client**: `ToolActivity` (`message-parts/
  types.ts:28`) with `args`/`result` as `unknown`; transcript results
  parsed from stored parts (`parse.ts`), live results from SSE
  `tool.result` (`stream/protocol.ts:76`). Gmail result payloads are
  `{"results": [GmailFanOutEntry...]}` (`integrations/gmail/tools/
  schemas.py`) whose free-text fields arrive as framed strings —
  markers embedded (`services/agents/runtime/untrusted.py:63
  _render_frame`; vocabulary at lines 10-13).
- **Model-visible read result is plain text only**:
  `integrations/gmail/operations/read_message.py` strips HTML
  (`_TextExtractor`), caps at 50k chars, wraps in `UntrustedContent`.
  The HTML body never reaches the transcript — by design.
- **Rich-content infra**: `MessageMarkdown` (react-markdown +
  `rehype-sanitize`, hardened schema); `FileContentView`
  (`features/files/components/file-content-view.tsx:29`) renders HTML
  in a sandboxed iframe but with `allow-scripts` — a precedent for the
  component shape, NOT for the sandbox posture (decision 4).
- **Route/auth precedent**: `routes/integrations/
  list_connection_resources.py` (require_read + workspace + connection
  scoping); audit precedent
  `services/audit_events/integration_events.py::
  record_integration_operation_audit_event` (041 Slice A).
- **Plugin contract**: `services/integrations/plugin.py` —
  `manifest + discover_resources + tool_definitions`; packaging §10
  withdrew `oauth_operations` but its loader-only resolution mechanism
  is the sanctioned extension shape.
- **Boundary enforcement**: `.dependency-cruiser.cjs` rules for
  `src/integrations` (§5.5); `tests/integrations/test_import_laws.py`
  for the backend (§4.6).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Backend lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Backend tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/integrations tests/services/integrations tests/routes/integrations -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | exit 0 (includes dependency-cruiser + knip) |
| Frontend tests | `cd apps/web && pnpm test` | all pass |
| Full gate | `make check` | exit 0 |

## Scope

**In scope:**

- `apps/web/src/lib/untrusted-frames.ts` (create) — frame parsing for
  display (decision 2) + tests
- `apps/web/src/integrations/gmail/` (fill): `search-row.tsx`,
  `read-row.tsx`, `send-row.tsx` presenters, `message-preview.tsx`
  (sandboxed HTML view), `index.ts` composition
- `apps/web/src/features/conversations/` — only if a small shared
  "external content" container component is extracted for reuse across
  providers (place it in `src/components/ui` or `src/lib` territory so
  §5.5 rules keep passing)
- `apps/api/services/integrations/plugin.py` (extend — `previews`
  attribute), `services/integrations/loader.py` (validate preview
  definitions), a preview dispatch service under
  `services/integrations/` and route under `routes/integrations/`
  (decision 3)
- `apps/api/integrations/gmail/operations/preview_message.py` +
  registration of the `gmail_message` preview kind
- `nh3` dependency in `apps/api/pyproject.toml`; server-side
  sanitization helper (engine-owned, not provider-owned)
- `docs/architecture/threat-model.md` (new browser-rendering section +
  fixture), `docs/architecture/integration-packaging.md` (§5.3
  deviation note per decision 2; §8 checklist line per decision 7)
- Slice C: `apps/web/src/integrations/google_ads/` and `airtable/`
  presenters (report table, record fields)
- Tests: frontend presenter/frame/XSS tests; backend preview
  auth/sanitization/audit/import-law tests

**Out of scope (do NOT touch):**

- Tool result payload shapes, `output_model`s, dispatch framing,
  truncation bounds — the model-visible contract is 041/076's and does
  not change here
- New Gmail operations beyond the preview fetch (no labels, archive,
  drafts, attachments — FOLLOW_UPS)
- User-direct write actions of any kind (decision 5)
- SSE protocol, `ToolPresentation`/`ToolFieldFormat` vocabularies,
  approval resume contract
- Notifications, unread badges, or any inbox-like standalone surface —
  this plan renders tool activity, it does not build an email client

## Git workflow

- Branch: `advisor/041b-rich-provider-tool-ui`
- Commits: one per execution slice below. Do NOT push or open a PR
  unless the operator instructed it.

## Execution slices

### Slice A — Frame display + Gmail presenters (`Web - Gmail Tool Rows`)

Layer 1 only; no backend change. Steps 1–2.

- `untrusted-frames.ts` parser + provenance-chip "external content"
  container; Gmail search/read/send presenters registered in
  `gmail/index.ts`; reply prefill; Open-in-Gmail links.
- **Gate**: `pnpm check` + presenter tests green; a transcript fixture
  with framed content renders zero raw markers; a forged-marker
  fixture renders as inert text.
- **Review focus**: frames can never render as trusted chrome (the
  provenance chip is server-attributed data, styled distinctly from
  app UI); presenter fallback — any unexpected payload shape falls
  through to the default row rather than crashing (error boundary or
  guard-and-return-null).

### Slice B — Preview seam + HTML email view (`Cross - Provider Content Preview`)

Layer 2. Steps 3–5.

- Plugin `previews` + loader validation; preview service + route;
  `nh3` sanitization; audit; `gmail_message` preview kind; web
  `message-preview.tsx` (sandbox="" iframe, CSP meta, remote-image
  toggle) wired into the read presenter behind a "View full email"
  action; threat-model section + hostile HTML fixture.
- **Gate**: backend suites green including the sanitization fixture
  test and a cross-workspace 404 test; `pnpm check` green; manual QA
  with a real connection renders an HTML email with images blocked.
- **Review focus**: sanitizer allowlist (scripts/handlers/forms/
  javascript: URLs all stripped), iframe has NO allow-scripts and NO
  allow-same-origin, preview responses are never persisted or logged,
  audit rows carry refs but never content, connection scoping cannot
  be bypassed by guessing ids.

### Slice C — Ads + Airtable presenters (`Web - Provider Result Tables`)

Blocked on 041 Slices B/C. Step 6.

- Google Ads report rows → table presenter (GAQL field-path columns,
  truncation note surfaced); Airtable records → field-table presenter
  with framed-field handling; packaging §8 checklist amendment.
- **Gate**: `pnpm check` green; the decision-7 checklist line is in
  the packaging note; `000_README.md` row updated (plan-level done).

## Steps

### Step 1: Frame display contract

Implement `src/lib/untrusted-frames.ts`: split a string into ordered
spans of plain text and `{ content, sourceKind, sourceRef }` frames by
scanning for the exact vocabulary
(`<<<PRAXIS_UNTRUSTED_CONTENT source_kind="..." source_ref="...">>>` …
`<<<END_PRAXIS_UNTRUSTED_CONTENT>>>`). Forgiving by construction:
unterminated frames yield the remainder as frame content; attribute
parse failure yields kind/ref `null`; neutralized forged markers
(`PRAXIS_UNTRUSTED-CONTENT`) are plain text. Add the shared "external
content" container: distinct background, provenance chip, content
rendered as plain text (`white-space: pre-wrap`) — never through
markdown (a hostile body must not gain formatting-based authority).

Record the decision-2 deviation in packaging §5.3 and threat-model §3
(one sentence each: the vocabulary is also a display contract; both
sides pin it).

**Verify**: unit tests — round-trip of a server-produced frame
(fixture string copied from a backend test's actual output, so drift
breaks a test), forged markers inert, unterminated frame safe,
multi-frame strings ordered correctly.

### Step 2: Gmail presenters

In `src/integrations/gmail/`, one presenter per tool, matching on
`activity.name`:

- `gmail_search_messages` → per-mailbox message list: sender, subject
  (frame-unwrapped, chip on hover or inline-compact), date, snippet;
  mailbox header when multiple fan-out entries; error entries render
  the entry's `error_message` inline.
- `gmail_read_message` → email header block (from/to/date/subject),
  body in the external-content container, truncation notice when
  `truncated`, "Open in Gmail" link, "Reply" prefill (decision 5), and
  — after Slice B — "View full email".
- `gmail_send_message` → when `approvalDecision` is present, an
  email-shaped approval card (To/Subject/Body laid out as a message,
  editable per the existing `ToolUiField.editable` flags, reusing
  `ApprovalDecisionBlock`'s controls contract); after completion, a
  compact "sent" row with the message id as an Open-in-Gmail link.

Every presenter guards its payload shape and returns `null` on
mismatch so the default row takes over. Compose in `index.ts`;
`registry.ts` needs no change (loaders already exist).

**Verify**: vitest presenter tests with transcript-shaped fixtures
(success, partial fan-out failure, forged markers, unexpected shape →
null); `pnpm check` (dependency-cruiser §5.5 rules pass).

### Step 3: Preview seam (engine)

- `plugin.py`: `IntegrationPreviewDefinition(kind, fetch)` +
  `previews: tuple[...] = ()` on the plugin; loader validates kinds
  are unique, `^[a-z][a-z0-9_]*$`, and prefixed with the provider key.
- Preview service: resolve connection (workspace-scoped, 404 outside),
  resolve the provider's loaded plugin, find the kind, mint
  credentials via the existing seam, call `fetch`, sanitize `html`
  payloads with the `nh3` helper, enforce a response size cap
  (settings: `INTEGRATION_PREVIEW_MAX_BYTES`, default 2MB), emit the
  audit event, return the payload. Never store anything.
- Route per decision 3, response model
  `IntegrationPreviewRead(kind, content_type, content, meta)`.

**Verify**: route tests — auth required, cross-workspace 404, unknown
kind 404, size cap enforced, audit row written with
`operation="preview_gmail_message"` and no content; import-law test
still green.

### Step 4: Gmail preview operation

`integrations/gmail/operations/preview_message.py`: `messages.get
(format=full)`, extract the `text/html` part (fall back to `text/plain`
wrapped in `<pre>` semantics via `content_type="text"`), return
payload with `meta` = sanitized header summary (from/to/subject/date).
Register `("gmail_message", fetch)` on `PROVIDER.previews`. The
operation returns RAW html — sanitization is engine-owned (Step 3), so
a provider can never opt out of it.

**Verify**: MockTransport tests — HTML part extracted, plain-text
fallback, hostile fixture passes through the *service* and comes out
sanitized (fixture asserts script/handler/form/meta-refresh/
javascript:-URL removal and that the tracking-pixel img survives as an
https img for the client-side blocking layer to handle).

### Step 5: HTML email view (web)

`message-preview.tsx`: fetch on demand (TanStack Query, no persistence
beyond cache), render via `<iframe sandbox="" srcDoc>` with injected
CSP meta per decision 4, height-managed, loading/error states, "Load
remote images" toggle re-rendering with the widened `img-src`. Wire
into the read presenter. Add the threat-model section + fixture file
reference (Step 3/4 created the fixture).

**Verify**: component tests assert the iframe has `sandbox=""` (empty,
not merely present) and the CSP meta is injected; `make check` green.

### Step 6 (Slice C): Ads + Airtable presenters, checklist closure

Table presenters for `google_ads_run_report` (columns from GAQL field
paths, row-cap truncation note surfaced) and
`airtable_list_records`/`get_record` (field tables; framed field
values through the Step 1 container). Amend packaging §8 with the
decision-7 checklist line. Update the `000_README.md` status row.

**Verify**: `pnpm check` + presenter tests; packaging note updated.

## Test plan

Pinned invariants: **no raw framing markers ever render** (fixture
copied from real backend output so vocabulary drift fails CI), **forged
markers render inert**, **presenters fail open to the default row**,
**preview HTML is sanitized server-side AND rendered script-less in an
opaque-origin sandbox** (both layers asserted independently), **remote
images blocked by default**, **preview access is workspace-scoped and
audited without content**, **no new SSE/presentation vocabulary**, and
**§4.6/§5.5 boundary rules still pass**.

## Done criteria

- [ ] Gmail search/read/send render through presenters; zero raw
      markers in a seeded transcript; default row still renders when a
      module chunk fails to load
- [ ] "View full email" renders sanitized HTML in a script-less
      opaque-origin iframe with remote images blocked by default
- [ ] Preview route: scoped, size-bounded, audited (refs only),
      nothing persisted
- [ ] Reply prefill flows into the composer; send still requires
      approval (no policy change anywhere in the diff)
- [ ] Threat model has the browser-rendering section + hostile HTML
      fixture; packaging note carries the §5.3 deviation and §8
      checklist line
- [ ] FOLLOW_UPS records user-direct actions (file/archive/label,
      send-as-user) and attachments as explicitly deferred
- [ ] `make check` green; `docs/plans/000_README.md` row updated
      (Slice C may trail 041 B/C — mark partial status accordingly)

## STOP conditions

Stop and report back (do not improvise) if:

- Rendering rich results seems to require changing tool `output_model`s,
  dispatch framing, truncation bounds, or adding SSE event types /
  presentation field formats — that is platform scope this plan
  explicitly rejected.
- The preview seam seems to need to persist provider content, or to
  feed preview responses into model context — both are design
  violations, not implementation details.
- `nh3` is unacceptable as a dependency and the fallback is hand-rolled
  HTML sanitization — never hand-roll; report instead.
- The frame vocabulary in `untrusted.py` changed since 2026-07-22 —
  reconcile decision 2's two-sided contract first.
- You feel the need to build inbox navigation, unread state, message
  listing outside tool activity, or any user-direct write — scope leak
  toward "email client", which this plan is not.

## Maintenance notes

- **Provider N+1**: presenters and preview kinds live in the provider's
  own packages (`apps/api/integrations/<key>/` +
  `apps/web/src/integrations/<key>/`); the engine surface (route,
  sanitizer, container component, frame parser) never grows per
  provider. A provider needing a new `content_type` or a new engine
  behavior is a platform review, not a package change.
- **Reviewers should scrutinize**: sandbox attributes on every iframe
  touching provider content (empty `sandbox`, no `allow-same-origin`),
  sanitizer allowlist changes, any path where preview content could
  reach logs/audit/model context, and that provenance chips are
  visually distinct from app chrome (a frame must not be stylable into
  looking like a system message).
