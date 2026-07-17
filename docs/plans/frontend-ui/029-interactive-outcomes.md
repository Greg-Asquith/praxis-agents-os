# Plan 029: Interactive outcomes — tool results you can act on

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against the working tree at
  `19ace81` with plan 022 applied. Part of the tool-surface series —
  see the series preamble in plan 025. This plan carries the fourth
  thread: **outcomes are interactive** (maintainer direction,
  2026-07-17).
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — this plan wires real mutations (rename) and
  audited reads (open, download) into the transcript. All actions must
  reuse the files feature's existing query/mutation layer so cache
  invalidation, CSRF, workspace scoping, and the
  preview-passive/download-audited split (settled, plan 019) hold
  automatically. No new endpoints, no new permissions.
- **Depends on**: 026 (field shells), 028 (outcome-row shape). 027 is
  file-disjoint but land it first so the series' QA story is coherent.
  Web-only.

## Goal

When the agent runs List Files, the user should see a miniature version
of the Files page — real rows with thumbnails, and real actions: click
through to the file detail modal, rename, download (maintainer
direction, 2026-07-17). A tool outcome is not a report *about* the
workspace; it is a **working view of** the workspace, collaborating in
the same objects the user manages elsewhere in the product.

Today the file rows are display-only: `ListFilesRow` renders passive
`FileCard`s and a summary `TextBlock`
(`file-tool-row.tsx:92-123`), and nothing in a transcript can open the
file modal or rename anything — the user must navigate to the Files
page and find the file again by hand.

This plan builds the pattern on workspace files (the entities we own
end to end) and records it as the template every future entity-bearing
tool follows — including external integrations: when a Google Drive (or
similar) connector lands, its search results adopt the same presenter
pattern with open/rename/share actions scoped to that provider's API.
That future work ships *with the integration*, not speculatively here.

## Current state (verified 2026-07-17, working tree at `19ace81` + 022)

- Custom presenters exist per tool family
  (`tool-call-row-registry.tsx:52-91`); file tools match on typed
  results parsed by the guards in `file-tools.ts:102-289`, which
  already carry `file_id`s (`fileCardFromRuntimeFile`,
  `file-tools.ts:316-324`).
- `FileCard` (`features/files/components/file-card.tsx`) is a passive
  display card; the conversations feature already imports it and
  `FileContentView` (`file-tool-row.tsx:5-6`) — the cross-feature
  import precedent this plan builds on.
- The files feature has the full interactive surface: centered
  `file-detail-modal.tsx` with preview-first layout (plan 019),
  `rename-file-dialog.tsx`, and one-operation API modules
  (`features/files/api/`: `get-file.ts`, `update-file.ts`,
  `download-file.ts`, `preview-file.ts`, `delete-file.ts`, …) with
  workspace-scoped query keys and cache invalidation.
- Backend file tool results expose ids/names/sizes via typed output
  models (`RuntimeToolDefinition.output_model`, `contract.py:104`) —
  the server-side contract that makes client entity parsing safe.
- Tool results in transcripts may be stale relative to the workspace
  (a listed file can be renamed or deleted after the run).

## Design decisions (this plan)

- **Actions reuse the product's real surfaces — never re-implement.**
  Clicking a file outcome opens the same `FileDetailModal` used by the
  Files page; rename goes through the same dialog/mutation; download
  through the same audited flow. The transcript is an entry point, not
  a second implementation. If a modal needs loosening to be launchable
  from outside the Files route (e.g. it currently assumes route
  context), restructure the modal's props, not the rule.
- **The entity's id is the contract; current state comes from the
  server.** The tool result contributes identity and a snapshot label;
  opening the modal fetches live data via `get-file.ts` queryOptions.
  A file deleted since the run yields the modal's error/empty state —
  never a crash, never fabricated data. After a rename from the
  transcript, the row keeps its historical snapshot text (transcripts
  are records) while the modal and Files page show the new name; do
  not rewrite transcript content.
- **A miniature of the Files page, not a new widget.** `ListFilesRow`
  renders a compact list — thumbnail, name, size, updated — visually
  descended from `files-table.tsx` rows, inside a 026 field shell
  ("Files · 12"). Row click opens the modal; a kebab (or hover
  actions) offers Rename and Download. Drafts (scratch entries, no
  `file_id`) stay display-only rows.
