# Plan 041b: Rich provider tool UI — presenter kits, provenance display, safe content preview

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
> of, and the §5.5 boundary rules this plan amends per decision 2), and
> `docs/architecture/threat-model.md` §3 (the shared framing standard
> whose markers this plan surfaces in the UI). The notes win over this
> plan if they diverge — except where a decision below explicitly
> amends a note, in which case the amendment lands in the note in the
> same slice.
>
> **Sibling-plan pre-flight**: 041 Slice A (Gmail provider) and 042
> (integrations UI, including the `src/integrations/` lazy-module seam)
> must be DONE. Slice C of this plan requires 041 Slice B (Google Ads —
> in progress on `main` as of 2026-07-22, package present uncommitted);
> Slice D requires 041 Slice C (Airtable). Do not start a slice before
> its provider lands.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH (renders attacker-authored email HTML in the
  operator's browser; a sanitization gap is an XSS against the
  workspace session — treat the preview slice like an auth surface)
- **Depends on**: 041 Slice A (hard, DONE), 042 (hard, DONE); Slice C
  only: 041 Slice B; Slice D only: 041 Slice C
- **Category**: Phase 4a integrations (packaging note §2 principle 2,
  §5.2–5.5; threat-model §3/§4)
- **Planned at**: 2026-07-22, tree with 041 Slice A present.
  **Rewritten 2026-07-22** after a donor-app parity review: the first
  draft's per-provider one-off presenters were replaced by engine-owned
  **presenter kits** (the donor's "family renderer" architecture), a
  kind-driven data-table/KPI/chart surface for reports, and a richer
  message experience. The donor sets the *richness benchmark*; its
  *mechanisms* are adopted only where they fit our packaging and
  threat-model posture — rejections are recorded in "Donor patterns
  deliberately rejected" so they are not re-proposed.

## Problem

041's Gmail tools work, but the conversation renders them through the
generic declarative row: the model-visible result — a fan-out entry
list whose free text is wrapped in raw `<<<PRAXIS_UNTRUSTED_CONTENT
...>>>` frames — is shown nearly verbatim. Operators see framing
markers, base64-flavoured ids, and flattened plain text instead of an
email. Google Ads (041 Slice B, landing now) is worse: every tool ships
`result_fields` of a single `list`-format field
(`integrations/google_ads/tools/utils.py:39`), so a GAQL report — rows
of framed strings keyed by field paths — renders as an unreadable chip
soup. There is no way to see the actual HTML message, no table for a
report, no chart, no affordance to reply, and nothing that generalizes
to Airtable records.

The declarative default row was never meant to carry this. Principle 2
says the default row must render every tool *acceptably*, and custom
presenter rows are "opt-in polish for the few tools that earn it (rich
previews, domain widgets)". Email in a chat transcript and ad-spend
report tables are the canonical cases that earn it. The donor app
proves the ceiling: message lists that read like an inbox, HTML email
in a hardened frame, reports as formatted tables with currency/percent
cells, KPI strips, chart⇄table toggles, CSV export, row drill-downs,
editable approval cards, and per-account partial-failure summaries.
This plan builds that level of experience — through our seams, not the
donor's.

## Donor benchmark (what "rich" means here)

The donor (`saas-template` — see `apps/web/src/components/ai/tools/`
in that tree) renders ~10 providers richly from ~6 shared renderer
kits; providers contribute only thin `adapt(output) → KitResult`
functions. The experiences this plan commits to reproducing, in our
styles:

- **Gmail search** → an inbox-like list per mailbox: sender, subject,
  relative date, snippet, per-row "Open in Gmail" deep link; fan-out
  entry headers when multiple mailboxes; inline error entries.
- **Gmail read** → an email header block (from/to/date/subject as
  address chips), the plain-text body in a provenance-marked external-
  content container with preview/expand, "Open in Gmail", "Reply"
  prefill, and — once the preview seam lands — a "View full email"
  HTML view in a hardened iframe with remote images blocked by
  default.
- **Gmail send** → an email-shaped approval card (To/Cc/Bcc/Subject/
  Body laid out as a message, editable fields wired to the existing
  approval-edit mechanism), then a compact "sent" confirmation row
  with an Open-in-Gmail link.
- **Google Ads report** → a real data table: kind-driven columns
  (currency from micros, percent, number, date, status badge, id),
  right-aligned `tabular-nums` metrics, zebra rows, a totals footer,
  truncation note, copy-CSV/download-CSV actions, row click → detail
  sheet, and a chart⇄table toggle (line over time when a date
  dimension is present, bar otherwise).
- **Google Ads accounts** → the account hierarchy as an indented list
  with manager/status/writable badges.
- **Google Ads campaign mutation** → an approval card with an explicit
  write-operation banner, campaign list, and the editable
  ENABLED/PAUSED select; a result view with succeeded/failed counts
  and per-campaign status badges + inline error text (partial-failure
  first-class).
- **Airtable records** → field-table cards per record with
  field-type-aware value rendering and framed-field handling.
- **Everywhere** → "N succeeded · M failed" fan-out summaries with a
  failed-entries block, loading skeletons, empty states, metadata
  strips (provider · resource · counts · truncation), and provenance
  chips instead of raw markers.

## Decisions taken

