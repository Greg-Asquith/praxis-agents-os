# Plan 019: Files — thumbnails, detail modal with preview, rename

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-16 (anchors verified against `75da3b5`; the files
  feature is untouched by the in-flight 014 working-tree changes)
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — this is the first plan in the series that touches
  `apps/api` (a scoped widening of the preview grant). The audit-trail
  property of previews vs downloads is a deliberate backend decision that
  must be preserved, not weakened.
- **Depends on**: 011, 013 (both landed). Independent of 014–018 — the
  files feature directory is disjoint from everything they touch, so this
  can run in a parallel worktree.

## Goal

The Files section becomes something a non-technical user can browse and
trust:

1. The list shows **thumbnails** for images (icons for everything else).
2. File details open in a **centered modal**, not a right-hand sheet.
3. **Images, videos, HTML, and PDFs render inline** in that modal, always
   — the preview is the point of opening a file, not a tab you hunt for.
4. Technical metadata (revision UUIDs, content hashes, raw actor ids)
   disappears from the default view — hidden entirely or behind one
   "Technical details" disclosure — and only appears when applicable to
   the file type.
5. Files can be **renamed** (and their description edited).

## Current state (verified 2026-07-16)

Frontend (`apps/web/src/features/files/`):

- `components/files-table.tsx` (379 lines): desktop table + mobile
  `ResponsiveList`, both showing a generic `FileCategoryIcon` (lines
  357-379, `size-9` muted tile with a lucide icon per category). Row
  click opens details; a dropdown has Open / Download / Delete — no
  Rename.
- `components/file-detail-sheet.tsx` (218 lines): despite the name it is
  a `Dialog` styled as a full-height right sheet via overrides on
  `DialogContent` (line 84: `top-0 right-0 left-auto h-dvh … rounded-none`).
  Header shows category + status badges, name, and a
  `content_type · bytes · N revisions` line. Body: a `FileMetadata` `<dl>`
  that always shows **Created / Updated / Current revision (full UUID) /
  Content hash** (lines 178-205), then tabs — "Revisions" always, and
  "Content" only for `editable_text`. Media files get no preview at all.
- `components/file-revisions-list.tsx` (230 lines): every revision row
  shows Base/Compare picker buttons **even for files that can never
  diff** (images, video, PDFs), with a placeholder box "Text diff is
  available for editable text files" (lines 108-112) shown to exactly
  the users who can do nothing about it. The meta line (lines 149-152)
  is `User 8831f56e · 279.4 KB · b343d525b2f6 · date` — raw id prefixes
  via `actorLabel` (lines 219-230) and a content-hash fragment.
- `components/file-content-view.tsx`: renders markdown, sandboxed-iframe
  HTML (`sandbox=""` srcDoc), or `<pre>` from revision text content —
  reusable as-is for the modal's text/HTML preview.
- `api/preview-file.ts`: `filePreviewQueryOptions(fileId)` POSTs
  `/files/{id}/preview` for a signed inline URL, `staleTime` 4 min
  (under the 10-min grant expiry). Sole consumer today:
  `features/conversations/components/message-attachment-card.tsx:28`,
  which already proves the `<img src={grant}>` pattern works.
- `routes/files-route.tsx`: `?fileId=` search param drives the detail
  surface — keep this deep-linking mechanism.
- No `api/update-file.ts` exists yet.

Backend (`apps/api`):

- `PATCH /files/{file_id}` (`routes/files/update_file.py`,
  `services/files/update_file.py`) already accepts
  `{ name?, description? }` (`FileUpdateRequest`,
  `services/files/domain.py:97-106`). **Rename needs no backend work.**
- `services/files/create_file_preview.py:26-34` rejects everything but
  `FileCategory.IMAGE`, and deliberately skips the file-read audit
  event (previews are passive; opens/downloads via
  `create_file_download.py` record `AuditAction.READ`).
- The file contract (`services/files/contract.py`): editable_text =
  txt/md/csv/json/html; ingestible_document = pdf/docx/pptx/xlsx;
  image = png/jpeg/webp; video = mp4/mov. No audio content types are
  registered yet (the frontend `audio` category is forward-looking —
  icon only, no preview path needed).
- Route tests live in `apps/api/tests/routes/files/test_files_routes.py`.

## Steps

