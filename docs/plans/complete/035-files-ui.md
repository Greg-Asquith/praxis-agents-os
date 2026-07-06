# Plan 035: Files UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Sibling-plan pre-flight (run before Step 1)**: this plan was written in
> parallel with plans 030–034. Hard dependency: plan 032's `/api/v1/files`
> routes must be implemented in code at execution time — Step 1's `types.ts`
> must be transcribed from 032's **landed** Pydantic response schemas, not
> from the shapes sketched here. Soft dependencies: 033 (`processing_status`
> only progresses past `pending` once extraction jobs run — the UI must
> render all four states regardless) and 034 (chat file cards get
> `write_file`/`promote_scratch` rows to render; without 034 those rows
> simply never occur). If 032 is missing, STOP.
>
> **Drift check (run first)**: `git diff --stat 0cbbb39..HEAD -- apps/web/src/features/ apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/lib/`
> Note: `features/conversations/message-parts/` and two chat components had
> **uncommitted local changes at planning time** — this plan anchors to
> what is on disk at `0cbbb39` + those working-tree edits (the
> `group-render-items.ts` refactor). Re-read the current
> `tool-call-row-registry.tsx` and `message-parts/` shapes before Step 5;
> on a structural mismatch with the excerpts below, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: LOW-MEDIUM (additive frontend surface; the only shared-code
  touches are the router, nav config, and the chat tool-row registry)
- **Depends on**: 032 (hard — the files API), 031 (transitively — the
  contract categories the UI displays), 034 (soft — scratch/promote chat
  rows), 033 (soft — processing status progression)