1. **Two layers, strictly separated** (unchanged from the first
   draft).
   - *Layer 1 — presenter kits + adapters*: rich rendering of the
     **existing** tool-result payloads. Zero model-visible change
     beyond decision 8's narrow metadata additions; pure consumers of
     the shipped `IntegrationUiModule` seam.
   - *Layer 2 — on-demand content preview*: full HTML email (and later
     provider blobs) is fetched **user-initiated, at view time**,
     through a new engine seam — never by fattening tool results. The
     model-visible result deliberately excludes HTML (Gate G6 framing +
     truncation bounds); those constraints are not negotiable for UI
     convenience. Preview responses are ephemeral: never persisted,
     never entered into model context.
2. **Layer 1 is kit-based: engine-owned presenter kits, thin provider
   adapters.** This is the donor's highest-leverage pattern and the
   core change of the rewrite. A new engine-owned directory
   `apps/web/src/components/tool-ui/` holds shared renderer kits;
   provider modules under `src/integrations/<key>/` contain only
   `matches` guards and `adapt(activity) → KitProps | null` functions
   plus composition. The kits:
   - **`fan-out-shell`** — the universal envelope for
     `{"results": [entries...]}` payloads: per-entry sections keyed by
     resource `display_name`/`external_id`, a "N succeeded · M failed"
     summary when mixed, a failed-entries block rendering
     `error_message` inline, an empty state, and a metadata strip.
     Every provider presenter wraps in it.
   - **`external-content`** — the provenance container from decision
     3: distinct background, provenance chip, plain-text rendering
     (`white-space: pre-wrap`, never markdown), preview/expand for
     long bodies.
   - **`message`** — message list rows (sender/subject/date/snippet,
     deep-link action) and a message detail block (header grid,
     address chips, body via `external-content`, action row).
   - **`data-table`** — kind-driven columns
     (`text | number | currency | percent | date | datetime | status |
     badge | link | id`), per-kind cell formatters (`Intl` currency
     and locale numbers, `font-mono tabular-nums` right-aligned
     metrics, status-tone badges, `<code>` ids, external-link cells),
     zebra striping, horizontal scroll inside the row, optional totals
     footer, truncation/pagination footer, copy-CSV/download-CSV
     actions, and row click → a detail `Sheet` with a two-column field
     grid. Built on the existing shadcn `table.tsx` primitive; the
     copy/download helpers are extracted to `src/lib/table-export.ts`
     and shared with `MarkdownTable` (which currently hand-rolls them,
     `markdown-table.tsx:21-49,154-187`).
   - **`kpi`** — a responsive strip of stat cards (mono tabular value,
     tone border), used for mutation result counts and report
     summaries.
   - **`chart`** — decision 7's chart surface with the chart⇄table
     toggle.
   - **`approval-card`** — the tool approval shell (title, icon,
     optional write-operation banner, body slot, Approve/Decline
     footer driven by the existing `ToolApprovalDecisionControls`
     contract) extracted from
     `features/conversations/components/approval-decision-block.tsx`
     so presenters can compose bespoke approval bodies (email-shaped,
     mutation-shaped) without importing `features/`.
     `ApprovalDecisionBlock` remains in `features/` as the default
     consumer of the extracted primitives; the editable-field engine
     (`approval-decision-fields.tsx`) moves with the shell. No change
     to the controls contract or approval flow.

   **§5.5 amendment (recorded in the packaging note in the same
   slice)**: boundary rule 1 gains `^src/components/tool-ui` in the
   import allowlist for `^src/integrations`. Kits are engine-owned: a
   provider needing a new kit or a new column kind is a platform
   review, not a package change. `src/components/tool-ui` may import
   only `src/components/ui` and `src/lib` (a new cruiser rule pins
   this), so kits can never grow feature/route dependencies.