### 1. Backend — widen the preview grant to all inline-renderable media

In `services/files/create_file_preview.py`, replace the image-only check
with an allowlist: `FileCategory.IMAGE`, `FileCategory.VIDEO`, and
`content_type == "application/pdf"`. Everything else (docx/pptx/xlsx,
plus any future audio) keeps the validation error, with the message
updated to say previews exist for images, video, and PDFs.

- **Preserve the no-audit property and its docstring intent**: previews
  stay passive and unaudited; Open/Download keep recording
  `AuditAction.READ`. Do not add audit calls here and do not remove them
  from `create_file_download`.
- HTML needs no backend change — it renders from revision text content
  through the existing sandboxed iframe.
- Add route-test coverage in `tests/routes/files/test_files_routes.py`:
  preview allowed for an image, a video, and a PDF; still rejected for
  a docx. Follow the existing factory/fixture patterns.
- Gate: `cd apps/api && uv run ruff check . && uv run pytest
  tests/routes/files tests/services/files` (with `TEST_DATABASE_URL`
  set, or via `make api-test`).

### 2. List thumbnails

New `components/file-thumbnail.tsx`: one component used by both the
desktop table cell and the mobile row (and sized by prop).

- For `category === "image"` with `processing_status === "ready"`:
  `useQuery(filePreviewQueryOptions(file.id))`, render the signed URL in
  an `<img>` with `object-cover`, rounded, `loading="lazy"`, empty `alt`
  (the name is adjacent text). While loading and on any error, fall back
  to the existing category icon tile — a thumbnail is decoration, never
  a failure state.
- Every other category renders the icon tile (move `iconForCategory`
  into this component; delete `FileCategoryIcon` from
  `files-table.tsx`).
- Bump the tile to `size-10` in the table so image thumbnails read as
  pictures, not specks; keep the muted border treatment for icon tiles
  so mixed lists stay calm.
- Scale note: the list caps at 100 files and only image rows fire a
  preview POST; grants are cached 4 min per file. Accept that for now —
  if it ever needs batching, that is a backend endpoint, not a client
  hack (see STOP conditions).

### 3. Detail modal — centered, preview-first

Rename `file-detail-sheet.tsx` → `file-detail-modal.tsx` (components
`FileDetailModal`; update the import in `files-route.tsx`). Drop the
sheet overrides on `DialogContent` — it becomes a standard centered
modal, `sm:max-w-3xl`, body scrolling internally (`max-h` grid rows as
now, minus the `h-dvh`/`rounded-none`/edge-pinning classes).

Layout, top to bottom:

1. **Header**: file name as title (truncated), with a Rename affordance
   (step 4). Meta line in plain words: category label · size ·
   "Updated {date}". Status badge only when `processing_status` is not
   `ready`; category badge stays. Drop the raw `content_type` and the
   "N revisions" count from the header — the history section carries
   that.
2. **Preview, always present for visual types** (not a tab):
   - `image` → `<img>` from the preview grant, contained (`max-h`,
     `object-contain`, subtle checkered/muted backdrop token).
   - `video` → `<video controls>` from the preview grant.
   - `application/pdf` → `<iframe>` from the preview grant (`h-96`-ish,
     executor judges), `title` set.
   - `text/html` → existing `FileContentView` sandboxed iframe from
     current-revision content.
   - other `editable_text` (md/txt/csv/json) → `FileContentView` as
     today, promoted out of the "Content" tab.
   - Non-previewable (docx/pptx/xlsx, audio, or preview still
     processing) → no dead placeholder; show nothing beyond the header,
     or a single quiet line ("Preview isn't available for this file
     type — use Open or Download").
   - While `processing_status` is `pending`/`processing`, say so in
     outcome language ("Praxis is still preparing this file").
3. **Details**: Created / Updated only (plus the processing error, in
   `--destructive`, when present). **Current revision UUID and content
   hash leave the default view** — put them (full hash, revision id)
   inside a native `<details>` "Technical details" disclosure at the
   very bottom of the body, closed by default (the settled disclosure
   pattern; also matches the non-technical-user decision).
4. **History** (formerly the "Revisions" tab — with Content promoted to
   preview, tabs go away entirely; history is a section under the
   preview). See step 5.
5. **Footer**: unchanged actions — Delete (destructive, confirm dialog),
   Download, Open.

Remove the `Tabs` usage from this file once both tabs are dissolved.

### 4. Rename & description edit

- New `api/update-file.ts`: `useUpdateFileMutation` PATCHing
  `/files/{fileId}` with `{ name?, description? }`, invalidating the
  files list key and seeding/invalidating the detail key — follow the
  one-operation-per-file pattern and `filesQueryKeys`.
- UI: a small "Rename File" dialog (name + description fields, native
  form + `lib/forms.ts` helpers, no form library) opened from a pencil
  / "Rename" button beside the modal title, **and** from a new
  "Rename" item in the table row's dropdown menu (above the
  destructive Delete, with a separator). Title Case labels: "Rename
  File", pending "Saving".