- **Category**: Phase 3 files & jobs (roadmap `000_MASTER_ROADMAP.md` §4
  row 035; donor `DONOR_PORT_ROADMAP.md` §4.3 "UI" / §6 row B6)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **One route, sheet for detail.** `/files` is a single table route; the
   detail (metadata, revision history, diff, restore) opens in a `Sheet`
   keyed by a `fileId` search param, per the donor design ("table + detail
   sheet") — unlike skills/schedules which use `$id` sub-routes, files are
   inspected far more often than edited, and a sheet keeps table context.
   Using a search param (not component state) keeps detail links shareable
   and back-button-correct.
2. **Feature layout per the 019/022 precedent**: `src/features/files/`
   with `api/` (one operation per file), `components/`, `routes/`, and
   `types.ts` (hand-written `type` aliases — no interfaces, no codegen).
   Query keys are workspace-scoped through the same
   `activeWorkspaceQueryScope()` idiom as
   `features/skills/api/list-skills.ts:15-27`.
3. **Hand-rolled line diff, no new dependency.** Revision diff for
   editable-text files is a feature-local LCS line diff
   (`features/files/diff.ts`, ~60 lines, returns
   `{kind: "same" | "added" | "removed", text}[]`). A diff library is a
   new dependency for one screen; knip and the zero-warning gate punish
   half-used packages, and the frontend has no test framework to certify a
   fancy one anyway. Diff renders only for the editable-text contract
   category; other categories show metadata-only revision rows.
4. **Signed URLs are fetched on click, never cached.** Open/download
   actions call the 032 download endpoint on demand and immediately
   `window.open(url)` / trigger the download — short-lived URLs must not
   sit in the TanStack Query cache going stale. This matches the skills
   precedent (`createSkillDocumentDownload`,
   `features/skills/api/skill-documents.ts:48-50`, called imperatively).
5. **Upload rides the existing grant plumbing unchanged**: request-upload →
   `uploadFileDirectly` (`src/lib/api/direct-upload.ts:5`) → confirm, the
   exact three-step flow `skill-documents-section.tsx:69-81` already
   proves. The `AssetUploadGrant`/`SignedUpload` types in
   `features/storage/types.ts` are reused as-is if 032 kept that grant
   shape; otherwise transcribe 032's landed grant type into
   `features/files/types.ts` (pre-flight).
6. **Processing status is polled, not pushed.** Rows in
   `pending`/`processing` set `refetchInterval: 4000` on the list query
   (conditional on data, so quiescent workspaces do not poll). No SSE, no
   websocket — 033's job pipeline has no push channel and must not grow
   one for this.
7. **Chat file cards are tool-row registry entries + one shared card.**
   A generic `FileCard` (name, category icon, size, open/download actions)
   plus registry rows for the 034 tools (`write_file` durable results,
   `promote_scratch` results, `read_file` url-mode results), following the
   `SkillDocumentReadRow` pattern registered in
   `tool-call-row-registry.tsx:29-56`. User-message attachment chips are
   **036's** job — this plan only ships the card component they will
   reuse, rendering agent-side file activity.
8. **Restore confirms destructively-styled but is not destructive**:
   restore creates a new roll-forward revision (031 contract — history is
   never rewritten), so the confirm dialog copy says exactly that.
   Delete soft-deletes with an `AlertDialog` confirm; hard-delete/purge is
   admin-only per governance §1 and **not in this UI slice** (032's
   sweeper owns it; an admin purge surface is a follow-up).

## Why this matters

Roadmap targets §3 "Surfaces": nothing an agent can do should be
invisible. 031–034 give agents and users a shared file substrate; without
this plan the only witnesses are API consumers and audit rows. The files
page is also the operational window into 033's processing pipeline
(status column), the human end of 034's promote-scratch approval loop
(the promoted file must be immediately findable and diffable), and the
prerequisite card work for 036's attachment chips.

## Current state

All anchors verified at `0cbbb39` (+ the uncommitted `message-parts`
working-tree state noted in the drift check).

- Feature precedent — `apps/web/src/features/skills/`: `api/` one file per
  operation (`list-skills.ts` exports `queryOptions` factory +
  `useSuspenseQuery` hook + structured `skillsQueryKeys` with the
  workspace scope segment, lines 15-53); mutations invalidate keys
  (`skill-documents.ts:76-100`); `routes/skills-route.tsx` is the
  header + `MetricCard` + table shell this plan's `/files` route copies.
- Router — `apps/web/src/app/router.tsx`: code-based routes with
  `lazyRouteComponent` (`/skills` at 159-166); routes registered in the
  tree list (~249-252). Search-param validation via
  `validateSearch` is available on `createRoute`.
- Nav — `apps/web/src/config/navigation.ts:43-44` (`Skills` item): plain
  data; add a `Files` item the same way.
- Upload plumbing — `src/lib/api/direct-upload.ts:5`
  `uploadFileDirectly(upload, file, maxSizeBytes)` (size pre-check, PUT
  with grant headers, `credentials: "omit"`);
  `features/storage/types.ts` `SignedUpload` / `AssetUploadRequest` /
  `AssetUploadGrant` (`upload`, `upload_token`, `max_size_bytes`,
  `expires_at`); the three-step flow in
  `features/skills/components/skill-documents-section.tsx:69-81`.
- API client — `src/lib/api/client.ts` `apiRequest` sends credentials,
  CSRF, and `X-Workspace`; features never call `fetch` directly (the
  only sanctioned exception is `direct-upload.ts`'s signed PUT, which
  deliberately omits credentials).
- Chat integration seam —
  `features/conversations/components/tool-call-row-registry.tsx`:
  `ToolCallRowDefinition[]` with `matches(activity)`/`render(props)`;
  `renderCustomToolCallRow` falls through to the generic row (57-60).
  `ToolActivity` shape in `features/conversations/message-parts/types.ts:25-36`
  (`name`, `args`, `result`, `status`). `SkillDocumentReadRow` +
  `READ_SKILL_DOCUMENT_TOOL_NAME` (`skill-document-read.ts`) is the
  name-matched row precedent from plan 020.
- Quality gate — `pnpm check` = typecheck, eslint (zero warnings),
  prettier, knip, dependency-cruiser, build. `components/ui` is vendored
  shadcn; prefer adding shadcn components (`Sheet`, `Table`, `Badge`,
  `AlertDialog`, `Tabs`, `Empty` variants largely exist already under
  `src/components/ui/`) over hand-building.
- Layering rules (`.dependency-cruiser.cjs`): features may import other
  features' public modules (skills↔storage types precedent), but
  `components/ui` stays generic — `FileCard` lives in
  `features/files/components/`, not `components/ui/`.
- **Will exist after 032 (verify at pre-flight; sketched from the dictated
  contract)**: `GET /files` (list: id, name, contract category,
  content_type, size_bytes, `processing_status`
  pending/processing/ready/error, current_revision_id, created/updated,
  provenance), `GET /files/{id}`, `GET /files/{id}/revisions`,
  revision-content read for text, `POST /files/upload` +
  `POST /files/confirm` (two-phase grant), `POST /files/{id}/restore`
  (revision id), `DELETE /files/{id}`, `GET /files/{id}/download`
  (SignedDownload). Route paths/verbs may differ — **transcribe, don't
  assume**.

## Commands you will need

| Purpose | Command (from `apps/web`) | Expected on success |
|---------|---------------------------|---------------------|
| Install | `pnpm install` | lockfile unchanged (no new deps in this plan) |
| Full gate | `pnpm check` | exit 0, zero warnings |
| Typecheck only | `pnpm typecheck` (or the check subset) | exit 0 |
| Dev server | `pnpm dev` | `/files` renders against a local API |
| Arch rules | `pnpm arch` | no dependency-cruiser violations |

## Scope

**In scope:**

- `apps/web/src/features/files/` (create): `types.ts`, `format.ts`,
  `diff.ts`, `api/` (`list-files.ts`, `get-file.ts`,
  `list-file-revisions.ts`, `get-revision-content.ts`,
  `request-file-upload.ts`, `confirm-file-upload.ts`,
  `restore-file-revision.ts`, `delete-file.ts`, `download-file.ts`),
  `components/` (`files-table.tsx`, `file-detail-sheet.tsx`,
  `file-revisions-list.tsx`, `revision-diff.tsx`, `file-upload-button.tsx`,
  `file-card.tsx`, `file-status-badge.tsx`), `routes/files-route.tsx`
- `apps/web/src/app/router.tsx` (add the `/files` route + tree entry)
- `apps/web/src/config/navigation.ts` (add the Files nav item)
- `apps/web/src/features/conversations/components/file-tool-row.tsx`
  (create) + `tool-call-row-registry.tsx` (register it)
- `apps/web/src/features/conversations/file-tools.ts` (create — tool-name
  constants and result-shape guards for the 034 tools)

**Out of scope (do NOT touch):**

- Composer attachment UI, attachment chips on user messages, and any
  send-message payload change — all 036.
- Backend code of any kind; no new API endpoints. If 032's API is missing
  something this UI needs (e.g. revision text read), STOP and report —
  do not add a route.
- Scratch UI. Scratch has no HTTP surface (034 decision); the chat rows
  showing `write_file` scratch results are the only scratch visibility.
- Admin hard-delete/purge and storage quota counters (follow-up per
  governance §1/§4).
- `src/components/ui/` additions beyond `pnpm dlx shadcn` vendored output
  (no hand-written primitives there).
- The SSE protocol (`stream/protocol.ts`, `stream/sse.ts`) — zero
  changes; file activity arrives through existing `tool.call`/
  `tool.result` events.

## Git workflow

- Branch: `advisor/035-files-ui`
- Commit style: `Web - Files UI`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Types and query keys

`features/files/types.ts` — transcribe from 032's landed schemas
(pre-flight). Expected shape (rename to match reality):

```ts
export type FileContractCategory = "editable_text" | "ingestible_document" | "image" | "video" | "audio"
export type FileProcessingStatus = "pending" | "processing" | "ready" | "error"

export type WorkspaceFile = {
  id: string
  name: string
  category: FileContractCategory
  content_type: string
  size_bytes: number
  processing_status: FileProcessingStatus
  current_revision_id: string
  created_at: string
  updated_at: string
}

export type FileRevision = {
  id: string
  revision_kind: "create" | "edit" | "replace" | "restore" | "import"
  content_hash: string
  size_bytes: number
  created_at: string
  actor: { kind: "user" | "agent" | "system"; id: string | null; label: string | null }
}

export type FilesListResponse = { files: WorkspaceFile[]; total: number }
export type SignedDownload = { url: string; expires_at: string }
```

`format.ts`: byte formatting, category/status labels (reuse
`lib/format.ts` helpers where they exist; keep display strings here so
components stay dumb).

`api/list-files.ts`: `filesQueryKeys` (all → workspace → lists/list,
details/detail, revisions) with the `activeWorkspaceQueryScope()` idiom
copied from `features/skills/api/list-skills.ts:15-27`;
`filesQueryOptions(params)` + `useFilesQuery(params)`
(`useSuspenseQuery`); `refetchInterval` callback returning `4000` when any
row is `pending`/`processing`, else `false` (decision 6).

**Verify**: `pnpm typecheck` passes with the new module compiled (import
it from a scratch route or rely on Step 3); eslint clean (`type` aliases
only).

### Step 2: Remaining API operations (one per file)

Each file follows the skills pattern (reads: queryOptions + hook; writes:
`useMutation` invalidating `filesQueryKeys`):

- `get-file.ts` — detail query (`filesQueryKeys.detail(fileId)`).
- `list-file-revisions.ts` — revisions query
  (`filesQueryKeys.revisions(fileId)`), newest first.
- `get-revision-content.ts` — text content for one revision; only ever
  called for editable-text files; `staleTime: Infinity` (revisions are
  immutable — 031 contract — so the cache never goes stale).
- `request-file-upload.ts` / `confirm-file-upload.ts` — the two-phase
  mutations; confirm invalidates lists + detail (the
  `skill-documents.ts:76-87` shape).
- `restore-file-revision.ts` — mutation `{fileId, revisionId}`;
  invalidates detail + revisions + lists.
- `delete-file.ts` — mutation; invalidates lists, removes detail queries.
- `download-file.ts` — **not a hook**: an exported async function
  `createFileDownload(fileId): Promise<SignedDownload>` called
  imperatively on click (decision 4, the
  `createSkillDocumentDownload` precedent).

**Verify**: `pnpm typecheck` + `pnpm lint` clean; no `fetch` outside
`client.ts`/`direct-upload.ts` (`grep -rn "fetch(" src/features/files` →
nothing).

### Step 3: Route, nav, and table

1. `routes/files-route.tsx` — the `skills-route.tsx` shell: header
   ("Workspace" eyebrow, "Files" h1), `FileUploadButton` in the header
   slot, summary `MetricCard`s (total files, total bytes, processing
   count), then `FilesTable`. Empty state card with an upload call to
   action.
2. `components/files-table.tsx` — columns: name (with category icon),
   type (contract category badge + media type as muted text), size,
   processing status (`FileStatusBadge`: `ready` plain, `processing`/
   `pending` accent + spinner, `error` destructive), updated (relative
   time). Row click sets the `fileId` search param; per-row actions menu:
   Open (signed URL, decision 4), Download, Delete (confirm dialog).
3. Router: add `filesRoute` with
   `validateSearch: (s) => ({ fileId: typeof s.fileId === "string" ? s.fileId : undefined })`
   and `lazyRouteComponent(() => import("@/features/files/routes/files-route"))`,
   mirroring `/skills` (`router.tsx:159-166`); register it in the route
   tree list (~249). Nav: add `{ label: "Files", to: "/files" }` with a
   lucide `FolderIcon`/`FilesIcon` beside the Skills entry
   (`config/navigation.ts:43-44`).

**Verify**: `pnpm dev` → `/files` renders the empty state; nav item
highlights; `pnpm check` subset (typecheck+lint) clean.

### Step 4: Detail sheet — revisions, diff, restore

1. `components/file-detail-sheet.tsx` — a `Sheet` opened when `fileId` is
   set (closing clears the param). Header: name, category, media type,
   size, status, created/updated. Body tabs: **Revisions** and (for
   editable-text) **Content** (current revision text in a scrollable
   `<pre>`). Footer actions: Open, Download, Delete.
2. `components/file-revisions-list.tsx` — revision rows: kind badge,
   actor (user name / agent name / system — 031's exactly-one-actor
   provenance), size, short content hash, created time. Two selection
   checkmarks (base / compare) enable the diff pane; a **Restore**
   button per non-current revision opens a confirm dialog whose copy
   states restore *adds a new revision* (decision 8) and calls the
   restore mutation.
3. `components/revision-diff.tsx` + `diff.ts` — fetch both revisions'
   content (Step 2's immutable-cached query), run the LCS line diff
   (decision 3), render added/removed/context lines with
   green/red/muted styling inside an `overflow-x-auto` block. Non-text
   categories render "No text diff for {category} files" and show
   metadata deltas (size, hash) instead.

**Verify**: with a seeded file + two revisions (via 032's API or the 034
tools in a dev conversation): sheet opens from row click and from a
pasted URL with `?fileId=...`; diff shows expected added/removed lines;
restore creates a new head revision and the table row's updated time
changes; delete removes the row and closes the sheet.

### Step 5: Upload flow

`components/file-upload-button.tsx` — hidden `<input type="file">`
triggered by the header button; on selection:

1. `requestFileUpload({ filename, content_type, size_bytes })` → grant
   (032 rejects contract-violating MIME/extension pairs server-side —
   surface its problem+json detail via `getErrorMessage`, the
   `conversation-composer.tsx:106-110` idiom; do not duplicate the
   contract table client-side beyond an `accept` attribute hint).
2. `uploadFileDirectly(grant.upload, file, grant.max_size_bytes)`
   (`lib/api/direct-upload.ts:5`).
3. `confirmFileUpload({ upload_token })` → invalidates the list; the new
   row appears with `processing_status` per the contract category (images
   `ready`, ingestible documents `pending` until 033 runs).

Busy state on the button during the three steps; errors render in an
inline `Alert`. Multiple-file selection loops sequentially (keep it
simple; parallel grants are a follow-up).

**Verify**: uploading a `.md` file shows a `ready` editable-text row;
uploading a PDF shows `pending` → (with 033 running) `processing` →
`ready` via the poll (decision 6); an oversized file fails client-side
with the grant's `max_size_bytes` message.

### Step 6: Chat file cards

1. `features/conversations/file-tools.ts` — constants
   `WRITE_FILE_TOOL_NAME = "write_file"`,
   `PROMOTE_SCRATCH_TOOL_NAME = "promote_scratch"`,
   `READ_FILE_TOOL_NAME = "read_file"`, `LIST_FILES_TOOL_NAME =
   "list_files"`, plus narrow guards that pull `{file_id, name, ...}` out
   of `ToolActivity.result` (034's declared output models make these
   stable; guard defensively anyway — `result` is `unknown`).
2. `features/files/components/file-card.tsx` — the shared card: category
   icon, name, size/type line, and Open/Download actions that call
   `createFileDownload` imperatively (decision 4). Takes a plain
   `{fileId, name, category?, sizeBytes?}` prop object so 036 can feed it
   from message parts without the files query.
3. `features/conversations/components/file-tool-row.tsx` — one row
   component matched by tool name (registry entry appended to
   `TOOL_CALL_ROW_DEFINITIONS`, the `skill-document-read` shape at
   `tool-call-row-registry.tsx:29-56`): `write_file` durable results and
   `promote_scratch` results render the summary line ("Wrote file" /
   "Promoted scratch to file") + a `FileCard`; `write_file` scratch
   results render a compact text row (name + bytes + expiry — no card,
   nothing durable to open); `list_files` renders a visible file/scratch
   summary with `FileCard`s for durable files; `read_file` renders visible
   rows for content reads, scratch reads, processing guidance, image reads,
   and url-mode links so the human can inspect what the agent accessed.

**Verify**: in a dev conversation with a 034-enabled agent: a durable
`write_file` (post-approval) renders a card whose Open works; a scratch
write renders the compact row; conversations from before this plan still
render (registry fall-through untouched). If 034 is not yet implemented,
verify instead with a mocked `ToolActivity` in a temporary story-style
render and note it in the completion report.

### Step 7: Gate

Run the full gate and fix everything it raises:

```bash
cd apps/web && pnpm check
```

Zero eslint warnings, prettier clean, knip clean (every exported helper in
`files/` is consumed — trim speculative exports), dependency-cruiser clean
(no route-shell imports from features, `FileCard` not in
`components/ui/`), build succeeds.

**Verify**: `pnpm check` exit 0.

## Test plan

There is no frontend test framework (AGENTS.md); the gate is static plus
manual verification. The manual matrix that must pass before done:

- Files table: empty state, populated list, status badge for all four
  `processing_status` values, poll stops when nothing is in flight.
- Detail sheet: URL-driven open/close, revisions list with mixed
  user/agent actors, text diff between two chosen revisions, restore
  round-trip, delete round-trip.
- Upload: happy path per category, contract-rejected type, oversized
  file, network failure between PUT and confirm (row must not appear;
  re-upload works).
- Chat: durable write card, scratch compact row, url-mode read card,
  pre-existing conversations unaffected.
- Workspace switch: `/files` in workspace B never shows workspace A rows
  (the workspace-scoped query keys doing their job).

## Done criteria

- [ ] `pnpm check` exits 0 from `apps/web` (typecheck, eslint zero
      warnings, prettier, knip, dependency-cruiser, build)
- [ ] `/files` route registered with `lazyRouteComponent`, nav item live,
      detail sheet driven by the `fileId` search param
- [ ] All API access goes through `apiRequest` / `uploadFileDirectly` —
      `grep -rn "fetch(" apps/web/src/features/files` returns nothing
- [ ] `types.ts` uses `type` aliases only and matches 032's landed
      response schemas field-for-field
- [ ] Signed URLs fetched imperatively on click; none stored in the query
      cache
- [ ] Chat registry renders 034 tool rows; unknown tools still fall
      through to the generic row
- [ ] No new npm dependencies (diff is hand-rolled)
- [ ] Manual matrix above completed against a local API (state which
      rows were exercised with 033/034 present vs mocked)
- [ ] `docs/plans/000_README.md` status row updated (add the 035 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- 032's routes are not implemented at execution time, or their response
  shapes cannot express this UI (e.g. no revision-content read for text
  files, no restore endpoint) — report the gap; do not add backend code.
- The uncommitted `message-parts`/`tool-call-row-registry` working-tree
  state at planning time has been reshaped so that
  `TOOL_CALL_ROW_DEFINITIONS` or `ToolActivity` no longer match the
  "Current state" excerpts — re-anchor before Step 6.
- You feel the need to touch `stream/protocol.ts` or `stream/sse.ts` —
  file activity must ride existing events; a new event name requires the
  client-first protocol change process (000_README skills precedent) and
  is not this plan.
- A `features/files/` directory already exists.
- The design requires a diff/virtualization/upload library — the
  decisions above say no; report if they prove wrong rather than adding
  dependencies.
- `pnpm check` fails on `main` before your changes.

## Maintenance notes

- **036 reuses `FileCard`** for user-message attachment chips — keep its
  props primitive (`{fileId, name, ...}`) and free of query-cache
  assumptions so message parts can drive it.
- **Processing-status polling** is deliberately dumb. If 033's status
  surface later grows a push channel or a jobs-status route, replace the
  `refetchInterval` in exactly one place (`list-files.ts`).
- **Revision immutability is a cache contract**: `staleTime: Infinity` on
  revision content is only correct while 031's DB-level immutability
  holds. If a future plan ever mutates revisions (it should not), this
  cache breaks silently — the reviewer of any such plan should grep for
  `get-revision-content`.
- The admin purge surface and workspace storage-usage counter (governance
  §1 hard-delete row, §4 storage quota) are the natural next slice on
  this page — a follow-up, not scope creep here.
- Reviewers should scrutinize: search-param handling (sheet must not
  trap focus or break back-button), the diff on pathological inputs
  (10k-line files — cap rendered lines with a "diff too large" fallback),
  and that delete invalidation also removes revision/detail queries for
  the deleted id.