3. **The untrusted-frame vocabulary becomes a published display
   contract.** 041 declared the carrier/markers "runtime-internal, not
   SSE payload contracts", but the framed strings already reach the
   client verbatim inside stored tool-result parts — the client
   renders them today, badly. This plan records the deviation (in the
   packaging note §5.3 area and threat-model §3): the marker
   vocabulary and `source_kind`/`source_ref` attribute shape are now
   also a client-side *display* contract. A single shared helper
   (`src/lib/untrusted-frames.ts`) parses frames out of display
   strings and returns `{ content, sourceKind, sourceRef }` spans; UI
   renders the content inside the `external-content` container with a
   provenance chip ("Gmail message · 18c…"), never the raw markers.
   Parsing is forgiving: unmatched or forged (neutralized) markers
   render as plain text; a parse failure can never hide content.
   **Per-cell frames**: Google Ads report cells arrive individually
   framed (`operations/run_report.py:40-50` wraps every string cell);
   the data-table adapter unwraps each cell via the shared parser and
   the table shows provenance **once at container level** ("External
   data · Google Ads · account 123…") — a chip per cell would be
   noise, and the container-level treatment is the same trust signal.
   Changing the vocabulary now requires touching both sides — that is
   the cost of surfacing provenance as a UI asset, and it is pinned by
   tests on both sides (the frontend fixture string is copied from
   real backend output so drift fails CI).
4. **Preview seam shape (Layer 2).** `IntegrationProviderPlugin` gains
   one optional attribute —
   `previews: tuple[IntegrationPreviewDefinition, ...]`, default `()`
   — following the (withdrawn) §9 `oauth_operations` mechanism:
   contribution through the loaded plugin, resolution loader-only,
   §4.6 import laws unchanged. Each definition is
   `(kind: str, fetch: PreviewFetchFn)` where
   `fetch(client_credentials, external_ref)` returns a typed
   `IntegrationPreviewPayload` (`kind`,
   `content_type: "html" | "text"`, `content`, `meta: dict`). One
   generic core route serves every provider:
   `GET /api/v1/workspaces/{workspace_id}/integrations/connections/{connection_id}/previews/{kind}?ref=...`
   — engine-owned auth (`require_read` + workspace membership +
   connection-in-workspace check, mirroring
   `routes/integrations/list_connection_resources.py`), engine-owned
   response size bound, and one audit event per preview via
   `record_integration_operation_audit_event` (operation
   `preview_<kind>`, the user as actor, external ref = the `ref`;
   never content in audit details). The rationale bar for
   membership-level access: the same member already sees the full
   plain-text body in the transcript.
5. **HTML safety is defense in depth, and scripts never run.**
   - *Server*: sanitize with `nh3` (new dependency, rust ammonia
     bindings — allowlist-based) before the payload leaves the API:
     strip `script`/`style` event handlers, forms, `object`/`embed`/
     `iframe`, `meta` refresh, and javascript: URLs; harden every
     anchor (http/https/mailto/tel only, `target="_blank"
     rel="noopener noreferrer nofollow"`). The sanitized output is the
     only HTML the client ever receives.
   - *Client*: render in an opaque-origin `<iframe sandbox="" srcDoc>`
     (NO `allow-scripts`, NO `allow-same-origin` — stricter than both
     `FileContentView`'s `allow-scripts`
     (`file-content-view.tsx:29-38`, workspace-authored content) and
     the donor's `allow-same-origin` email frame, deliberately: email
     HTML is attacker-authored) with an injected
     `<meta http-equiv="Content-Security-Policy">` of
     `default-src 'none'; img-src data:` — remote images blocked by
     default (tracking-pixel posture), with a per-message "Load remote
     images" action that re-renders with `img-src data: https:`.
   - *Consequence accepted*: with an opaque origin the parent cannot
     measure the frame's content height (the donor's auto-height
     script requires `allow-same-origin`). The preview renders in a
     fixed `max-height` container with internal scroll. Do not weaken
     the sandbox to get auto-height.
   - *Threat model*: browser rendering of provider content is a new
     surface (§2's channel table is model-context only). This plan
     adds a new threat-model section for it with the mechanical
     defenses above and a hostile-HTML fixture (script, event handler,
     form, meta refresh, remote tracking pixel, javascript: link)
     asserted sanitized server-side; the fixture lives with the shared
     corpus directory.
6. **Reply stays inside the governance loop.** The read-message
   presenter's "Reply" affordance pre-fills the conversation composer
   with a structured instruction (recipient, subject, quoted context)
   so the send flows through `gmail_send_message` and its
   approval-default policy; the approval card's editable fields
   (`ToolUiField.editable`, rendered by the extracted field engine)
   are the editing surface. No user-direct write path ships in this
   plan: direct actions (send-as-user, file/archive/label) require
   operations outside 041 decision 10's curated surface AND a new
   user-principal action category with its own envelope/audit story —
   record in `docs/plans/FOLLOW_UPS.md`, do not grow this plan. "Open
   in Gmail" deep links
   (`https://mail.google.com/mail/#all/<message_id>`) cover the
   escape-hatch cases meanwhile.
7. **Charts: `recharts`, one wrapper, chart⇄table toggle.** The web
   app has no chart library; reports deserve one. Add `recharts`
   (^2.x) to `apps/web` as the single chart dependency, wrapped once
   in the `chart` kit (`DataChart`: bar | line; themed via existing
   Tailwind tokens; abbreviated K/M axis ticks with currency/percent
   awareness; capped legend). `google_ads_run_report` presenters
   auto-derive a chart from the parsed table: line when a
   `segments.date` column is present, bar otherwise; up to 3 metric
   series; rendered behind a chart⇄table toggle with the table as the
   default view. Charts consume only unwrapped, numerically parsed
   cells — a framed string that fails numeric parsing is excluded from
   charting, never coerced. Pie/combo variants, model-authored charts,
   and dashboards are out of scope (FOLLOW_UPS).
8. **Narrow, additive result-data enrichment — recorded, not
   forbidden.** The first draft froze tool payloads entirely; that
   froze the UI below the benchmark. The rule is now: *small additive
   metadata fields inside a provider `data` dict are allowed when they
   serve the model and the human alike and cost trivial tokens*; HTML,
   blobs, and anything that exists only for rendering stay excluded
   (that is what Layer 2 is for). Under this rule, this plan makes
   exactly one addition: `google_ads_run_report` per-account `data`
   gains `currency_code` (from the discovered resource metadata) so
   both the model and the table formatter can interpret micros. Cell
   values stay raw GAQL micros in the model-visible payload; the
   data-table kit converts micros → currency units for display
   (`metrics.*_micros` → `value / 1e6`, `Intl` currency with
   `currency_code`). Whether the model-visible rows should pre-convert
   micros is a FOLLOW_UPS question, not this plan's. Any future
   addition under this rule is a provider-package change reviewed
   against it, one field at a time.
9. **No protocol growth.** No new SSE event types, no new
   `ToolFieldFormat` values, no `ToolPresentation` schema changes
   (packaging §2 principle 5). Column kinds, table rendering, charts,
   and provenance are entirely client-side interpretations of existing
   payloads (plus decision 8's one field). Everything rides
   presenters, the kits, the one new preview route, and the one plugin
   attribute. The declarative default row remains the guaranteed
   fallback for every tool.
10. **The pattern is the deliverable.** Slices C and D apply the kits
    to Google Ads and Airtable as each 041 slice lands, and amend
    packaging §8 so the provider N+1 checklist asks the adapter
    question explicitly ("does any tool return content a human would
    want to *see* rather than read about? If yes: which kits, and
    which preview kinds, are part of the provider's package — adapters
    only, never new kit code").

## Donor patterns deliberately rejected

Recorded so they are not re-proposed as "the donor did it":

- **`allow-same-origin` on the email iframe + client-only DOMPurify
  sanitization** — rejected; our posture is server-side `nh3` AND an
  opaque-origin script-less sandbox (decision 5). The donor trusts the
  client sanitizer and pays for auto-height with a weaker sandbox.
- **Full HTML email bodies inside tool results** — rejected; the
  model-visible payload stays plain-text and framed (Gate G6). HTML
  arrives only via the audited, ephemeral preview seam (Layer 2).
- **Direct tool invocation from the UI** (donor's tool-catalog
  playground, direct-send forms, `inputSubmitsInternally`) — rejected
  for this plan; every write flows through the agent + approval
  governance (decision 6). A tool playground is a separate roadmap
  conversation.
- **Provider logic in shared modules** (the donor's descriptor cache,
  per-provider branches in shared renderers) — rejected; kits are
  generic, adapters live in provider packages, boundaries are
  machine-enforced (§5.5 as amended).
- **Micros pre-converted server-side for display** — deferred
  (decision 8): the model-visible contract keeps raw GAQL values;
  conversion is a display concern until FOLLOW_UPS decides otherwise.
- **Threads, labels, unread state, attachments in Gmail rows** — the
  041 decision-10 curated surface doesn't return them
  (`GmailMessageSummary` carries sender/to/subject/date/snippet only,
  `integrations/gmail/tools/schemas.py:11-18`), so the UI does not
  fake them. The message kit is designed so label chips/attachment
  rows slot in when a later plan widens the surface (FOLLOW_UPS).

## Why this matters

The target operator is non-technical. A tool row that prints framing
markers and JSON-shaped text reads as broken, and "the agent found the
email but you cannot look at it" — or "the agent pulled your spend
report but it renders as chips" — kills trust in the whole integration
story at first contact. This is also the moment to set the pattern:
Gmail and Google Ads are the first providers a real user connects, and
every later provider (Drive, Sheets, Meta, Microsoft) maps onto the
same few kits: messages, tables, records, charts. Getting the seam
right once — engine-owned kits, provider-owned adapters, provenance as
a chip instead of noise, ephemeral audited preview for anything heavy —
is what keeps principle 2 true as the catalog grows: the default row
stays the floor, the kits become the affordable ceiling, and bespoke
one-off UI stays exceptional.

## Current state

Anchors verified 2026-07-22.

- **Frontend seam (042, delivered)**: `apps/web/src/integrations/
  contract.ts` — `ToolRowPresenterProps` (lines 13-20: `activity`,
  `approvalDecision?`, `compact`, `defaultOpen`, `live`,
  `providerKey`), `ToolRowPresenter` (22-26), `IntegrationUiModule`
  (28-33). `registry.ts` — `MODULE_LOADERS` (11-15),
  `integrationToolRowPresenters` (24-29), `useIntegrationUiModule`
  (41). All three provider modules are bare stubs exporting only
  `providerKey`.
- **Dispatch order**: `tool-call-row.tsx:58-68` consults
  `renderCustomToolCallRow` (which appends integration presenters to
  the built-in list, `tool-call-row-registry.tsx:96-102`) BEFORE the
  approval short-circuit at `tool-call-row.tsx:94-108` — presenters
  receive `approvalDecision` and can own the approval experience for
  their tools. The declarative default row (`ToolFieldGrid`,
  120-175) is the fallback.
- **Approval machinery**: `approval-decision-block.tsx` —
  `ToolApprovalDecisionControls` (25-33), `ApprovalDecisionBlock`
  (35-134) composing `ToolApprovalCard` + `ApprovalRequestFields` +
  `ApprovalFooter`; the editable-field engine is
  `approval-decision-fields.tsx:31-198` (Select at 142-167 when
  `options` present, Textarea 168-177, Input 178-187). These live in
  `features/conversations/components/` — presenters cannot import them
  today (§5.5 rule 1); decision 2 extracts the shell.
- **Data reaching the client**: `ToolActivity`
  (`message-parts/types.ts:28-39`) with `args`/`result` as `unknown`
  end-to-end (`stream/protocol.ts:76-83`); presenters must narrow the
  fan-out `{results: [{..., data}]}` shape with guards.
- **Gmail payloads** (`integrations/gmail/tools/schemas.py`):
  `GmailMessageSummary` (11-18), `GmailSearchData` (20-23),
  `GmailMessageData` (25-33, `body` + `truncated`), `GmailSendData`
  (35-37), fan-out envelope `GmailFanOutEntry` (39-49:
  `integration_resource_id`, `connection_id`, `provider_key`,
  `external_id`, `display_name`, `status`, `data`, `error_code`,
  `error_message`). Free-text fields arrive as framed strings
  (`services/agents/runtime/untrusted.py` — markers at 10-13,
  `UntrustedContent` 18-25, `_render_frame` 63-73,
  `_sanitize_source_component` 76-79). The HTML body never reaches
  the transcript — by design (`read_message.py` strips HTML, caps at
  50k).
- **Google Ads payloads (041 Slice B, in progress on `main`,
  uncommitted — verify at execution)**: client pinned to v24
  (`client.py:12`). `google_ads_run_report` per-account `data` =
  `{rows, row_count, truncated, truncation_note}` with every string
  cell individually framed (`operations/run_report.py:40-50`);
  `google_ads_list_accounts` `data` = `{accounts: [{customer_id,
  display_name, parent_customer_id, manager, currency_code, status,
  writable, enabled}]}`; `google_ads_update_campaign_status` `data` =
  `{resource_names, campaign_errors: [{campaign_id, message,
  error_code}]}` (partial failure at
  `operations/update_campaign_status.py:42-79`), with an
  approval-editable `status` field (options ENABLED/PAUSED) already in
  its presentation. All three currently present results as one
  `list`-format field (`tools/utils.py:39`).
- **Rich-content ceiling today**: `MessageMarkdown` (react-markdown +
  `rehype-sanitize`), `MarkdownTable` (bespoke, with copy-TSV /
  download-CSV at `markdown-table.tsx:21-49,154-187`), `ToolField`
  chips/links (`tool-field.tsx`, `FULL_WIDTH_FORMATS` 12-17), and
  `FileContentView`'s `allow-scripts` iframe
  (`file-content-view.tsx:29-38`) — a precedent for the component
  shape, NOT the sandbox posture (decision 5).
- **Design system**: shadcn-style primitives on `@base-ui/react`
  (`src/components/ui/`: table, sheet, badge, card, skeleton, tabs,
  tooltip, select, …), Tailwind v4 + CVA + `cn()`, `lucide-react`.
  **No chart library** in `apps/web/package.json` (decision 7 adds
  one).
- **Route/auth precedent**:
  `routes/integrations/list_connection_resources.py` (require_read +
  workspace + connection scoping); audit precedent
  `services/audit_events/integration_events.py::
  record_integration_operation_audit_event` (041 Slice A). **No
  preview or on-demand-fetch route exists** —
  `routes/integrations/__init__.py` registers connect/context/
  discovery/connection-management routes only.
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
  display (decision 3) + tests; `src/lib/table-export.ts` (extract
  from `markdown-table.tsx`)
- `apps/web/src/components/tool-ui/` (create) — the decision-2 kits
  (`fan-out-shell`, `external-content`, `message`, `data-table`,
  `kpi`, `chart`, `approval-card` + the relocated editable-field
  engine) with tests
- `.dependency-cruiser.cjs` — the §5.5 amendment (integrations may
  import `^src/components/tool-ui`; tool-ui may import only ui/lib)
- `apps/web/src/integrations/gmail/` (fill): search/read/send
  adapters + presenters, `message-preview.tsx` (sandboxed HTML view),
  `index.ts` composition
- `apps/web/src/integrations/google_ads/` (fill, Slice C): report
  table+chart adapter, accounts list adapter, campaign-status
  approval/result adapter
- `apps/web/src/integrations/airtable/` (fill, Slice D): record
  field-table adapters
- `apps/web/src/features/conversations/components/` — extraction
  refactor only (decision 2); `ApprovalDecisionBlock` keeps its
  public behavior
- `apps/web/package.json` — `recharts` (decision 7)
- `apps/api/services/integrations/plugin.py` (extend — `previews`
  attribute), `services/integrations/loader.py` (validate preview
  definitions), a preview dispatch service under
  `services/integrations/` and route under `routes/integrations/`
  (decision 4)
- `apps/api/integrations/gmail/operations/preview_message.py` +
  registration of the `gmail_message` preview kind
- `apps/api/integrations/google_ads/operations/run_report.py` — the
  decision-8 `currency_code` addition (Slice C)
- `nh3` dependency in `apps/api/pyproject.toml`; server-side
  sanitization helper (engine-owned, not provider-owned)
- `docs/architecture/threat-model.md` (new browser-rendering section +
  fixture), `docs/architecture/integration-packaging.md` (§5.3
  deviation note per decision 3; §5.5 amendment per decision 2; §8
  checklist line per decision 10)
- Tests: kit unit tests; presenter/adapter tests per provider;
  frame/XSS tests; backend preview auth/sanitization/audit/import-law
  tests

**Out of scope (do NOT touch):**

- Tool `output_model`s, dispatch framing, truncation bounds, or any
  model-visible value beyond decision 8's single `currency_code`
  field — the model-visible contract is 041's
- New Gmail/Ads/Airtable operations beyond the preview fetch (no
  labels, archive, drafts, attachments, threads — FOLLOW_UPS)
- User-direct write actions or UI-direct tool invocation of any kind
  (decision 6; rejected-patterns list)
- SSE protocol, `ToolPresentation`/`ToolFieldFormat` vocabularies,
  approval resume contract
- Notifications, unread badges, or any inbox-like standalone surface —
  this plan renders tool activity, it does not build an email client
- Dashboards, saved reports, model-authored charts (FOLLOW_UPS)

## Git workflow

- Branch: `advisor/041b-rich-provider-tool-ui`
- Commits: one per execution slice below. Do NOT push or open a PR
  unless the operator instructed it.

## Execution slices

### Slice A — Kit substrate + Gmail presenters (`Web - Tool UI Kits & Gmail Rows`)

Layer 1; no backend change. Steps 1–3.

- `untrusted-frames.ts` parser; `src/components/tool-ui/` with
  `fan-out-shell`, `external-content`, `message`, and the
  `approval-card` extraction; the §5.5 cruiser amendment; Gmail
  search/read/send presenters registered in `gmail/index.ts`; reply
  prefill; Open-in-Gmail links.
- **Gate**: `pnpm check` + kit/presenter tests green; a transcript
  fixture with framed content renders zero raw markers; a
  forged-marker fixture renders as inert text; `ApprovalDecisionBlock`
  behavior unchanged (existing approval tests still pass).
- **Review focus**: frames can never render as trusted chrome (the
  provenance chip is server-attributed data, styled distinctly from
  app UI); presenter fallback — any unexpected payload shape falls
  through to the default row rather than crashing (guard-and-return-
  null, error boundary at the presenter seam); the extraction did not
  alter approval semantics or the controls contract.

### Slice B — Preview seam + HTML email view (`Cross - Provider Content Preview`)

Layer 2. Steps 4–6.

- Plugin `previews` + loader validation; preview service + route;
  `nh3` sanitization; audit; `gmail_message` preview kind; web
  `message-preview.tsx` (sandbox="" iframe, CSP meta, remote-image
  toggle, fixed max-height) wired into the read presenter behind a
  "View full email" action; threat-model section + hostile HTML
  fixture.
- **Gate**: backend suites green including the sanitization fixture
  test and a cross-workspace 404 test; `pnpm check` green; manual QA
  with a real connection renders an HTML email with images blocked.
- **Review focus**: sanitizer allowlist (scripts/handlers/forms/
  javascript: URLs all stripped, anchors hardened), iframe has NO
  allow-scripts and NO allow-same-origin, preview responses are never
  persisted or logged, audit rows carry refs but never content,
  connection scoping cannot be bypassed by guessing ids.

### Slice C — Google Ads report UI (`Cross - Google Ads Report UI`)

Blocked on 041 Slice B. Steps 7–8.

- `data-table`, `kpi`, and `chart` kits; `recharts`;
  `table-export.ts` extraction; the decision-8 `currency_code`
  addition; Google Ads adapters — report table with chart⇄table
  toggle, accounts hierarchy list, campaign-status approval card
  (write banner) + per-campaign result view.
- **Gate**: `pnpm check` + kit/presenter tests green; a report
  fixture renders currency/percent/date cells correctly formatted and
  the truncation note; a mixed-success mutation fixture renders
  per-campaign statuses; backend suite green for the `currency_code`
  addition.
- **Review focus**: micros conversion only at display time; framed
  cells unwrapped with container-level provenance; chart series parse
  numerically or are excluded (never coerced); CSV export contains
  unwrapped display values, not raw frames; the approval card cannot
  weaken or bypass the approval flow (it renders the same controls
  contract).

### Slice D — Airtable records + checklist closure (`Web - Airtable Record UI`)

Blocked on 041 Slice C. Step 9.

- Airtable record/field-table adapters over the kits (verify the
  landed payload shapes first); packaging §8 checklist amendment;
  FOLLOW_UPS entries; `000_README.md` row updated (plan-level done).
- **Gate**: `pnpm check` green; the decision-10 checklist line is in
  the packaging note.

## Steps

### Step 1: Frame display contract

Implement `src/lib/untrusted-frames.ts`: split a string into ordered
spans of plain text and `{ content, sourceKind, sourceRef }` frames by
scanning for the exact vocabulary
(`<<<PRAXIS_UNTRUSTED_CONTENT source_kind="..." source_ref="...">>>` …
`<<<END_PRAXIS_UNTRUSTED_CONTENT>>>`). Forgiving by construction:
unterminated frames yield the remainder as frame content; attribute
parse failure yields kind/ref `null`; neutralized forged markers
(`PRAXIS_UNTRUSTED-CONTENT`) are plain text. Export a scalar helper
(`unwrapFramedValue`) for the per-cell case (decision 3).

Record the decision-3 deviation in packaging §5.3 and threat-model §3
(one sentence each: the vocabulary is also a display contract; both
sides pin it).

**Verify**: unit tests — round-trip of a server-produced frame
(fixture string copied from a backend test's actual output, so drift
breaks a test), forged markers inert, unterminated frame safe,
multi-frame strings ordered correctly, scalar unwrap.

### Step 2: Kit substrate

Create `src/components/tool-ui/` with this slice's kits:

- `external-content.tsx` — the provenance container: distinct
  background, provenance chip built from `sourceKind`/`sourceRef`
  (chip is visibly data, not chrome), content as plain text
  (`white-space: pre-wrap`) — never through markdown (a hostile body
  must not gain formatting-based authority); preview/expand beyond
  ~480 chars.
- `fan-out-shell.tsx` — narrows `{results: [...]}` payloads
  (`status`, `display_name`, `external_id`, `error_message` per
  entry), renders per-entry sections, the mixed-outcome summary, the
  failed-entries block, empty state, and metadata strip. Exports the
  entry-narrowing type guard adapters reuse.
- `message.tsx` — `MessageListRow` (sender, subject, relative date,
  snippet, action slot) and `MessageDetail` (header grid with address
  chips, body slot, action row).
- `approval-card.tsx` — extract `ToolApprovalCard`,
  `ApprovalRequestFields` (the editable-field engine), and
  `ApprovalFooter` from `features/conversations/components/` into the
  kit space, preserving the `ToolApprovalDecisionControls` contract;
  `ApprovalDecisionBlock` becomes a thin `features/` consumer.

Amend `.dependency-cruiser.cjs`: rule 1 allowlist gains
`^src/components/tool-ui`; new rule — `^src/components/tool-ui` may
import only `^src/components/ui` and `^src/lib`. Record the amendment
in packaging §5.5.

**Verify**: kit unit tests (fixtures for mixed fan-out, empty results,
malformed entries → shell returns null); existing conversation/
approval tests pass unchanged; `pnpm check` (cruiser rules) green.

### Step 3: Gmail presenters

In `src/integrations/gmail/`, one adapter+presenter per tool, matching
on `activity.name`, each guarding its payload shape and returning
`null` on mismatch so the default row takes over:

- `gmail_search_messages` → `fan-out-shell` + `MessageListRow` per
  message: sender, subject (frame-unwrapped), relative date, snippet;
  mailbox header when multiple entries; per-row "Open in Gmail".
- `gmail_read_message` → `MessageDetail`: header block, body in
  `external-content` (frame-parsed), truncation notice when
  `truncated`, "Open in Gmail", "Reply" prefill (decision 6), and —
  after Slice B — "View full email".
- `gmail_send_message` → when `approvalDecision` is present, an
  email-shaped approval card composed from `approval-card` primitives
  (To/Subject/Body laid out as a message, editable per the existing
  `ToolUiField.editable` flags); after completion, a compact "sent"
  row with the message id as an Open-in-Gmail link.

Compose in `index.ts`; `registry.ts` needs no change (loaders already
exist).

**Verify**: vitest presenter tests with transcript-shaped fixtures
(success, partial fan-out failure, forged markers, unexpected shape →
null, approval card renders + approve/decline controls fire);
`pnpm check` green.

### Step 4: Preview seam (engine)

- `plugin.py`: `IntegrationPreviewDefinition(kind, fetch)` +
  `previews: tuple[...] = ()` on the plugin; loader validates kinds
  are unique, `^[a-z][a-z0-9_]*$`, and prefixed with the provider key.
- Preview service: resolve connection (workspace-scoped, 404 outside),
  resolve the provider's loaded plugin, find the kind, mint
  credentials via the existing seam, call `fetch`, sanitize `html`
  payloads with the `nh3` helper, enforce a response size cap
  (settings: `INTEGRATION_PREVIEW_MAX_BYTES`, default 2MB), emit the
  audit event, return the payload. Never store anything.
- Route per decision 4, response model
  `IntegrationPreviewRead(kind, content_type, content, meta)`.

**Verify**: route tests — auth required, cross-workspace 404, unknown
kind 404, size cap enforced, audit row written with
`operation="preview_gmail_message"` and no content; import-law test
still green.

### Step 5: Gmail preview operation

`integrations/gmail/operations/preview_message.py`: `messages.get
(format=full)`, extract the `text/html` part (fall back to `text/plain`
via `content_type="text"`), return payload with `meta` = sanitized
header summary (from/to/subject/date). Register `("gmail_message",
fetch)` on `PROVIDER.previews`. The operation returns RAW html —
sanitization is engine-owned (Step 4), so a provider can never opt out
of it.

**Verify**: MockTransport tests — HTML part extracted, plain-text
fallback, hostile fixture passes through the *service* and comes out
sanitized (fixture asserts script/handler/form/meta-refresh/
javascript:-URL removal, anchor hardening, and that the tracking-pixel
img survives as an https img for the client-side blocking layer to
handle).

### Step 6: HTML email view (web)

`message-preview.tsx`: fetch on demand (TanStack Query, no persistence
beyond cache), render via `<iframe sandbox="" srcDoc>` with injected
CSP meta per decision 5, fixed max-height with internal scroll,
loading/error states, "Load remote images" toggle re-rendering with
the widened `img-src`. Wire into the read presenter. Add the
threat-model section + fixture file reference (Steps 4/5 created the
fixture).

**Verify**: component tests assert the iframe has `sandbox=""` (empty,
not merely present) and the CSP meta is injected; `make check` green.

### Step 7: Data-table, KPI, and chart kits

- `table-export.ts`: extract copy-TSV/copy-CSV/download-CSV from
  `markdown-table.tsx`; `MarkdownTable` consumes it (behavior
  unchanged).
- `data-table.tsx`: `DataColumn { key, label, kind, align?, isMetric?,
  currencyCode?, format? }`; cell formatters per decision 2 (currency
  from micros when the column key matches `*_micros` and a
  `currencyCode` is present; percent auto-×100 when ≤1; locale
  numbers; status-tone badges — enabled/active → success,
  paused/pending → warning, removed/failed → danger; ids as `<code>`;
  link cells as hardened external anchors); zebra rows; totals footer
  (sums of numeric metric columns, opt-in); truncation footer;
  export actions; row click → detail `Sheet` with a two-column field
  grid derived from the columns.
- `kpi.tsx`: stat-card strip with tone borders.
- `chart.tsx`: the decision-7 `recharts` wrapper (bar | line) +
  `ChartTableToggle`.

**Verify**: kit unit tests — formatter matrix (micros/percent/date/
status/id/link), totals correctness, CSV export emits unwrapped
values, toggle switches without losing table state; `pnpm check`
green (knip accepts recharts).

### Step 8: Google Ads adapters + `currency_code`

Backend (small): `operations/run_report.py` adds `currency_code` (from
the target resource's discovered metadata) to each per-account `data`
dict (decision 8); extend the operation's tests.

`src/integrations/google_ads/`:

- `google_ads_run_report` → column derivation from the row key paths
  (`metrics.*` → metric/number, `*_micros` → currency,
  `metrics.ctr`/`*_rate` → percent, `segments.date` → date,
  `*.status` → status, `*.id`/`*.resource_name` → id, else text);
  cells unwrapped per decision 3 with container-level provenance;
  `data-table` + auto-derived `chart` behind the toggle; truncation
  note surfaced; per-account sections via `fan-out-shell`.
- `google_ads_list_accounts` → indented hierarchy list
  (parent-linked), manager/status/writable badges, currency code.
- `google_ads_update_campaign_status` → approval card with a
  write-operation banner ("This changes live campaign delivery"),
  campaign-id list, the editable ENABLED/PAUSED select (existing
  presentation flags); result view with a succeeded/failed KPI strip
  and per-campaign status badges + inline `campaign_errors` messages.

**Verify**: presenter tests — report fixture (framed cells, micros,
date dimension → line chart offered), no-date fixture (bar), mixed
mutation fixture, hierarchy fixture; backend test for
`currency_code`; `pnpm check` + backend suites green.

### Step 9 (Slice D): Airtable adapters, checklist closure

Verify the landed Airtable payload shapes first (041 Slice C), then:
`airtable_list_records`/`airtable_get_record` → record cards with
field tables (field-name/value grid; framed field values through
`external-content`'s scalar treatment; long text expandable);
`airtable_create_record`/`airtable_update_record` → approval card
listing the fields being written, result row with the record id.
Amend packaging §8 with the decision-10 checklist line. Record
FOLLOW_UPS (labels/threads/attachments, user-direct actions, micros
pre-conversion, further chart variants, tool playground). Update the
`000_README.md` status row.

**Verify**: `pnpm check` + presenter tests; packaging note updated.

## Test plan

Pinned invariants: **no raw framing markers ever render** (fixture
copied from real backend output so vocabulary drift fails CI), **forged
markers render inert**, **presenters and kits fail open to the default
row** (bad payload → null, never a crash), **the approval-card
extraction changes zero approval semantics** (existing approval tests
unchanged), **preview HTML is sanitized server-side AND rendered
script-less in an opaque-origin sandbox** (both layers asserted
independently), **remote images blocked by default**, **preview access
is workspace-scoped and audited without content**, **micros/percent
conversion is display-only** (model-visible payload byte-identical
except `currency_code`), **CSV export never contains raw frames**,
**no new SSE/presentation vocabulary**, and **§4.6/§5.5 (as amended)
boundary rules pass mechanically**.

## Done criteria

- [ ] Gmail search/read/send render through kit-based presenters; zero
      raw markers in a seeded transcript; default row still renders
      when a module chunk fails to load
- [ ] "View full email" renders sanitized HTML in a script-less
      opaque-origin iframe with remote images blocked by default
- [ ] Preview route: scoped, size-bounded, audited (refs only),
      nothing persisted
- [ ] Reply prefill flows into the composer; send still requires
      approval (no policy change anywhere in the diff)
- [ ] Google Ads reports render as formatted tables with currency/
      percent/date cells, totals, truncation note, CSV export, detail
      sheet, and a chart⇄table toggle; campaign mutations show an
      explicit write banner at approval and per-campaign outcomes
      after
- [ ] Airtable records render as field tables (Slice D may trail 041
      Slice C — mark partial status accordingly)
- [ ] `src/components/tool-ui/` exists with cruiser rules pinning its
      imports; provider modules contain adapters only (no kit logic)
- [ ] Threat model has the browser-rendering section + hostile HTML
      fixture; packaging note carries the §5.3 deviation, the §5.5
      amendment, and the §8 checklist line
- [ ] FOLLOW_UPS records user-direct actions, attachments/labels/
      threads, micros pre-conversion, and chart growth as explicitly
      deferred
- [ ] `make check` green; `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Rendering rich results seems to require changing tool
  `output_model`s beyond decision 8's single `currency_code` field,
  dispatch framing, truncation bounds, or adding SSE event types /
  presentation field formats — that is platform scope this plan
  explicitly bounded.
- The preview seam seems to need to persist provider content, or to
  feed preview responses into model context — both are design
  violations, not implementation details.
- The approval-card extraction cannot preserve the existing controls
  contract and approval tests — reconcile before restructuring
  anything else.
- `nh3` is unacceptable as a dependency and the fallback is hand-rolled
  HTML sanitization — never hand-roll; report instead. Same for
  `recharts`: if it is rejected, stop rather than hand-rolling SVG
  charts or picking a substitute unilaterally.
- The frame vocabulary in `untrusted.py` changed since 2026-07-22 —
  reconcile decision 3's two-sided contract first.
- The §5.5 amendment (a `src/components/tool-ui` import lane) is
  rejected in review — the kit architecture depends on it; do not
  smuggle kits into `src/components/ui` or duplicate them per
  provider.
- You feel the need to build inbox navigation, unread state, message
  listing outside tool activity, UI-direct tool invocation, or any
  user-direct write — scope leak toward "email client"/"ads console",
  which this plan is not.

## Maintenance notes

- **Provider N+1**: adapters and preview kinds live in the provider's
  own packages (`apps/api/integrations/<key>/` +
  `apps/web/src/integrations/<key>/`); the engine surface (kits,
  route, sanitizer, frame parser) never grows per provider. A provider
  needing a new kit, a new column kind, a new `content_type`, or a new
  engine behavior is a platform review, not a package change.
- **Kit ownership**: `src/components/tool-ui/` is engine code with the
  same review bar as `features/conversations` — changes there affect
  every provider at once. Keep kits payload-shape-agnostic: they take
  narrowed props, never `unknown` activity objects (narrowing is the
  adapter's job).
- **Reviewers should scrutinize**: sandbox attributes on every iframe
  touching provider content (empty `sandbox`, no `allow-same-origin`),
  sanitizer allowlist changes, any path where preview content could
  reach logs/audit/model context, that provenance chips are visually
  distinct from app chrome (a frame must not be stylable into looking
  like a system message), that adapters guard payload shapes rather
  than trusting them, and that display-time conversions (micros,
  percent) never leak back into model-visible payloads.