- Validation mirrors the backend: name required (1–255 chars),
  description optional (≤4096). Surface API errors through
  `getErrorMessage` like the neighbors.

### 5. History section clarity

In `file-revisions-list.tsx` (rename user-facing copy, keep filenames):

- **Version, not revision**: badges read "Version 2", the section is
  "History", restore confirm becomes "Restore this version? / A new
  current version will be created." (`fileRevisionKindLabel` values are
  fine as-is.)
- **Base/Compare buttons and the diff panel render only for
  `editable_text` files.** For everything else the rows show no diff
  controls and the "Text diff is available for editable text files"
  placeholder box (lines 108-112) is deleted outright — never show a
  capability notice for a capability the file can't have.
- **Actor names, not id fragments**: resolve `created_by_user_id`
  against the memberships list (`user_display_name`, falling back to
  `user_email`, then "A teammate") and `created_by_agent_id` against
  the agents list (name, falling back to "An agent");
  `created_by_system` stays "System". Both queries are already cached
  workspace-wide (`list-memberships.ts`, `list-agents.ts` with
  `includeInactive: true` so renamed/retired agents still resolve).
  Executor picks the seam (a small hook in the files feature is fine);
  do not add a backend join for this.
- Meta line slims to `{actor} · {size} · {date}` — the content-hash
  fragment goes; it lives in the modal's Technical details disclosure.
- When a file has exactly one version, skip the Base/Compare controls
  even for text files (nothing to diff) — one calm row.

### 6. Verify

- `cd apps/api && uv run ruff check .` and the file tests from step 1
  pass; `cd apps/web && pnpm check` passes (knip: `update-file.ts` and
  `file-thumbnail.tsx` both have consumers; no orphaned exports after
  the sheet rename and Tabs removal).
- Manual QA against `pnpm dev` (API up via `make dev`), both themes,
  desktop + mobile:
  - Upload one of each: png, mp4, pdf, html, md, docx. List shows a real
    thumbnail for the png and icons for the rest.
  - Open each: png/mp4/pdf render inline (video plays, pdf scrolls),
    html renders in the sandboxed iframe (scripts stay disabled), md
    renders as markdown, docx shows the quiet no-preview line. No
    revision UUID or hash visible without opening Technical details.
  - Rename from the modal and from the row dropdown; the list, modal
    title, and a subsequent download filename all reflect the new name.
  - History: text file shows Base/Compare + diff; the png shows neither
    the buttons nor the old placeholder; actor shows a real member/agent
    name; restore still works and copy says "version".
  - Deep link `?fileId=` still opens the modal directly; Esc and
    backdrop close it and clear the param.
  - Keyboard pass: row focus + Enter opens the modal, focus is trapped
    inside, rename dialog is reachable, all icon-only buttons keep
    `aria-label`s.

## STOP conditions

- The local storage provider cannot serve video or PDF such that
  `<video>`/`<iframe>` work (e.g. missing Range support breaks playback
  entirely, or content-type/disposition comes back wrong) — stop and
  report the provider gap; do not proxy content through the client or
  hack headers frontend-side.
- Widening the preview grant would require weakening signing/auth or
  changing the audit posture of downloads — stop; the audited-download /
  unaudited-preview split is deliberate.
- Thumbnail preview requests need batching to be acceptable — stop and
  propose a backend batch-grant endpoint rather than client-side
  workarounds.
- Resolving actor names cannot be done from the existing memberships and
  agents queries (e.g. revisions by users who left the workspace turn
  out to be common enough to matter) — note it and fall back to the
  generic labels; do not add a backend join inside this plan.
