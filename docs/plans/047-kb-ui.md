# Plan 047: Knowledge base UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Sibling pre-flight (run before Step 1)**: this plan was written in
> parallel with 044/045/046 against a dictated backend contract. Before
> coding, hit the live API (or read the shipped route/schema code) and
> reconcile every path and response shape in "Current state — dictated
> backend contract" with reality; hand-written `types.ts` must mirror the
> real JSON, not this plan's guesses. A material mismatch is a STOP
> condition.
>
> **Working-tree note**: at planning time (`0cbbb39`) the repo carried
> uncommitted changes under
> `apps/web/src/features/conversations/message-parts/` (including a new
> `group-render-items.ts`). All conversations-feature citations below are
> at commit `0cbbb39`; re-verify the tool-row extension point (Step 7)
> against whatever landed.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/web/src/features/ apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/lib/api/ apps/web/src/components/shell/`
> Changes under `features/files/` (035) and `features/conversations/` are
> expected; for everything else compare the "Current state" excerpts
> against live code before proceeding; on a mismatch in the router, query
> patterns, or tool-row registry, treat it as a STOP condition.
>
> **Amendment (plan 080) pre-flight**: the "Amendment (plan 080,
> 2026-07-10)" block at the end of this file amends this plan — Vitest
> unit tests exist and are mandatory for the new pure logic, query keys
> ride `createWorkspaceScopedQueryKeys` (plan 064), and the upload flow
> is real end-to-end (044's plan-080 amendment); where it conflicts with
> the body above, the amendment wins.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MEDIUM (pure frontend; the risky choke points shipped in
  046 — the main hazards here are contract drift against 044–046 and the
  no-new-SSE-events constraint)
- **Depends on**: hard — 044 (document model + processing states), 045
  (`POST /api/v1/kb/search` + read routes), 046 (document write routes:
  manual/from-url/from-file, update, delete, reprocess). Soft — 035
  (Files UI upload component; reuse it if it exists, decision 4).
- **Category**: Phase 4b knowledge base (roadmap `000_MASTER_ROADMAP.md`
  §4 Phase 4b row 047; donor `DONOR_PORT_ROADMAP.md` §4.4 row D5)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **One feature directory, skills-shaped.** `src/features/knowledge/`
   with `api/`, `components/`, `routes/`, `types.ts` — the exact layout
   of `features/skills/` (019), which is the closest precedent for a
   documents-table feature. Routes: `/knowledge` (table + search + add
   flows) and `/knowledge/$documentId` (detail). No sub-tabs in v1; the
   search panel lives on the main page above/beside the table.
2. **Search is submit-driven, not keystroke-driven.** The search box is a
   native form (per AGENTS.md forms rule); submitting sets the active
   query, and a non-suspense `useQuery` (`enabled: query !== ""`) hits
   the same `POST /api/v1/kb/search` endpoint the agent's
   `search_knowledge` tool rides (045's contract — one endpoint, two
   consumers). No debounce machinery, no search library. Results render
   chunk snippets with the document title linking to the detail route.
3. **Processing status polls only while work is pending.** The documents
   list query uses a `refetchInterval` callback returning 5000 when any
   row is in a non-terminal processing state and `false` otherwise —
   ingestion progress appears without websockets or new endpoints. Retry
   visibility = status badge + attempt/error detail (from 044's retry
   columns) + a Reprocess action wired to 046's
   `POST /kb/documents/{id}/reprocess`.
4. **Upload rides Files; reuse 035's component when present (soft
   dependency).** The flow is: two-phase signed upload through the 032
   files API → `POST /kb/documents/from-file {file_id, ...}` (046). At
   execution time, if `features/files/` ships an upload component/API ops
   (035), import and reuse them. If 035 has not landed, implement a
   minimal `api/upload-file.ts` in the knowledge feature against the 032
   routes, following the existing two-phase precedent
   (`features/skills/api/skill-documents.ts:34-46`), and leave a
   follow-up note in `docs/plans/FOLLOW_UPS.md` to consolidate onto 035's
   component when it lands. Feature→feature imports are established
   practice (`list-skills.ts:6` imports `features/workspaces/`).
5. **Chat rendering: zero SSE/protocol changes; one client-side row.**
   The 046 tools stream through the existing `tool.call`/`tool.result`
   events and render via the generic tool rows already. This plan adds
   one specialized compact row for `search_knowledge` through the 020
   extension point — `TOOL_CALL_ROW_DEFINITIONS` in
   `features/conversations/components/tool-call-row-registry.tsx`
   (29–57), exactly how `read_skill_document` got
   `SkillDocumentReadRow` (51–55). The SSE parser
   (`features/conversations/stream/`) is not touched; no new event names
   exist server-side, so the client-first shipping rule is satisfied
   vacuously. `read_document` keeps the generic row in v1.
6. **Privacy is explicit and one-way in the UI.** The create forms expose
   a "Private (only visible to you)" checkbox; the detail view offers
   "Make private" only (never "make shared"), mirroring 046's write
   policy — the UI must not offer a transition the API always rejects.
7. **No markdown-renderer duplication.** The detail view reuses the
   existing conversations markdown component (`MessageMarkdown`,
   `features/conversations/components/message-markdown.tsx`, already
   imported cross-feature by `skill-document-read-row.tsx:6`) rather than
   adding a second renderer. If dependency-cruiser objects at execution
   time, hoist the component to a shared location — do not vendor a copy.

## Why this matters

Roadmap pillar 3 ("Surfaces"): nothing an agent can do is invisible. 046
gives agents `search_knowledge`/`read_document`; without this plan the
knowledge those tools read is write-only for humans — documents can be
created only via raw API calls, ingestion failures are silent, and
private-vs-shared state is invisible. The donor shipped KB backend
capability without an operator surface and it rotted unaudited. This plan
is the product surface: a dense operational table of documents with
honest processing status (including retries and failures), the three add
flows (upload/URL/manual) riding 046's routes, a detail view of exactly
the markdown the agent reads, and a search box that exercises the same
endpoint the agent uses — so a human can verify retrieval quality with
their own eyes before trusting an agent with it.

## Current state

Frontend anchors verified at `0cbbb39` (see working-tree note above).

**Feature/precedent layout (019 skills — the template):**

- `apps/web/src/features/skills/` — `api/` (six one-operation files),
  `components/` (`skills-table.tsx`, `skill-form.tsx`,
  `skill-form-model.ts` hand-rolled validation, `skill-form-section.tsx`,
  `skill-documents-section.tsx`), `routes/` (`skills-route.tsx`,
  `new-skill-route.tsx`, `skill-detail-route.tsx`), `types.ts`.
- `features/skills/api/list-skills.ts` — the read-op shape: structured
  `skillsQueryKeys` with the workspace scope baked in via
  `getActiveWorkspaceSlug()` (15–27) *(superseded — the keys are now
  composed from `createWorkspaceScopedQueryKeys` (plan 064); see
  Amendment (plan 080))*, `queryOptions` factory (43–49),
  `useSuspenseQuery` hook (51–53), `apiRequest` with a `query` object
  (34–41).
- `features/skills/api/skill-documents.ts` — mutations + the two-phase
  signed-upload call pattern (34–46: grant → confirm) and
  cache invalidation via `useQueryClient`.

**Plumbing:**

- `src/lib/api/client.ts` — `apiRequest` sends credentials, the
  `X-CSRF-Token` header (59–61), and the `X-Workspace` header; features
  never call `fetch` directly.
- `src/app/router.tsx` — code-based route tree; `lazyRouteComponent`
  (8); the skills routes at 159–184 (`path: "/skills"`,
  `"/skills/new"`, `"/skills/$skillId"`) registered in the tree at ~249.
  New routes follow this exact shape under the authed app layout route.
- `src/config/navigation.ts` — nav items are plain data
  (`label`/`to`/`icon`); "Skills" → `/skills` at 43–44;
  `navigationItemsForRole` feeds
  `components/shell/primary-navigation.tsx` (17). The "Knowledge" item
  goes here — one data entry, no shell component changes.

**Chat tool rendering (020 — the extension point):**

- `features/conversations/components/tool-call-row-registry.tsx` —
  `TOOL_CALL_ROW_DEFINITIONS: ToolCallRowDefinition[]` (29–57) matched by
  `renderCustomToolCallRow` (59–62); each definition is
  `{key, matches(activity), render(props)}`. The `skill-document-read`
  entry (50–55) matches on `activity.name === READ_SKILL_DOCUMENT_TOOL_NAME`
  and renders `SkillDocumentReadRow` — the exact pattern for a
  `search_knowledge` row.
- `features/conversations/components/skill-document-read-row.tsx` — the
  compact-row precedent built on `ToolActivityRowShell`/
  `ToolActivityRowHeader`/`ActivityStatusIcon` (21–60).
- `features/conversations/message-parts/types.ts` — `ToolActivity`
  (25–36: `id`/`kind`/`status`/`name`/`args`/`result`/`outcome`).
- `features/conversations/stream/` — hand-written SSE parser that throws
  on unknown event names; this plan must not require any new server
  event (decision 5).

**Quality gate**: no test framework *(superseded — Vitest ships in
`pnpm check` since 062/063; see Amendment (plan 080))*; `pnpm check` =
typecheck, eslint
(zero warnings), prettier, knip, dependency-cruiser (`pnpm arch`), build.
`src/components/ui/` is vendored shadcn (`base-nova` on
`@base-ui/react`); prefer adding shadcn primitives over hand-building.

**Dictated backend contract (from 044/045/046 — reconcile at pre-flight,
not in the tree at `0cbbb39`):**

- `GET /api/v1/kb/documents` (list — owned by **046** (`list_documents`,
  workspace list with `source_type`/status/`is_private` filters; assigned
  at the 2026-07-06 reconciliation pass). Verify it landed with 046 at
  pre-flight) and
  `GET /api/v1/kb/documents/{id}` (detail incl. markdown + chunk count;
  045). Documents carry: `id`, `title`, `source_type`
  (upload/url/manual/conversation/integration), `is_private`, processing
  state machine fields with retry visibility (status + attempts +
  last error), `file_revision_id?`, `created_at`, `updated_at`.
- `POST /api/v1/kb/search` (045 — POST; the filter object travels in the
  body) — the same endpoint `search_knowledge`
  uses; results carry chunk id/index, document id/title/source_type/
  `is_private`, score, chunk content/snippet, plus a lexical-fallback
  indicator.
- Write routes (046): `POST /kb/documents` (manual),
  `POST /kb/documents/from-url`, `POST /kb/documents/from-file`
  (`{file_id, title?, is_private}`), `PATCH /kb/documents/{id}`,
  `DELETE /kb/documents/{id}`,
  `POST /kb/documents/{id}/reprocess`. Creates are member+ (governance
  §1); read_only members get 403 — the UI hides write affordances for
  read_only roles the way `navigationItemsForRole` already gates by role.
- Agent tool names (046): `search_knowledge`, `read_document`
  (`provider: "kb"`); `search_knowledge` args include `query`, results
  include framed chunk content.
- Files (032): two-phase signed upload; a confirmed upload yields a
  `file_id` the from-file route accepts.

## Commands you will need

| Purpose | Command (from `apps/web`) | Expected on success |
|---------|---------------------------|---------------------|
| Install | `pnpm install` | lockfile unchanged (no new deps expected) |
| Full gate | `pnpm check` | typecheck + eslint(0 warnings) + prettier + knip + depcruise + build all pass |
| Arch only | `pnpm arch` | no dependency-cruiser violations |
| Dev server | `pnpm dev` | app serves; `/knowledge` renders against a running API |
| Backend up (for manual verify) | `make dev` (repo root) | API + web running |

## Scope

**In scope:**

- `apps/web/src/features/knowledge/` (create):
  - `types.ts` — `KbDocument`, `KbDocumentsListResponse`,
    `KbDocumentDetail`, `KbSearchResult`, `KbSearchResponse`,
    `KbProcessingStatus`, request payload types (all `type`, never
    `interface`)
  - `api/list-documents.ts` (owns `knowledgeQueryKeys`),
    `api/get-document.ts`, `api/search-knowledge.ts`,
    `api/create-document.ts`, `api/create-document-from-url.ts`,
    `api/create-document-from-file.ts`, `api/update-document.ts`,
    `api/delete-document.ts`, `api/reprocess-document.ts`, and (only if
    035 absent) `api/upload-file.ts`
  - `components/documents-table.tsx`, `components/document-status-badge.tsx`,
    `components/source-type-badge.tsx`, `components/add-document-menu.tsx`,
    `components/manual-document-form.tsx` +
    `components/manual-document-form-model.ts`,
    `components/url-document-form.tsx`,
    `components/document-upload-button.tsx`,
    `components/document-detail-header.tsx`,
    `components/document-markdown-view.tsx`,
    `components/knowledge-search-panel.tsx`
  - `routes/knowledge-route.tsx`, `routes/document-detail-route.tsx`
- `apps/web/src/app/router.tsx` (extend — two routes)
- `apps/web/src/config/navigation.ts` (extend — "Knowledge" item)
- `apps/web/src/features/conversations/components/knowledge-search-row.tsx`
  (create), `apps/web/src/features/conversations/knowledge-search.ts`
  (create — tool-name constant + arg/result guards), and the one-entry
  addition to `components/tool-call-row-registry.tsx`
- `docs/plans/FOLLOW_UPS.md` (only if the decision-4 fallback was used)

**Out of scope (do NOT touch):**

- Backend anything — routes, services, schemas (044/045/046 own them).
- The SSE parser/protocol (`features/conversations/stream/`) — no new
  event names, no reducer changes (decision 5).
- A files management page (035), embeddings/reranker settings UI (043+),
  and any KB analytics/eval surface (045's harness is backend-only).
- Form or schema-validation libraries, markdown editors, data-grid
  libraries — native forms + existing primitives only (AGENTS.md).
- Editing derived content: the UI only offers content editing for
  `source_type === "manual"` documents, matching 046's rule.
- `src/components/ui/` internals (vendored shadcn output).

## Git workflow

- Branch: `advisor/047-kb-ui`
- Commit style: `Web - Knowledge Base UI`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Sibling pre-flight

With the API running (`make dev`), verify each dictated route responds
and capture real response JSON for: document list (one pending-ingestion
doc if possible), document detail, search, and one create. Check whether
`features/files/` exists with reusable upload ops (decision 4). Adjust
`types.ts` field names in Step 1 to the real payloads.

**Verify**: `curl` (with session cookie + `X-Workspace`) or the browser
network tab shows 200s for the read routes and the documented shapes; a
mismatch beyond field-level naming is a STOP condition.

### Step 1: Types and query keys

Create `features/knowledge/types.ts` (hand-written, `type` aliases only)
mirroring Step 0's real payloads. Create `api/list-documents.ts` first —
it owns the key factory, mirroring `skillsQueryKeys`
(`list-skills.ts:15-27`) including the workspace scope *(sketch below
superseded — build on `createWorkspaceScopedQueryKeys`; see Amendment
(plan 080))*:

```ts
export const knowledgeQueryKeys = {
  all: ["knowledge"] as const,
  workspace: () => [...knowledgeQueryKeys.all, activeWorkspaceQueryScope()] as const,
  lists: () => [...knowledgeQueryKeys.workspace(), "list"] as const,
  list: (params: ListDocumentsParams = {}) => [...knowledgeQueryKeys.lists(), params] as const,
  details: () => [...knowledgeQueryKeys.workspace(), "detail"] as const,
  detail: (documentId: string) => [...knowledgeQueryKeys.details(), documentId] as const,
  searches: () => [...knowledgeQueryKeys.workspace(), "search"] as const,
  search: (query: string) => [...knowledgeQueryKeys.searches(), query] as const,
}
```

`documentsQueryOptions` includes the decision-3 polling:
`refetchInterval: (query) => hasActiveProcessing(query.state.data) ? 5000 : false`.

**Verify**: `pnpm typecheck` passes with the new files imported nowhere
yet (knip will flag until Step 4 — run the full gate only at Step 9).

### Step 2: Read operations

- `api/get-document.ts` — `documentQueryOptions(documentId)` +
  `useDocumentQuery` (suspense), keyed `knowledgeQueryKeys.detail(id)`.
- `api/search-knowledge.ts` — `searchKnowledgeQueryOptions(query)`
  hitting `POST /kb/search` with body `{ query, top_k: 20 }` (045's
  request shape — reconcile field names at pre-flight);
  export `useKnowledgeSearchQuery(query)` as a **non-suspense**
  `useQuery` with `enabled: query.trim() !== ""` and
  `placeholderData: keepPreviousData` (decision 2). One operation per
  file, reads export queryOptions — per AGENTS.md.

**Verify**: typecheck; keys for all three reads include the workspace
scope segment.

### Step 3: Mutations

One file per operation, each a `useMutation` hook that invalidates
`knowledgeQueryKeys.lists()` (and `detail(id)` where relevant), the
`skill-documents.ts` shape:

- `create-document.ts` (`POST /kb/documents`), `create-document-from-url.ts`,
  `create-document-from-file.ts`
- `update-document.ts` (`PATCH`), `delete-document.ts` (`DELETE`,
  also removes the detail key), `reprocess-document.ts` (`POST
  .../reprocess`, invalidates list + detail so the status badge flips to
  pending and polling resumes)
- Decision 4: `upload-file.ts` ONLY if 035's ops are absent — two-phase
  grant→PUT→confirm against the 032 routes, mirroring
  `skill-documents.ts:34-46`, returning the confirmed `file_id`.

**Verify**: typecheck; every mutation file exports exactly one hook; no
`fetch` calls outside `lib/api`.

### Step 4: Routes, router, navigation

- `routes/knowledge-route.tsx` — `KnowledgeRoute`: page header, role-gated
  `AddDocumentMenu` (hidden for read_only), `KnowledgeSearchPanel`,
  `DocumentsTable` inside the feature's suspense boundary (copy the
  skills route shell structure).
- `routes/document-detail-route.tsx` — `KnowledgeDocumentRoute` reading
  `$documentId` via `useParams`.
- `src/app/router.tsx` — `knowledgeRoute` (`path: "/knowledge"`) and
  `knowledgeDocumentRoute` (`path: "/knowledge/$documentId"`) with
  `lazyRouteComponent`, registered beside the skills routes (159–184
  shape) under the authed layout.
- `src/config/navigation.ts` — add `{ label: "Knowledge", to:
  "/knowledge", icon: <lucide icon, e.g. BookOpen or Library> }` after
  Skills (43–44).

**Verify**: `pnpm dev` → sidebar shows Knowledge; `/knowledge` and
`/knowledge/<uuid>` render (empty states fine); unauthenticated access
redirects like other app routes.

### Step 5: Documents table + add flows

`documents-table.tsx` — dense table (skills-table precedent, shadcn
table primitives): columns Title (link to detail), Source
(`source-type-badge.tsx`: upload/url/manual — do not render UI for the
producer-less conversation/integration values beyond a fallback label),
Status (`document-status-badge.tsx`: terminal ready/failed states plus
in-flight states from 044's machine; failed rows show attempts + last
error in a tooltip/expandable and an inline Reprocess button —
decision 3), Privacy (lock icon + "Private" when `is_private`), Updated
(relative time, existing formatting helpers). Empty state invites the
add flows.

`add-document-menu.tsx` — a dropdown with three items opening dialogs:

- **Manual** — `manual-document-form.tsx`: native form + `FormData`
  helpers from `src/lib/forms.ts`, hand-rolled model in
  `manual-document-form-model.ts` (`skill-form-model.ts` precedent):
  title required, content required, private checkbox (decision 6).
- **From URL** — `url-document-form.tsx`: url + optional title + private
  checkbox; client-side `new URL()` + http(s) check for fast feedback
  (the API re-validates); on success, toast that ingestion is queued.
- **Upload** — `document-upload-button.tsx`: file picker → decision-4
  upload path → `create-document-from-file` mutation; show per-file
  progress/failure inline in the dialog.

All three surface RFC 7807 errors from the API via the existing error
display pattern in skills forms; write policy rejections (secrets,
duplicates) arrive as problem+json and must be shown verbatim.

**Verify**: against a dev API — create one document per source; the
table shows all three with correct badges; a pending doc's status
updates within ~5 s of ingestion finishing without a manual refresh
(decision-3 polling); read_only member (switch role in a test workspace)
sees no add menu or reprocess buttons.

### Step 6: Document detail

`document-detail-route.tsx` composes:

- `document-detail-header.tsx` — title, source/status/privacy badges,
  chunk count, updated/created, actions: Reprocess, Make private
  (decision 6 — only when currently shared; confirmation dialog states
  it cannot be undone), Delete (confirmation dialog; navigates back to
  `/knowledge` and invalidates the list), and Edit (manual source only:
  title + content form reusing the Step 5 form pieces).
- `document-markdown-view.tsx` — renders `content_md` via the reused
  `MessageMarkdown` (decision 7) inside an `overflow-x-auto` container;
  for pending/failed docs with no content yet, show the processing state
  instead.

**Verify**: detail renders markdown for a ready doc; reprocess flips the
badge and repolls; Make private disappears once private; edit is offered
only on manual docs; delete returns to the table without the row.

### Step 7: Search panel + chat row

`knowledge-search-panel.tsx` — native form with one search input +
submit; on submit set local `query` state feeding
`useKnowledgeSearchQuery` (decision 2). Results list: one row per chunk —
document title (link), source/privacy badges, score, and the chunk
snippet with the matched content (use 045's highlight/snippet field if
present; otherwise render the chunk content clamped to a few lines).
Show the lexical-fallback indicator as a subtle hint ("semantic index
still building — lexical results") when the response flags it. Empty
query renders nothing; zero results get an explicit empty state.

Chat row (decision 5): `features/conversations/knowledge-search.ts`
exports `SEARCH_KNOWLEDGE_TOOL_NAME = "search_knowledge"` plus small
guards to pull `query` from `activity.args` and result document titles
from `activity.result` (defensive `unknown` narrowing like
`skill-document-read.ts`). `knowledge-search-row.tsx` renders a compact
row ("Searched knowledge: {query}" + result count, expandable to the raw
result via the existing content blocks), built on
`ToolActivityRowShell`/`ToolActivityRowHeader` exactly like
`skill-document-read-row.tsx:21-60`. Register one entry in
`TOOL_CALL_ROW_DEFINITIONS` (`tool-call-row-registry.tsx:29-57`)
matching `activity.name === SEARCH_KNOWLEDGE_TOOL_NAME`. No parser,
reducer, or event-type changes anywhere.

**Verify**: searching a seeded phrase returns rows whose links open the
right detail pages; in a conversation, an agent `search_knowledge` call
renders the compact row and `read_document` renders the generic tool row;
`git diff --stat -- apps/web/src/features/conversations/stream/` is
empty.

### Step 8: Role gating polish

Thread the workspace role (same source `primary-navigation.tsx` uses)
into the knowledge routes so read_only members get a read-only surface:
no add menu, no reprocess/delete/privacy/edit actions, table and search
fully functional (governance §1: view = read_only+, create/edit =
member+). Server enforcement exists (046); the UI must simply not offer
dead buttons.

**Verify**: as read_only, `/knowledge` shows table + search only; as
member, all write affordances appear.

### Step 9: Quality gate

Run `pnpm check`. Fix violations by restructuring, not by editing lint
or dependency-cruiser rules; knip must not report dead exports in the
new feature (delete speculative helpers instead of ignoring them). If
dependency-cruiser rejects the `MessageMarkdown` cross-feature import
(decision 7), hoist the component rather than duplicating or rule-editing.

**Verify**: `pnpm check` exits 0 with zero eslint warnings.

## Test plan

There is no frontend test framework (AGENTS.md); the gate is static plus
scripted manual verification. *(superseded — Vitest exists and unit
tests for this plan's pure logic are mandatory; see Amendment
(plan 080))* Pinned checks:

- `pnpm check` fully green (typecheck strict incl.
  `exactOptionalPropertyTypes`, eslint 0 warnings, prettier, knip,
  depcruise, build).
- Manual matrix against `make dev`: create via all three sources; watch
  a pending → ready transition land via polling; force a failure (bad
  URL host) and confirm attempts/error visibility + reprocess; privacy
  one-way flow; delete; search hits the same endpoint the agent uses and
  results deep-link correctly; agent chat renders `search_knowledge`
  via the new row with no console errors; read_only gating (Step 8).
- Grep assertions: no `fetch(` outside `src/lib/api/`; no `interface `
  in the new feature; every new query key path includes the workspace
  scope; zero changes under `features/conversations/stream/`.

## Done criteria

- [ ] `pnpm check` exits 0 (zero eslint warnings)
- [ ] `/knowledge` lists documents with title, source type, processing
      status (with retry visibility + reprocess), privacy, and updated
      columns; polling stops when nothing is processing
- [ ] All three add flows work end to end against a dev API; upload rides
      the Files two-phase API (via 035's component or the recorded
      fallback + follow-up note)
- [ ] Document detail shows markdown, chunk count, and reprocess/
      privacy/delete (+ edit for manual) actions; privacy control is
      one-way (decision 6)
- [ ] Search UI rides `POST /api/v1/kb/search` — the identical endpoint
      the agent tool uses — with chunk snippets and a lexical-fallback
      hint
- [ ] `search_knowledge` renders via one new `TOOL_CALL_ROW_DEFINITIONS`
      entry; `features/conversations/stream/` is byte-identical
- [ ] "Knowledge" appears in `config/navigation.ts` and both routes are
      registered in `router.tsx` with `lazyRouteComponent`
- [ ] No new dependencies in `package.json`; no `type`→`interface`
      violations; all query keys workspace-scoped
- [ ] Read_only members see a read-only surface (Step 8)
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 044, 045, or 046 is not implemented at execution time (any dictated
  route 404s), or the shipped response shapes differ structurally from
  the pre-flight contract (beyond field renames you can mirror in
  `types.ts`).
- Rendering the KB tool calls would require a **new SSE event name** or
  any change under `features/conversations/stream/` — the parser throws
  on unknown events and stale clients break; that would need a
  server-side plan with client-first shipping, which this plan explicitly
  does not include.
- `tool-call-row-registry.tsx` no longer exists or the working-tree
  message-parts changes noted above landed a different extension point —
  re-locate the 020 mechanism first and reconcile.
- The 032 files upload API is absent or incompatible with the two-phase
  pattern (decision 4's fallback cannot be built).
- `features/knowledge/` already exists, or a "Knowledge" nav/route was
  added by another plan.
- Satisfying `pnpm check` would require editing `.dependency-cruiser.cjs`
  or eslint config — restructure instead; if genuinely impossible,
  report.
- The 046 tool names differ from `search_knowledge`/`read_document`
  (the chat-row match and the search-panel parity claim both depend on
  them).

## Maintenance notes

- **Contract coupling**: `types.ts` is the hand-written mirror of
  044/045/046 responses. When 044 evolves the processing state machine or
  045 changes the search response, this feature's badges/snippets are the
  first breakage point — update `types.ts` and the badge maps together.
- **Upload consolidation**: if the decision-4 fallback shipped, 035's
  executor should replace `api/upload-file.ts` with the shared files ops
  and delete the fallback (tracked in `FOLLOW_UPS.md`).
- **Future rows**: when an agent KB write tool ships (deferred by 046
  decision 1), its approval-gated call should get a specialized row via
  the same `TOOL_CALL_ROW_DEFINITIONS` entry pattern — approval controls
  already flow through `ToolCallRowRenderProps.approvalDecision`.
- **Roadmap D9**: this UI renders the Praxis-owned KB; OKF informs the
  markdown/frontmatter document shape it displays (044's `content_md` +
  preserved frontmatter) and future import/export affordances. No
  external knowledge-catalog UI is implied here.
- **Search parity is a feature**: keep the UI on the exact agent
  endpoint. If someone proposes a UI-only search variant (different
  ranking, different filters), that belongs in 045's engine behind the
  shared route, or retrieval quality seen by humans and agents will
  diverge silently.
- Reviewers should scrutinize: polling shutoff (a table stuck on a 5 s
  interval is a quiet cost), problem+json surfacing on write-policy
  rejections (secret blocking must be legible, not a generic toast), and
  that privacy affordances never offer private→shared.

## Amendment (plan 080, 2026-07-10): Vitest, shared query keys, real upload path

Where this block conflicts with the body above, this block wins.

**1. Frontend tests exist (plan 080 decision 11).** The "no frontend
test framework" claims predate plans 062/063: Vitest is installed and
`pnpm test` (`vitest run`) runs inside `pnpm check` and CI
(`apps/web/package.json`), with tests under `apps/web/tests/` mirroring
the source module paths — AGENTS.md mandates that layout; do not
colocate tests under `src/`. Test-plan delta: unit-test the pure logic
this plan adds, under `apps/web/tests/features/knowledge/`:

- the form models — `manual-document-form-model.test.ts` (and the URL
  form's validation if it is a separate module), following the
  `tests/features/agents/components/agent-form-model.test.ts` precedent;
- the query keys — workspace scoping and key composition (the
  `tests/features/workspaces/query-keys.test.ts` precedent);
- the status mapping — the processing-status → badge map and the
  `hasActiveProcessing` polling predicate (decision 3's shutoff is the
  quiet-cost hazard the maintenance notes flag; pin it).

The scripted manual QA matrix and the grep assertions stand unchanged.
The commands-table expectation for `pnpm check` now includes
`vitest run`.

**2. Query keys ride the shared factory (plan 064).** Step 1's
hand-rolled `knowledgeQueryKeys` sketch mirrors a retired pattern:
`features/skills/api/list-skills.ts` now builds its keys from
`createWorkspaceScopedQueryKeys` in
`src/features/workspaces/query-keys.ts`, which provides `all`,
`workspace()`, `lists()`, `list(params)`, `details()`, and
`detail(id)` with the workspace scope baked in. Do the same:

```ts
const baseKnowledgeQueryKeys = createWorkspaceScopedQueryKeys("knowledge")

export const knowledgeQueryKeys = {
  ...baseKnowledgeQueryKeys,
  searches: () => [...baseKnowledgeQueryKeys.workspace(), "search"] as const,
  search: (query: string) => [...knowledgeQueryKeys.searches(), query] as const,
}
```

The workspace-scope done criterion and grep assertion are satisfied by
the factory; do not re-implement `workspace()`/`getActiveWorkspaceSlug()`
plumbing in the feature.

**3. The upload path is real end-to-end.** 044's plan-080 amendment
ships upload-source ingestion with 044 (plan 033 landed), so
`POST /kb/documents/from-file` produces a document that actually
ingests — there is no pending-033 messaging to design around, and the
Step 5 upload dialog plus decision-3 polling reflect real ingestion
progress through to `ready`.

**Done-criteria addition:**

- [ ] Unit tests for the knowledge form models, query keys, and status
      mapping exist under `apps/web/tests/features/knowledge/`, and
      `pnpm check` (which includes `vitest run`) exits 0
