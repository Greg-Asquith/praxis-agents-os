# Plan 041b: Rich provider tool UI — structured untrusted content, presenter kits, safe content preview

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
> whose _enforcement point_ this plan moves per decision 3). The notes
> win over this plan if they diverge — except where a decision below
> explicitly amends a note, in which case the amendment lands in the
> note in the same slice.
>
> **Sibling-plan pre-flight**: 041 Slice A (Gmail provider) and 042
> (integrations UI, including the `src/integrations/` lazy-module seam)
> must be DONE. Slice D of this plan requires 041 Slice B (Google Ads —
> in progress on `main` as of 2026-07-22, package present uncommitted);
> Slice F requires 041 Slice C (Airtable). Do not start a slice before
> its provider lands.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH (Slice A rewires how untrusted content reaches
  model context — a framing gap there is a prompt-injection regression;
  Slice C renders attacker-authored email HTML in the operator's
  browser — a sanitization gap is an XSS against the workspace session.
  Treat both like auth surfaces)
- **Depends on**: 041 Slice A (hard, DONE), 042 (hard, DONE); Slice D
  only: 041 Slice B; Slice F only: 041 Slice C
- **Category**: Phase 4a integrations (packaging note §2 principle 2,
  §5.2–5.5; threat-model §3/§4)
- **Execution progress**: Slices A–B **DONE 2026-07-22**. Slice A
  delivered structured provenance nodes, prompt-assembly framing,
  provider schema retyping, and persistence/SSE/model-request coverage.
  Slice B delivered the shared tool UI kits and Gmail search/read/send
  presenters, including stable call/result rendering and bounded inbox lists.
  Slice C is **DONE 2026-07-23**: the preview backend, automatic
  read-message HTML rendering, and search-row drill-in are complete.
  Slice D is **DONE 2026-07-23**: the shared data-table and KPI kits,
  Google Ads report and account presenters, governed campaign-status
  presenter, discovered-account currency propagation, and production
  presenter registration are complete. Google Ads results remain ordinary
  typed values with no model-side untrusted framing or legacy-result decoder,
  per operator decision. Slices E–F remain TODO.
  Execution corrected one landed-state mismatch found during pre-flight:
  Gmail read results carried an undeclared duplicate body field, which is now
  removed. A later 2026-07-23 operator decision explicitly exempted all Google
  Ads tool results from model-side untrusted framing; report values remain
  ordinary typed tool data.
  **2026-07-23 operator-review pass**: Slice C's backend (preview route,
  `nh3` sanitization, audit, hostile-fixture tests) landed with four
  operator amendments: (1) the read presenter renders the full HTML email
  **automatically** (plain-text tool result as instant fallback), not
  behind a "View full email" click; (2) **remote images load by default**
  — fidelity over tracking-pixel posture (threat-model §6 records this;
  scripts remain never-runnable); (3) preview `meta` carries Gmail
  **labels and thread size**, shown as chips — the model-visible tool
  result is unchanged; (4) the Gmail "Reply" action and its tool-row
  instruction dispatcher were removed after security review. Operators
  compose replies themselves in the conversation input, so provider
  metadata is never promoted into a user instruction by the UI.
  Search-row drill-in opens a viewport-centred popover and fetches the
  selected message on demand. The same pass fixed rich-row latency:
  deferred-tool
  resume events now stream live (finalize replay only covers ids that
  never streamed), transcript rows absorb live results instead of
  lingering as skeletons, live/transcript tool rows deduplicate,
  integration UI modules preload at conversation-workspace mount, and
  provider keys resolve from tool-name prefixes so presenter dispatch
  no longer waits on the presentations query.