- **Every file-bearing outcome gets the same affordance**: write_file,
  promote_scratch, and read_file rows make their `FileCard` clickable
  (open modal) with the same actions. One interaction grammar across
  the family.
- **Audit and permission behavior is inherited, not invented.**
  Previews stay passive/unaudited; opens/downloads stay audited
  (settled, plan 019). RBAC: rename uses the same mutation the Files
  page uses — if the server rejects for a read-only member, surface the
  feature's existing error copy. No client-side permission guessing
  beyond what the files feature already does.
- **External providers are recorded, not built.** The Google Drive
  scenario (search results with open/share/rename against Drive) is the
  declared direction for integration verticals; each integration ships
  its own presenter + actions against its own API surface when it
  lands. Nothing speculative lands now.

## Steps

### 1. Make the modal launchable from the transcript

- Audit `file-detail-modal.tsx` for route assumptions; expose a
  controlled `open/onOpenChange` + `fileId` API if it does not already
  have one. It must fetch via the existing `get-file.ts` queryOptions
  so transcript-launched modals share cache with the Files page.
- Confirm `pnpm arch` (dependency-cruiser) accepts the deepened
  conversations→files imports; if a rule fires, restructure exports
  (e.g. a `features/files/public.ts` surface) rather than editing
  rules.

### 2. Interactive file rows

- New `features/conversations/components/file-entity-row.tsx` (name
  indicative): compact row — `FileThumbnail`, name, size · updated —
  as a button opening the modal, plus inline/kebab actions Rename
  (opens `RenameFileDialog`) and Download (existing audited flow).
  Built inside the 026 field-shell geometry so it sits flush with
  wells.
- `ListFilesRow` (`file-tool-row.tsx:71-124`): replace the summary
  `TextBlock` + stacked `FileCard`s with the field-shell list
  ("Files · {n}") of interactive rows; scratch entries render as
  display-only rows beneath ("Drafts · {n}").
- Write/promote/read rows: wrap their `FileCard` render sites
  (`file-tool-row.tsx:159,198,246,282,330,359`) in the same
  open-modal/action affordance when a `file_id` is present.

### 3. Post-action coherence

- Rename/download from the transcript must invalidate/refresh exactly
  what the Files page flows invalidate (they already do if the same
  hooks are reused — verify, do not duplicate). The open modal reflects
  the rename immediately; the transcript row keeps its snapshot.
- Deleted-file path: modal shows its not-found state; row actions on a
  404 surface the feature's error toast/copy, not a blank.

### 4. Tests & verify

- Unit-test any new pure helpers (e.g. mapping tool results to entity
  rows). Interaction coverage rides on the existing files feature
  tests; do not component-test the modal from the transcript side.
- `cd apps/web && pnpm check`.
- Manual QA (`pnpm dev`, both themes, desktop + mobile):
  - Agent runs list_files: miniature list renders; clicking a row
    opens the detail modal with live data and working preview.
  - Rename from the transcript: Files page shows the new name; the
    transcript row still shows the historical name; reopening the
    modal shows the new name.
  - Download works and is audited (spot-check the audit trail);
    preview stays unaudited.
  - Delete the file from the Files page, then click its transcript
    row: not-found state, no crash.
  - write_file / promote_scratch outcomes open the modal for the
    created file.
  - Keyboard-only: rows and actions reachable, focus returns to the
    row on modal close.
  - A read-only workspace member sees rename rejected with the
    feature's standard error.

## STOP conditions

- An action would need a new API endpoint, permission, or audit
  exemption — stop; this plan only composes existing feature
  operations.
- The modal cannot be decoupled from its route without duplicating it —
  stop and report the coupling; duplication is the failure mode this
  plan exists to prevent.
- Cache updates from transcript-launched mutations diverge from
  Files-page behavior (stale lists, phantom names) — stop; shared
  hooks/keys are the acceptance bar.
- You find yourself building Drive/external-provider UI — stop; that
  ships with the integration vertical.