- **Planned at**: 2026-07-22, tree with 041 Slice A present.
  **Rewritten 2026-07-22** after a donor-app parity review: per-provider
  one-off presenters were replaced by engine-owned **presenter kits**
  (the donor's "family renderer" architecture). **Rewritten again
  2026-07-22** after operator review, which took four decisions the
  first rewrite got wrong: (1) the untrusted-frame vocabulary stays
  **model-only** — instead of teaching the client to parse frames, the
  backend stores structured untrusted nodes and renders frames only at
  prompt-assembly time (decision 3, amending 041); (2) the preview
  seam is a **generic engine route with provider-contributed handlers**
  so provider code does not enter the central route tree (decision 4);
  (3) Gmail search
  results get **click-to-open drill-in** to the full message, the
  donor's flagship inbox interaction (decision 6); (4) **charts move
  to a trailing slice** so the trust-critical report table is not
  gated on a chart library review (decision 7). The donor sets the
  _richness benchmark_; its _mechanisms_ are adopted only where they
  fit our packaging and threat-model posture — rejections are recorded
  in "Donor patterns deliberately rejected" so they are not
  re-proposed. **Re-baselined 2026-07-23** against the landed Slice B–C
  code before starting Slice D: kit names/mechanics updated to what
  actually shipped (see "As landed" under decision 2 and the amended
  "Current state"), the approval opt-in flag (`handlesApprovals`) and
  five-state write-tool rendering were folded into Steps 8/10, and four
  operator decisions were taken: (1) the campaign-mutation write
  warning is the approval card's existing `prompt` line with strong
  copy — no new banner slot in the kit; (2) Google Ads customer and
  campaign ids ARE shown to the operator (they are business-meaningful
  ids the operator uses in the Ads console — unlike Gmail message ids,
  which stay hidden; internal refs like `resource_names` stay hidden);
  (3) Slice D ships the full data-table featureset (totals, CSV
  export, row detail sheet), not a lean first pass; (4) Slice E
  (charts) stays in the plan as trailing polish.

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
report, no affordance to reply, and nothing that generalizes to
Airtable records.

The root cause of the marker noise is upstream: dispatch renders
untrusted content into model-facing frame strings _before_ the result
is validated, persisted, and streamed (`dispatch.py:358`), so the
client inherits the model's view of the data. The frames are a prompt-
injection defense; they were never meant to be a display format.

The declarative default row was never meant to carry this either.
Principle 2 says the default row must render every tool _acceptably_,
and custom presenter rows are "opt-in polish for the few tools that
earn it (rich previews, domain widgets)". Email in a chat transcript
and ad-spend report tables are the canonical cases that earn it. The
donor app proves the ceiling: message lists that read like an inbox,
click-through to full HTML email, reports as formatted tables with
currency/percent cells, KPI strips, CSV export, row drill-downs,
editable approval cards, and per-account partial-failure summaries.
This plan builds that level of experience — through our seams, not the
donor's.

## Donor benchmark (what "rich" means here)

The donor (`saas-template` — see `apps/web/src/components/ai/tools/`
in that tree) renders ~10 providers richly from shared renderer kit
families; providers contribute only thin `adapt(output) → KitResult`
functions (e.g. the 46-line Ads report descriptor over the 554-line
`data-tables` kit). The experiences this plan commits to reproducing,
in our styles:

- **Gmail search** → an inbox-like list per mailbox: sender, subject,
  relative date, snippet, and **row
  click → full-message view** (the donor's `useMailDetailDialog`
  drill-in); fan-out entry headers when multiple mailboxes; inline
  error entries.
- **Gmail read** → an email header block (from/to/date/subject as
  address chips), the plain-text body in a provenance-marked external-
  content container with preview/expand, and a full-email HTML view in
  a hardened iframe. Reply composition remains in the conversation
  input; the presenter does not generate or send user instructions.
- **Gmail send** → an email-shaped approval card (To/Cc/Bcc/Subject/
  Body laid out as a message, editable fields wired to the existing
  approval-edit mechanism), then a compact "sent" confirmation row.
- **Google Ads report** → a real data table: kind-driven columns
  (currency from micros, percent, number, date, status badge, id),
  right-aligned `tabular-nums` metrics, zebra rows, a totals footer,
  truncation note, copy-CSV/download-CSV actions, row click → detail
  sheet; a chart⇄table toggle lands in the trailing chart slice.
- **Google Ads accounts** → the account hierarchy as an indented list
  with manager/status/writable badges.
- **Google Ads campaign mutation** → an approval card with an explicit
  write-operation banner, campaign list, and the editable
  ENABLED/PAUSED select; a result view with succeeded/failed counts
  and per-campaign status badges + inline error text (partial-failure
  first-class).
- **Airtable records** → field-table cards per record with
  field-type-aware value rendering.
- **Everywhere** → "N succeeded · M failed" fan-out summaries with a
  failed-entries block, **in-flight states** (running tool calls render
  skeleton rows / a labelled progress line, not a blank row — the
  donor ships a `progress.tsx` per kit family), empty states, metadata
  strips (provider · resource · counts · truncation), and provenance
  chips instead of raw markers.

## Decisions taken

1. **Two layers, strictly separated.**
   - _Layer 1 — presenter kits + adapters_: rich rendering of tool-
     result payloads; pure consumers of the shipped
     `IntegrationUiModule` seam. The only model-visible changes are
     decision 3's representation change (identical rendered bytes) and
     decision 8's narrow metadata addition.
   - _Layer 2 — on-demand content preview_: full HTML email is fetched
     **client-side, at view time** (automatically for the read
     presenter per the 2026-07-23 amendment; on row click for search
     drill-in), through a preview route — never by fattening tool
     results. The model-visible result deliberately
     excludes HTML (Gate G6 framing + truncation bounds); those
     constraints are not negotiable for UI convenience. Preview
     responses are ephemeral: never persisted, never entered into
     model context.
2. **Layer 1 is kit-based: engine-owned presenter kits, thin provider
   adapters.** This is the donor's highest-leverage pattern. A new
   engine-owned directory `apps/web/src/components/tool-ui/` holds
   shared renderer kits; provider modules under
   `src/integrations/<key>/` contain only `matches` guards and
   `adapt(activity) → KitProps | null` functions plus composition.
   Every kit renders three states: pending (skeleton/progress,
   driven by `activity.status` + `live`), success, and entry-level
   failure. The kits:
   - **`fan-out-shell`** — the universal envelope for
     `{"results": [entries...]}` payloads: per-entry sections keyed by
     resource `display_name`/`external_id`, a "N succeeded · M failed"
     summary when mixed, a failed-entries block rendering
     `error_message` inline, an empty state, a pending skeleton, and a
     metadata strip. Every provider presenter wraps in it.
   - **`external-content`** — the provenance container from decision
     3: distinct background, provenance chip built from the node's
     `source_kind`/`source_ref`, plain-text rendering
     (`white-space: pre-wrap`, never markdown), preview/expand for
     long bodies.
   - **`message`** — message list rows (sender/subject/date/snippet,
     action slot, optional `onSelect` for drill-in) and a message
     detail block (header grid, address chips, body via
     `external-content`, action row).
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
   - **`chart`** — decision 7's chart surface, added in Slice E only.

   **As landed (Slices B–C, verified 2026-07-23)** — Slices D–F build
   on these, not on the pre-execution names above:

   - `fan-out.ts` — `parseFanOutData<T>(result, parse)` narrows the
     `{results: [...]}` envelope and parses each success entry's
     `data` (any unparseable success entry → the whole parse returns
     null → default row). This, not a shell export, is the entry
     guard adapters reuse.
   - `fan-out-shell.tsx` — `FanOutShell` (per-entry cards, mixed
     "N Succeeded / M Failed" badges, empty state, `renderFailed`
     callback for failure bodies) and `FanOutSkeleton` (heading +
     summary props) for pending states. Each entry renders through
     `ToolResultCard`, so entries are collapsible and carry a
     Details popover fed by the `details: FanOutDetail[]` prop — the
     plan's "metadata strip" became this popover; do not build
     strips.
   - `result-card.tsx` — `ToolResultCard`: the collapsible section
     with heading, summary line, Details popover, and trailing badge
     slot. Single home for that pattern (the web-search row uses it
     directly); never re-implement its header/popover.
   - `approval-card.tsx` — the high-level `ToolApprovalDecisionCard`
     (declarative: `fields: ApprovalField[]` with
     key/label/format/editable/secondary/options, plus `title`,
     `prompt`, `approveLabel`, `icon`) over the lower-level
     `ToolApprovalCard`/`ApprovalRequestFields`. New approval
     presenters compose `ToolApprovalDecisionCard` as
     `gmail/send-presenter.tsx` does. Exports the shared
     `ApprovalDecision` type.
   - Field pipeline — `field-resolution.ts` (`resolveToolField(s)`,
     `safeHttpUrl`, formats text/multiline/markdown/bytes/datetime/
     boolean/url/list), `field-styles.ts`, `field-value.tsx`
     (`ToolFieldValue`). Prefer this for label/value grids before
     writing new kit code.
   - `untrusted-node.ts` (`isUntrustedNode`, `nodeText`),
     `external-content.tsx`, `message.tsx`, `source.tsx` — as
     specified.
   - Registry/contract — presenters are `ToolRowPresenter`
     objects (`key`, `matches`, `render`, optional
     `handlesApprovals`) composed in the provider's `index.ts`
     (`providerKey`, `toolRowPresenters`, `catalogDescription`,
     `icons`). The registry wraps each presenter in a try/catch +
     error boundary and only routes approval-state calls to
     presenters declaring `handlesApprovals: true`. Per-provider
     convention: `tool-details.ts` (Details-popover rows) and
     `tool-heading.tsx` (icon + title heading).

   **§5.5 amendment (recorded in the packaging note in the same
   slice)**: boundary rule 1 gains `^src/components/tool-ui` in the
   import allowlist for `^src/integrations`. Kits are engine-owned: a
   provider needing a new kit or a new column kind is a platform
   review, not a package change. `src/components/tool-ui` may import
   only `src/components/ui` and `src/lib` (a new cruiser rule pins
   this), so kits can never grow feature/route dependencies.

3. **Untrusted frames become model-only: structured nodes in storage,
   frames rendered at prompt-assembly time.** This amends 041's
   framing mechanics (not its posture — every model-visible untrusted
   byte stays framed). Today `dispatch.py:358` renders
   `UntrustedContent` carriers into frame strings before validation,
   persistence, and streaming, so the framed text is what the client
   receives. Operator decision: the frame vocabulary is a prompt-
   injection defense and must not leak into any other layer. New
   mechanics:
   - Dispatch serializes carriers into a tagged, JSON-serializable
     **untrusted node** (a small pydantic model in `untrusted.py`
     with an unmistakable discriminator field plus `source_kind`,
     `source_ref`, `content`; source components sanitized at mint
     time as today). Nodes are what get validated, persisted
     (`persistence.py` stores pydantic-ai messages verbatim), and
     streamed (`events.py:113,155` serialize `part.content` as-is).
   - An always-loaded, request-only **`model_request` wrapper** on the
     runtime hooks renders nodes inside `ToolReturnPart` content into
     the existing frame strings — including forged-marker neutralization —
     on every model request. The wrapper passes a copied request context to
     the provider and never replaces the agent's canonical history. A
     `ProcessHistory` capability was explicitly rejected during Slice A
     verification because its processed current-run tool returns become
     `new_messages()` and would therefore persist frames instead of nodes.
     The model-visible rendering is
     byte-identical to today's output; a test pins this against the
     pre-change fixture. Legacy history containing already-framed
     strings passes through untouched (the processor only transforms
     nodes), so old runs replay exactly as before.
   - Tool output models type untrusted-capable fields as
     `str | UntrustedNode` (provider packages already import from
     `services.agents.runtime.untrusted`).
   - The client receives structured nodes and renders them natively:
     a type guard in the kit space (`isUntrustedNode`) feeds
     `external-content` with `{content, sourceKind, sourceRef}`. **No
     general frame parser exists outside the request wrapper**.
   - **Google Ads exception (operator decision 2026-07-23)**: all
     Google Ads tool results remain ordinary typed values and do not
     enter the provenance-node or model-frame path. The data table
     shows one source label at container level ("External data ·
     Google Ads · account 123…") for operator context only.
   - **Legacy transcripts**: tool results stored before this slice
     contain framed strings. Gmail and other providers retain the
     pre-launch no-migration posture. Google Ads has no legacy-result
     compatibility path because its rich presenters replace the
     pre-launch results.
4. **Preview seam shape (Layer 2): a generic route with
   provider-contributed handlers.** Operator correction: the initial
   Gmail-scoped implementation put provider-specific route and service
   logic in the central integration tree, violating the packaging boundary.
   Use one route,
   `GET /api/v1/workspaces/{workspace_id}/integrations/connections/{connection_id}/previews/gmail_message?ref=...`
   with a dynamic `{kind}` segment. The engine resolves the visible
   connection, selects that provider's registered preview definition, and
   returns 404 when the kind is not contributed. Gmail owns the
   `gmail_message` fetch adapter in its package. Engine-owned auth
   (`require_read` + workspace membership + connection-in-workspace
   check, mirroring `routes/integrations/list_connection_resources.py`),
   engine-owned response size bound
   (`INTEGRATION_PREVIEW_MAX_BYTES`, default 2MB), and one audit event
   per preview via `record_integration_operation_audit_event`
   (operation `preview_gmail_message`, the user as actor, external ref
   = the `ref`; never content in audit details). The rationale bar for
   membership-level access: the same member already sees the full
   plain-text body in the transcript. The plugin contribution distributes
   provider fetching only; scoping, bounding, sanitization, and audit remain
   centralized.
5. **HTML safety is defense in depth, and scripts never run.**
   - _Server_: sanitize with `nh3` (new dependency, rust ammonia
     bindings — allowlist-based) before the payload leaves the API:
     strip `script`/`style` event handlers, forms, `object`/`embed`/
     `iframe`, `meta` refresh, and javascript: URLs; harden every
     anchor (http/https/mailto/tel only, `target="_blank"
rel="noopener noreferrer nofollow"`). The sanitized output is the
     only HTML the client ever receives.
   - _Client_: render in an opaque-origin `<iframe sandbox="" srcDoc>`
     (NO `allow-scripts`, NO `allow-same-origin` — stricter than both
     `FileContentView`'s `allow-scripts`
     (`file-content-view.tsx:29-38`, workspace-authored content) and
     the donor's `allow-same-origin` email frame, deliberately: email
     HTML is attacker-authored) with an injected
     `<meta http-equiv="Content-Security-Policy">` of
     restricting the frame to image loading only. **Amended by the
     2026-07-23 operator review**: remote images load by default
     (`img-src data: https:`) — fidelity over tracking-pixel posture,
     recorded in threat-model §6. Scripts remain never-runnable; the
     sandbox posture below is unchanged.
   - _Consequence accepted_: with an opaque origin the parent cannot
     measure the frame's content height (the donor's auto-height
     script requires `allow-same-origin`). The preview renders in a
     fixed `max-height` container with internal scroll. Do not weaken
     the sandbox to get auto-height.
   - _Threat model_: browser rendering of provider content is a new
     surface (§2's channel table is model-context only). This plan
     adds a new threat-model section for it with the mechanical
     defenses above and a hostile-HTML fixture (script, event handler,
     form, meta refresh, remote tracking pixel, javascript: link)
     asserted sanitized server-side; the fixture lives with the shared
     corpus directory.
6. **Drill-in everywhere the preview reaches; replies remain user-authored.**
   Search-result rows are clickable: row click
   opens a viewport-centred message popover that fetches the full message
   through the decision-4 preview route (the fan-out entry already carries
   `connection_id` and the message id) — the donor's flagship inbox
   interaction without row-dependent placement shifts. The read-message
   presenter has no Reply action and does
   not turn provider-authored sender or subject metadata into a user
   instruction. An operator who wants to reply types that request into
   the conversation input; any resulting `gmail_send_message` call still
   follows its approval-default policy. The approval card's editable
   fields (`ToolUiField.editable`, rendered by the extracted field
   engine) are the editing surface. No user-direct
   write path ships in this plan: direct actions (send-as-user,
   file/archive/label) require operations outside 041 decision 10's
   curated surface AND a new user-principal action category with its
   own envelope/audit story — record in `docs/plans/FOLLOW_UPS.md`,
   do not grow this plan. Operator-facing Gmail workflows remain inside
   Praxis; provider message ids stay implementation data and are not shown
   as technical provenance chips or external deep links.
7. **Charts: `recharts`, one wrapper, chart⇄table toggle — in a
   trailing slice.** Operator decision: the trust-critical fix is the
   table; the chart must not gate it. Slice E adds `recharts` (^2.x)
   to `apps/web` as the single chart dependency, wrapped once in the
   `chart` kit (`DataChart`: bar | line; themed via existing Tailwind
   tokens; abbreviated K/M axis ticks with currency/percent awareness;
   capped legend). `google_ads_run_report` presenters auto-derive a
   chart from the parsed table: line when a `segments.date` column is
   present, bar otherwise; up to 3 metric series; rendered behind a
   chart⇄table toggle with the table as the default view. Charts
   consume only numerically parsed node contents — a value that fails
   numeric parsing is excluded from charting, never coerced.
   Pie/combo variants, model-authored charts, and dashboards are out
   of scope (FOLLOW_UPS).
8. **Narrow, additive result-data enrichment — recorded, not
   forbidden.** The rule: _small additive metadata fields inside a
   provider `data` dict are allowed when they serve the model and the
   human alike and cost trivial tokens_; HTML, blobs, and anything
   that exists only for rendering stay excluded (that is what Layer 2
   is for). Under this rule, this plan makes exactly one addition:
   `google_ads_run_report` per-account `data` gains `currency_code`
   (from the discovered resource metadata) so both the model and the
   table formatter can interpret micros. Cell values stay raw GAQL
   micros in the model-visible payload; the data-table kit converts
   micros → currency units for display (`metrics.*_micros` →
   `value / 1e6`, `Intl` currency with `currency_code`). Whether the
   model-visible rows should pre-convert micros is a FOLLOW_UPS
   question, not this plan's. Any future addition under this rule is a
   provider-package change reviewed against it, one field at a time.
9. **No protocol growth.** No new SSE event types, no new
   `ToolFieldFormat` values, no `ToolPresentation` schema changes
   (packaging §2 principle 5). Column kinds, table rendering, charts,
   and provenance are entirely client-side interpretations of existing
   payloads (decision 3 changes the _representation_ inside existing
   `result` values — `unknown` end-to-end on the wire — not the
   protocol). Everything rides presenters, the kits, the one preview
   route, and the dispatch/request-wrapper change. The declarative
   default row remains the guaranteed fallback for every tool and must
   render untrusted nodes acceptably (node → its `content` text).
10. **The pattern is the deliverable.** Slices D and F apply the kits
    to Google Ads and Airtable as each 041 slice lands, and amend
    packaging §8 so the provider N+1 checklist asks the adapter
    question explicitly ("does any tool return content a human would
    want to _see_ rather than read about? If yes: which kits, and
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
  arrives only via the audited, ephemeral preview route (Layer 2).
- **Direct tool invocation from the UI** (donor's tool-catalog
  playground, direct-send forms, `inputSubmitsInternally`) — rejected
  for this plan; every write flows through the agent + approval
  governance (decision 6). The read-only preview fetch is the one
  sanctioned user-direct call, and it is scoped, audited, and
  ephemeral. A tool playground is a separate roadmap conversation.
- **Provider logic in shared modules** (the donor's descriptor cache,
  per-provider branches in shared renderers) — rejected; kits are
  generic, adapters live in provider packages, boundaries are
  machine-enforced (§5.5 as amended). Preview fetching follows the same
  rule through provider-contributed definitions.
- **Micros pre-converted server-side for display** — deferred
  (decision 8): the model-visible contract keeps raw GAQL values;
  conversion is a display concern until FOLLOW_UPS decides otherwise.
- **Threads, labels, unread state, attachments in Gmail rows** — the
  041 decision-10 curated surface doesn't return them
  (`GmailMessageSummary` carries sender/to/subject/date/snippet only,
  `integrations/gmail/tools/schemas.py:11-18`), so the UI does not
  fake them. The message kit is designed so label chips/attachment
  rows slot in when a later plan widens the surface (FOLLOW_UPS).

Plan-internal rejection, same purpose: **teaching the client the frame
vocabulary** (the first rewrite's `untrusted-frames.ts` parser and
two-sided "display contract") — rejected by operator decision 3. The
frames are prompt hygiene; anything that needs the content outside
model context consumes the structured node.

## Why this matters

The target operator is non-technical. A tool row that prints framing
markers and JSON-shaped text reads as broken, and "the agent found the
email but you cannot look at it" — or "the agent pulled your spend
report but it renders as chips" — kills trust in the whole integration
story at first contact. This is also the moment to set the pattern:
Gmail and Google Ads are the first providers a real user connects, and
every later provider (Drive, Sheets, Meta, Microsoft) maps onto the
same few kits: messages, tables, records, charts. Getting the seam
right once — structured content with provenance instead of display-
parsed markers, engine-owned kits, provider-owned adapters, ephemeral
audited preview for anything heavy — is what keeps principle 2 true as
the catalog grows: the default row stays the floor, the kits become
the affordable ceiling, and bespoke one-off UI stays exceptional.

## Current state

Anchors verified 2026-07-22.

- **Framing pipeline (backend)**: operations mint `UntrustedContent`
  carriers (`integrations/gmail/operations/utils.py:22-23`,
  `integrations/airtable/operations/utils.py:22`); dispatch renders
  them to frame strings at `services/agents/runtime/dispatch.py:358`,
  _before_ `validate_output` (360) and `truncate_result` (378 —
  structured results are exempt from truncation); the framed result is
  what pydantic-ai receives, so it flows into run history. History is
  persisted verbatim (`persistence.py:45,225`,
  `ModelMessagesTypeAdapter`) and replayed as `message_history` on
  later runs (`execute/setup.py:255-257`). SSE serializes
  `part.content` as-is (`events.py:113,155`,
  `_public_function_tool_result`). Frame vocabulary + neutralization:
  `untrusted.py:10-13,63-79` (note the rendered opening frame is
  `<<<PRAXIS_UNTRUSTED_CONTENT>>> source_kind="..." source_ref="...">>>`
  — the START constant plus attributes plus a second `>>>`). The
  runtime agent already has a `ProcessHistory` trimmer assembled in
  `services/agents/runtime/capabilities.py`; the same always-loaded hooks
  capability is the request-only framing seam. The single construction point
  is `services/agents/runtime/loop.py` (`PydanticAgent(...)`) — delegate
  runners build through the same helper. `evals/run.py` also touches
  `ToolReturnPart` — check for framed-string assumptions in Slice A.
- **Frontend seam (042, delivered)**: `apps/web/src/integrations/
contract.ts` — `ToolRowPresenterProps` (lines 13-20: `activity`,
  `approvalDecision?`, `compact`, `defaultOpen`, `live`,
  `providerKey`), `ToolRowPresenter` (22-26), `IntegrationUiModule`
  (28-33). `registry.ts` — `MODULE_LOADERS` (11-15),
  `integrationToolRowPresenters` (24-29), `useIntegrationUiModule`
  (41). All three provider modules are bare stubs exporting only
  `providerKey`. `ToolActivity` carries `status` — presenters can
  render pending states.
- **Dispatch order (as landed)**: `tool-call-row.tsx` consults
  `renderCustomToolCallRow` (which appends integration presenters to
  the built-in list in `tool-call-row-registry.tsx`) BEFORE the
  approval short-circuit — but the registry only offers an
  approval-state call to a presenter that declares
  `handlesApprovals: true`; presenters without the flag fall through
  to the default approval UI. A presenter that throws is logged and
  skipped (try/catch per presenter + error boundary), and the
  declarative default row is the fallback for every tool.
- **Approval machinery (as landed)**: the shell and editable-field
  engine were extracted into `components/tool-ui/approval-card.tsx`
  (`ToolApprovalDecisionCard`, `ToolApprovalCard`,
  `ApprovalRequestFields`, `ApprovalField`, `ApprovalDecision`,
  `ToolApprovalDecisionControls`); the former
  `approval-decision-fields.tsx` and `tool-approval-card.tsx` in
  `features/conversations/components/` are deleted.
  `approval-decision-block.tsx` remains in `features/` as the default
  consumer, and `approval-decisions.ts` imports `ApprovalDecision`
  from the kit. Presenters import the kit directly — the decision-2
  extraction is DONE.
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
  `error_message`). Untrusted-capable fields are typed `str` today —
  they hold framed strings at validation time; decision 3 retypes
  them. The HTML body never reaches the transcript — by design
  (`read_message.py` strips HTML, caps at 50k).
- **Google Ads payloads (041 Slice B, in progress on `main`,
  uncommitted — verify at execution)**: client pinned to v24
  (`client.py:12`). `google_ads_run_report` per-account `data` =
  `{rows, row_count, truncated, truncation_note}` with ordinary typed
  values under the explicit Google Ads model-framing exception;
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
  one in Slice E).
- **Route/auth precedent**:
  `routes/integrations/list_connection_resources.py` (require_read +
  workspace + connection scoping); audit precedent
  `services/audit_events/integration_events.py::
record_integration_operation_audit_event` (041 Slice A). **No
  preview or on-demand-fetch route exists** —
  `routes/integrations/__init__.py` registers connect/context/
  discovery/connection-management routes only.
- **Boundary enforcement**: `.dependency-cruiser.cjs` rules for
  `src/integrations` (§5.5); `tests/integrations/test_import_laws.py`
  for the backend (§4.6).

## Commands you will need

| Purpose        | Command                                                                                                                                                | Expected on success                         |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------- |
| Backend lint   | `cd apps/api && uv run ruff check .`                                                                                                                   | exit 0                                      |
| Backend tests  | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/integrations tests/services/integrations tests/routes/integrations tests/services/agents -q` | all pass                                    |
| Frontend gate  | `cd apps/web && pnpm check`                                                                                                                            | exit 0 (includes dependency-cruiser + knip) |
| Frontend tests | `cd apps/web && pnpm test`                                                                                                                             | all pass                                    |
| Full gate      | `make check`                                                                                                                                           | exit 0                                      |

## Scope

**In scope:**

- `apps/api/services/agents/runtime/untrusted.py` (extend — the
  serializable `UntrustedNode` + node→frame rendering),
  `dispatch.py` (serialize instead of frame), `loop.py` (history
  processor), provider output schemas (`str | UntrustedNode` fields)
  — decision 3
- `apps/web/src/lib/table-export.ts` (extract from
  `markdown-table.tsx`)
- `apps/web/src/components/tool-ui/` (create) — the decision-2 kits
  (`fan-out-shell`, `external-content`, `message`, `data-table`,
  `kpi`, `approval-card` + the relocated editable-field engine;
  `chart` in Slice E) with tests, including the `isUntrustedNode`
  guard and pending-state rendering
- `.dependency-cruiser.cjs` — the §5.5 amendment (integrations may
  import `^src/components/tool-ui`; tool-ui may import only ui/lib)
- `apps/web/src/integrations/gmail/` (fill): search/read/send
  adapters + presenters, `message-preview.tsx` (sandboxed HTML view +
  centred search-result popover), `index.ts` composition
- `apps/web/src/integrations/google_ads/` (fill, Slice D): report
  table adapter, accounts list adapter, campaign-status
  approval/result adapter; chart derivation in Slice E
- `apps/web/src/integrations/airtable/` (fill, Slice F): record
  field-table adapters
- `apps/web/src/features/conversations/components/` — extraction
  refactor only (decision 2); `ApprovalDecisionBlock` keeps its
  public behavior; default row renders nodes as their content text
- `apps/web/package.json` — `recharts` (Slice E only)
- `apps/api/routes/integrations/` + `services/integrations/` — the
  decision-4 generic preview route, dispatch, and engine-owned enforcement
- `apps/api/services/integrations/plugin.py` — preview contribution contract
- `apps/api/integrations/gmail/operations/preview_message.py`
- `apps/api/integrations/google_ads/operations/run_report.py` — the
  decision-8 `currency_code` addition (Slice D)
- `nh3` dependency in `apps/api/pyproject.toml`; server-side
  sanitization helper (engine-owned, not provider-owned)
- `docs/architecture/threat-model.md` (framing enforcement-point
  amendment per decision 3; new browser-rendering section + fixture),
  `docs/architecture/integration-packaging.md` (§5.5 amendment per
  decision 2; §8 checklist line per decision 10)
- Tests: framing-equivalence + persistence/SSE node tests; kit unit
  tests; presenter/adapter tests per provider; XSS/sanitization
  tests; backend preview auth/audit tests

**Out of scope (do NOT touch):**

- Tool `output_model` _values_ beyond decision 3's type change and
  decision 8's single `currency_code` field; truncation bounds; the
  rendered model-visible framing bytes (must stay identical)
- New Gmail/Ads/Airtable operations beyond the preview fetch (no
  labels, archive, drafts, attachments, threads — FOLLOW_UPS)
- User-direct write actions or UI-direct tool invocation of any kind
  (decision 6; rejected-patterns list)
- SSE protocol, `ToolPresentation`/`ToolFieldFormat` vocabularies,
  approval resume contract
- Data migration of legacy framed transcripts (decision 3 accepts
  them)
- Notifications, unread badges, or any inbox-like standalone surface —
  this plan renders tool activity, it does not build an email client
- Dashboards, saved reports, model-authored charts (FOLLOW_UPS)

## Git workflow

- Branch: `advisor/041b-rich-provider-tool-ui`
- Commits: one per execution slice below. Do NOT push or open a PR
  unless the operator instructed it.

## Execution slices

### Slice A — Structured untrusted content (`Cross - Structured Untrusted Content`)

Decision 3; backend only. Step 1. **Highest-risk slice — the framing
invariant moves; treat like an auth change.**

- `UntrustedNode` + dispatch serialization + request-only model wrapper +
  schema retyping + threat-model amendment.
- **Gate**: backend suites green, including the new
  framing-equivalence test (captured model request bytes identical to
  the pre-change framed rendering) and persistence/SSE tests (nodes,
  zero markers, for new runs); existing untrusted/framing tests
  updated in the same commit, never deleted.
- **Review focus**: every model request path (fresh run, replayed
  history, delegate runs, approval resume) passes through the
  processor; forged-marker neutralization happens at render time;
  legacy framed strings replay unchanged; no path serializes a raw
  `UntrustedContent` dataclass into storage.

### Slice B — Kit substrate + Gmail presenters (`Web - Tool UI Kits & Gmail Rows`) — DONE 2026-07-22

Layer 1; no backend change. Steps 2–3.

- `src/components/tool-ui/` with `fan-out-shell`,
  `external-content`, `message`, the `approval-card` extraction, and
  the `isUntrustedNode` guard; the §5.5 cruiser amendment; Gmail
  search/read/send presenters registered in `gmail/index.ts`;
  pending-state skeletons. Provider resource ids and external
  Gmail links remain hidden from the operator-facing surface.
- **Gate**: `pnpm check` + kit/presenter tests green; a transcript
  fixture with node payloads renders zero raw markers and correct
  provenance chips; a running-status fixture renders the pending
  state; `ApprovalDecisionBlock` behavior unchanged (existing
  approval tests still pass).
- **Review focus**: provenance chips are visibly data, not chrome;
  presenter fallback — any unexpected payload shape falls through to
  the default row rather than crashing (guard-and-return-null, error
  boundary at the presenter seam); the extraction did not alter
  approval semantics or the controls contract.

### Slice C — Gmail message preview + drill-in (`Cross - Gmail Message Preview`) — DONE 2026-07-23

Layer 2. Steps 4–6. Historical — landed with the operator amendments
recorded in the execution-progress note (automatic read-presenter
render, remote images on by default, labels/thread-size chips, no
Reply action).

- Generic preview service + Gmail provider contribution; `nh3`
  sanitization; audit;
  `preview_message.py`; web `message-preview.tsx` (sandbox="" iframe,
  CSP meta, remote-image toggle, fixed max-height) wired into BOTH
  the read presenter ("View full email") and search-row drill-in
  (decision 6); threat-model section + hostile HTML fixture.
- **Gate**: backend suites green including the sanitization fixture
  test and a cross-workspace 404 test; `pnpm check` green; manual QA
  with a real connection: search → click a row → HTML email renders
  with images blocked.
- **Review focus**: sanitizer allowlist (scripts/handlers/forms/
  javascript: URLs all stripped, anchors hardened), iframe has NO
  allow-scripts and NO allow-same-origin, preview responses are never
  persisted or logged, audit rows carry refs but never content,
  connection scoping cannot be bypassed by guessing ids, non-gmail
  connections 404.

### Slice D — Google Ads report UI (`Cross - Google Ads Report UI`)

Blocked on 041 Slice B. Steps 7–8. No charts here.

- `data-table` + `kpi` kits; `table-export.ts` extraction; the
  decision-8 `currency_code` addition; Google Ads adapters — report
  table, accounts hierarchy list, campaign-status approval card
  (strong approval prompt) + per-campaign result view.
- **Gate**: `pnpm check` + kit/presenter tests green; a report
  fixture renders currency/percent/date cells correctly formatted and
  the truncation note; a mixed-success mutation fixture renders
  per-campaign statuses; backend suite green for the `currency_code`
  addition.
- **Review focus**: micros conversion only at display time; report
  cells read as ordinary typed Google Ads values with container-level
  provenance; CSV export contains the raw values, never framing markers;
  the approval card cannot weaken or bypass the approval flow (it
  renders the same controls contract).

### Slice E — Report charts (`Web - Report Charts`)

Trailing polish on Slice D; ship after the table has been used.
Step 9.

- `recharts`; the `chart` kit (`DataChart` + `ChartTableToggle`);
  auto-derived chart for `google_ads_run_report` (line when
  `segments.date` present, bar otherwise, ≤3 metric series), table
  remains the default view.
- **Gate**: `pnpm check` green (knip accepts recharts); chart tests —
  date fixture → line offered, no-date fixture → bar, non-numeric
  cells excluded never coerced; toggle preserves table state.

### Slice F — Airtable records + checklist closure (`Web - Airtable Record UI`)

Blocked on 041 Slice C. Step 10.

- Airtable record/field-table adapters over the kits (verify the
  landed payload shapes first); packaging §8 checklist amendment;
  FOLLOW_UPS entries; `000_README.md` row updated (plan-level done).
- **Gate**: `pnpm check` green; the decision-10 checklist line is in
  the packaging note.

## Steps

### Step 1: Structured untrusted content (Slice A)

- `untrusted.py`: add `UntrustedNode` (pydantic `BaseModel`) with an
  unmistakable literal discriminator (e.g.
  `node: Literal["praxis_untrusted"]`), `source_kind`, `source_ref`,
  `content`. Add `serialize_untrusted_content(value)` (recursive walk
  as `frame_untrusted_content` does today, replacing carriers with
  nodes; source components sanitized at mint) and
  `render_untrusted_frames(messages)` — the request-wrapper transform
  that maps `ToolReturnPart` content, replacing nodes with the
  existing `_render_frame` output (including forged-marker
  neutralization of the node content at render time). Keep the frame
  constants and `_render_frame` unchanged so rendered bytes are
  identical.
- `dispatch.py:358`: call `serialize_untrusted_content` instead of
  `frame_untrusted_content`. `validate_output` and `truncate_result`
  now see nodes — retype untrusted-capable fields in
  `integrations/gmail/tools/schemas.py` (and Airtable's; Google Ads is
  explicitly exempt) as `str | UntrustedNode`; confirm structured
  results remain truncation-exempt as today.
- `capabilities.py`: register `render_untrusted_frames` in the always-loaded
  hooks capability's `model_request` wrapper, passing a copied request context
  to the provider so `new_messages()` retains nodes; confirm delegate/resume
  paths build through the shared runtime constructor.
- Check `evals/run.py` for framed-string assumptions; update in the
  same commit if present.
- Amend threat-model §3: framing is enforced at prompt-assembly time;
  storage and client-visible payloads carry structured provenance
  nodes; the vocabulary remains runtime-internal.

**Verify**: (a) framing-equivalence — a test tool returning
`UntrustedContent` through a captured-request model (pydantic-ai
`FunctionModel`/capture) produces a model-visible tool return
byte-identical to the pre-change framed fixture; (b) persisted
messages for the run contain nodes and zero frame markers; (c) the
SSE `tool.result` payload carries nodes; (d) a legacy history fixture
containing framed strings replays through the processor unchanged;
(e) forged markers inside node content are neutralized in the
rendered request but stored verbatim; (f) full backend gate green.

### Step 2: Kit substrate (Slice B)

Create `src/components/tool-ui/` with this slice's kits:

- `untrusted-node.ts` — the `isUntrustedNode` type guard + a
  `nodeText` helper (node → content string) shared by kits and the
  default row.
- `external-content.tsx` — the provenance container: distinct
  background, provenance chip built from `sourceKind`/`sourceRef`
  (chip is visibly data, not chrome), content as plain text
  (`white-space: pre-wrap`) — never through markdown (a hostile body
  must not gain formatting-based authority); preview/expand beyond
  ~480 chars.
- `fan-out-shell.tsx` — narrows `{results: [...]}` payloads
  (`status`, `display_name`, `external_id`, `error_message` per
  entry), renders per-entry sections, the mixed-outcome summary, the
  failed-entries block, empty state, metadata strip, and a pending
  skeleton when the activity is running. Exports the entry-narrowing
  type guard adapters reuse.
- `message.tsx` — `MessageListRow` (sender, subject, relative date,
  snippet, action slot, optional `onSelect`) and `MessageDetail`
  (header grid with address chips, body slot, action row), plus
  skeleton variants.
- `approval-card.tsx` — extract `ToolApprovalCard`,
  `ApprovalRequestFields` (the editable-field engine), and
  `ApprovalFooter` from `features/conversations/components/` into the
  kit space, preserving the `ToolApprovalDecisionControls` contract;
  `ApprovalDecisionBlock` becomes a thin `features/` consumer.

Update the declarative default row to render untrusted nodes as their
content text (via `nodeText`) so non-presenter tools degrade cleanly.

Amend `.dependency-cruiser.cjs`: rule 1 allowlist gains
`^src/components/tool-ui`; new rule — `^src/components/tool-ui` may
import only `^src/components/ui` and `^src/lib`. Record the amendment
in packaging §5.5.

**Verify**: kit unit tests (fixtures for mixed fan-out, empty results,
running status → skeleton, malformed entries → shell returns null);
default row renders a node fixture as plain content text; existing
conversation/approval tests pass unchanged; `pnpm check` (cruiser
rules) green.

### Step 3: Gmail presenters (Slice B)

In `src/integrations/gmail/`, one adapter+presenter per tool, matching
on `activity.name`, each guarding its payload shape and returning
`null` on mismatch so the default row takes over:

- `gmail_search_messages` → `fan-out-shell` + `MessageListRow` per
  message: sender, subject (via `nodeText`), relative date, snippet;
  mailbox header when multiple entries; bounded per-mailbox scrolling;
  `onSelect` slot wired in Slice C.
- `gmail_read_message` → `MessageDetail`: header block, body in
  `external-content` (node-fed), truncation notice when `truncated`,
  and — after Slice C — the automatic full-email preview. It exposes
  no reply automation; operators write reply requests in the composer.
- `gmail_send_message` → when `approvalDecision` is present, an
  email-shaped approval card composed from `approval-card` primitives
  (To/Subject/Body laid out as a message, editable per the existing
  `ToolUiField.editable` flags); after completion, a compact "sent"
  row without exposing the provider message id.
- Running-status activities render the kit skeletons ("Searching
  mailboxes…", header-only detail shell).

Compose in `index.ts`; `registry.ts` needs no change (loaders already
exist).

**Verify**: vitest presenter tests with transcript-shaped fixtures
(success, partial fan-out failure, running status, unexpected shape →
null, approval card renders + approve/decline controls fire);
`pnpm check` green.

### Step 4: Preview service + route (Slice C)

- Service under `services/integrations/`: resolve connection
  (workspace-scoped, 404 outside), dispatch `{kind}` through the visible
  connection provider's preview definitions, sanitize `html` payloads
  with the `nh3` helper,
  enforce `INTEGRATION_PREVIEW_MAX_BYTES` (default 2MB), emit the
  audit event, return
  `IntegrationPreviewRead(kind, content_type, content, meta)`. Never
  store anything.
- Route per decision 4 at
  `.../connections/{connection_id}/previews/gmail_message?ref=...` —
  `{kind}` is dynamic and resolves only against definitions contributed by
  the visible connection's provider.

**Verify**: route tests — auth required, cross-workspace 404, wrong
provider 404, size cap enforced, audit row written with
`operation="preview_gmail_message"` and no content; import-law test
still green.

### Step 5: Gmail preview operation (Slice C)

`integrations/gmail/operations/preview_message.py`: `messages.get
(format=full)`, extract the `text/html` part (fall back to `text/plain`
via `content_type="text"`), return payload with `meta` = sanitized
header summary (from/to/subject/date). The operation returns RAW html —
sanitization is engine-owned (Step 4), so a provider can never opt out
of it.

**Verify**: MockTransport tests — HTML part extracted, plain-text
fallback, hostile fixture passes through the _service_ and comes out
sanitized (fixture asserts script/handler/form/meta-refresh/
javascript:-URL removal, anchor hardening, and that the tracking-pixel
img survives as an https img for the client-side blocking layer to
handle).

### Step 6: HTML email view + drill-in (web, Slice C)

> Historical — Slice C is DONE. As landed, the read presenter renders
> the HTML view automatically (no "View full email" click) and remote
> images load by default; see the execution-progress amendments.

`message-preview.tsx`: fetch on demand (TanStack Query, no persistence
beyond cache), render via `<iframe sandbox="" srcDoc>` with injected
CSP meta per decision 5, fixed max-height with internal scroll,
loading/error states, "Load remote images" toggle re-rendering with
the widened `img-src`. Wire it twice: the read presenter's "View full
email" action, and search-row drill-in — row click opens a centred
`Popover` titled with the subject, fetching by the row's message id +
the entry's `connection_id` (decision 6). Add the threat-model section

- fixture file reference (Steps 4/5 created the fixture).

**Verify**: component tests assert the iframe has `sandbox=""` (empty,
not merely present) and the CSP meta is injected; a search fixture row
click opens the popover and issues exactly one preview fetch;
`make check` green.

### Step 7: Data-table + KPI kits (Slice D)

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
  grid derived from the columns; loading skeleton. The table is a
  body-slot component: it renders inside a `FanOutShell` entry card
  (which already provides the collapsible header, status badge, and
  Details popover) — it must not grow its own card chrome or
  metadata strip.
- `kpi.tsx`: stat-card strip with tone borders.

**Verify**: kit unit tests — formatter matrix (micros/percent/date/
status/id/link), totals correctness, CSV export emits node contents
(never marker text or node JSON); `pnpm check` green.

### Step 8: Google Ads adapters + `currency_code` (Slice D)

Backend (small): `operations/run_report.py` adds `currency_code` (from
the target resource's discovered metadata) to each per-account `data`
dict (decision 8); extend the operation's tests.

`src/integrations/google_ads/` — follow the landed Gmail module shape:
presenters composed in `index.ts` (`providerKey`, `toolRowPresenters`,
`catalogDescription`, `icons`), a `tool-details.ts` for
Details-popover rows, a `tool-heading.tsx` for the icon + title
heading, every presenter guarding via `parseFanOutData` and returning
null on mismatch:

- `google_ads_run_report` → column derivation from the row key paths
  (`metrics.*` → metric/number, `*_micros` → currency,
  `metrics.ctr`/`*_rate` → percent, `segments.date` → date,
  `*.status` → status, `*.id` → id, else text); cells consume ordinary
  typed values, with container-level provenance
  ("External data · Google Ads · account …"); `data-table` per
  account inside `FanOutShell` (per-account collapsible card +
  Details popover via the `details` prop); truncation note surfaced.
  Full featureset per the 2026-07-23 decision: totals footer, CSV
  export, row click → detail sheet.
- `google_ads_list_accounts` → indented hierarchy list
  (parent-linked), manager/status/writable badges, currency code.
- `google_ads_update_campaign_status` → presenter declares
  `handlesApprovals: true` (without the flag the registry never
  routes approval-state calls to it). When `approvalDecision` is
  present, render `ToolApprovalDecisionCard` with the campaign list
  and the editable ENABLED/PAUSED select (`ApprovalField` with
  `options`, matching the existing presentation flags) and the write
  warning as the card's `prompt` line with strong copy ("This
  changes live campaign delivery.") — per the 2026-07-23 decision,
  no new banner slot in the kit. Result view: succeeded/failed KPI
  strip and per-campaign status badges + inline `campaign_errors`
  messages.
- **Five lifecycle states for the write tool**, mirroring
  `gmail/send-presenter.tsx`: running and `awaiting_approval` →
  `FanOutSkeleton` with honest labels; `denied` → an explicit
  "declined, nothing was changed" body; `failed`/`unknown` → an
  unconfirmed-outcome body (never imply success); completed → the
  result view. Read-only tools need running + completed + fan-out
  failure only.
- **Id display**: customer ids and campaign ids ARE shown (code-style
  cells, detail views) — they are business ids the operator uses in
  the Ads console; this deliberately differs from Gmail, whose
  message ids are provider-internal and stay hidden. Internal refs
  (`resource_names`, integration resource ids, connection ids) stay
  hidden.

**Verify**: presenter tests — report fixture (typed cells, micros,
correct formatting), mixed mutation fixture, hierarchy fixture, PLUS
approval-card fixture (controls fire, status select edits), denied
fixture, failed/unknown fixture, awaiting/running skeleton fixtures;
backend test for `currency_code`; `pnpm check` + backend suites green.

### Step 9: Charts (Slice E)

`chart.tsx`: the decision-7 `recharts` wrapper (bar | line) +
`ChartTableToggle`. `google_ads_run_report` presenter derives the
chart from the parsed table (line when `segments.date` present, bar
otherwise, ≤3 metric series); table stays the default view.

**Verify**: chart tests per the Slice E gate; `pnpm check` green
(knip accepts recharts).

### Step 10 (Slice F): Airtable adapters, checklist closure

Verify the landed Airtable payload shapes first (041 Slice C — note
the fan-out `data` is a loosely-typed `dict[str, UntrustedJsonValue]`,
`integrations/airtable/tools/schemas.py`, so adapters must narrow
defensively), then:
`airtable_list_records`/`airtable_get_record` → record cards with
field tables (field-name/value grid; node field values through
`external-content`'s scalar treatment; long text expandable). Before
writing any new kit code, try composing the shared field pipeline
(`resolveToolFields` + `ToolFieldValue`) inside `FanOutShell` entry
cards — a new record-field kit is justified only if that composition
falls short.
`airtable_create_record`/`airtable_update_record` → presenters declare
`handlesApprovals: true` and render `ToolApprovalDecisionCard` listing
the fields being written; result row with the record id; the same
five-lifecycle-state coverage as Step 8's write tool (running /
awaiting_approval / denied / failed-unknown / completed, honest copy
for the non-success states).
Amend packaging §8 with the decision-10 checklist line. Record
FOLLOW_UPS (labels/threads/attachments, user-direct actions, micros
pre-conversion, chart variants, tool playground, preview-seam
generalization at provider #2). Update the `000_README.md` status
row.

**Verify**: `pnpm check` + presenter tests; packaging note updated.

## Test plan

Pinned invariants: **the model-visible framed rendering is
byte-identical to the pre-change output** (equivalence fixture),
**stored payloads and SSE payloads for new runs contain zero frame
markers** (nodes only), **legacy framed history replays unchanged**,
**forged markers are neutralized at render time and inert in the UI**,
**presenters and kits fail open to the default row** (bad payload →
null, never a crash) **and render pending states while running**,
**write-tool presenters cover all five lifecycle states with honest
non-success copy and declare `handlesApprovals`** (an approval-capable
presenter without the flag is a bug — the default approval UI would
show instead of the custom card),
**the approval-card extraction changes zero approval semantics**
(existing approval tests unchanged), **preview HTML is sanitized
server-side AND rendered script-less in an opaque-origin sandbox**
(both layers asserted independently, scripts never run; remote images
load by default per the 2026-07-23 amendment),
**preview access is workspace- and provider-scoped and
audited without content**, **micros/percent conversion is
display-only** (model-visible payload unchanged except
`currency_code`), **CSV export never contains marker text or node
JSON**, **no new SSE/presentation vocabulary**, and **§4.6/§5.5 (as
amended) boundary rules pass mechanically**.

## Done criteria

- [ ] Untrusted content is stored and streamed as structured nodes;
      frames exist only in rendered model requests; the equivalence
      test pins identical model-visible bytes
- [ ] Gmail search/read/send render through kit-based presenters with
      pending states; zero raw markers in a newly seeded transcript;
      default row still renders when a module chunk fails to load
- [ ] Search-row drill-in and the read presenter's automatic
      full-email view both render sanitized HTML in a script-less
      opaque-origin iframe (remote images load by default per the
      2026-07-23 amendment; scripts never run)
- [ ] Preview route: workspace- and provider-scoped, size-bounded,
      audited (refs only), nothing persisted
- [ ] Gmail read exposes no reply automation or provider-metadata-to-
      instruction path; operator-authored send requests still require
      approval (no policy change anywhere in the diff)
- [ ] Google Ads reports render as formatted tables with currency/
      percent/date cells, totals, truncation note, CSV export, and
      detail sheet; campaign mutations show an explicit write banner
      at approval and per-campaign outcomes after; charts land in
      Slice E behind the chart⇄table toggle
- [ ] Airtable records render as field tables (Slice F may trail 041
      Slice C — mark partial status accordingly)
- [ ] `src/components/tool-ui/` exists with cruiser rules pinning its
      imports; provider modules contain adapters only (no kit logic)
- [ ] Threat model carries the framing enforcement-point amendment and
      the browser-rendering section + hostile HTML fixture; packaging
      note carries the §5.5 amendment and the §8 checklist line
- [ ] FOLLOW_UPS records user-direct actions, attachments/labels/
      threads, micros pre-conversion, chart growth, and preview-seam
      generalization as explicitly deferred
- [ ] `make check` green; `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The Step 1 framing-equivalence test cannot be made to pass — i.e.
  moving framing to prompt-assembly changes any model-visible byte,
  or any request path (delegates, approval resume, replayed history)
  bypasses the request-only model wrapper. This is the prompt-injection
  invariant; do not ship a partial version.
- Retyping output-model fields to `str | UntrustedNode` breaks
  output-contract validation or truncation semantics in a way that
  needs new dispatch behavior — reconcile before touching truncation.
- Rendering rich results seems to require changing tool
  `output_model` _values_ beyond decisions 3 and 8, dispatch
  semantics beyond Step 1, truncation bounds, or adding SSE event
  types / presentation field formats — that is platform scope this
  plan explicitly bounded.
- The preview route seems to need to persist provider content, or to
  feed preview responses into model context — both are design
  violations, not implementation details.
- A provider preview requires bypassing the generic scoping, size,
  sanitization, or audit boundary — that is a platform change, not a
  provider branch.
- The approval-card extraction cannot preserve the existing controls
  contract and approval tests — reconcile before restructuring
  anything else.
- `nh3` is unacceptable as a dependency and the fallback is hand-rolled
  HTML sanitization — never hand-roll; report instead. Same for
  `recharts`: if it is rejected, stop rather than hand-rolling SVG
  charts or picking a substitute unilaterally.
- The §5.5 amendment (a `src/components/tool-ui` import lane) is
  rejected in review — the kit architecture depends on it; do not
  smuggle kits into `src/components/ui` or duplicate them per
  provider.
- You feel the need to build inbox navigation, unread state, message
  listing outside tool activity, UI-direct tool invocation, or any
  user-direct write — scope leak toward "email client"/"ads console",
  which this plan is not.

## Maintenance notes

- **Provider N+1**: adapters live in the provider's own packages
  (`apps/api/integrations/<key>/` +
  `apps/web/src/integrations/<key>/`); the engine surface (kits,
  preview route, sanitizer, untrusted-node contract) never grows per
  provider. Preview fetchers and their kinds are plugin contributions.
  A provider needing a new kit, a
  new column kind, a new `content_type`, or a new engine behavior is
  a platform review, not a package change.
- **Kit ownership**: `src/components/tool-ui/` is engine code with the
  same review bar as `features/conversations` — changes there affect
  every provider at once. Keep kits payload-shape-agnostic: they take
  narrowed props, never `unknown` activity objects (narrowing is the
  adapter's job).
- **Untrusted-node contract**: the node shape is the one cross-layer
  contract (dispatch → storage → SSE → kits). Changing it is a
  platform review touching `untrusted.py`, the request wrapper, and
  `untrusted-node.ts` together; the frame vocabulary itself remains
  free to evolve without touching the client.
- **Reviewers should scrutinize**: every model request path passes
  the request wrapper (the framing invariant now lives there),
  sandbox attributes on every iframe touching provider content (empty
  `sandbox`, no `allow-same-origin`), sanitizer allowlist changes,
  any path where preview content could reach logs/audit/model
  context, that provenance chips are visually distinct from app
  chrome, that adapters guard payload shapes rather than trusting
  them, and that display-time conversions (micros, percent) never
  leak back into model-visible payloads.
