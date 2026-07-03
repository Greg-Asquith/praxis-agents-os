# Plan 019: Build the skills management UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat ccb721b..HEAD -- apps/web/src/features/agents apps/web/src/app/router.tsx apps/web/src/config/navigation.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (The check is deliberately scoped
> to this plan's anchors: `features/conversations/` was heavily reshaped by
> `603fff7`/`6af36b5` — that churn is expected and out of scope here.
> Anchors re-verified 2026-07-03 at `9208c47`: agent-form-model
> `skill_ids: []` now at l.210, router agent routes at l.132-158.)

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: LOW
- **Depends on**: docs/plans/complete/016-skills-backend-crud.md,
  docs/plans/complete/017-skill-documents-pipeline.md (documents section only — the
  CRUD screens work with 016 alone)
- **Category**: direction (feature foundation)
- **Planned at**: commit `ccb721b`, 2026-07-01

## Why this matters

Skills exist in the API (plans 016/017) but users cannot create, edit, upload
documents to, or assign them. This plan adds the `features/skills` module —
list, create, edit, delete, document management — and replaces the placeholder
"Skills" section in the agent form with a real multi-select, wiring
`skill_ids` end to end. The UI also teaches good skill authoring: the
name+description are what the agent sees on every turn, so the form copy makes
that explicit.

## Current state

All paths relative to `apps/web`. Stack: Vite + React 19, TanStack Router
(code-based, all routes in `src/app/router.tsx`), TanStack Query, Tailwind v4,
shadcn-style primitives on `@base-ui/react` in `src/components/ui/`
(`button, card, dialog, field, input, label, select, table, tabs, textarea,
alert, badge, empty-state, responsive-list, skeleton, separator, avatar,
dropdown-menu`). No toast library (inline `<Alert>` is the feedback pattern),
no checkbox/combobox primitives. Strict TS (`verbatimModuleSyntax` — use
`import type`), kebab-case filenames, every file starts with a
`// apps/web/src/...` path comment.

- **Feature layout exemplar** — `src/features/agents/`: `api/` (one file per
  operation), `components/`, `routes/`, `types.ts`. Query keys are
  workspace-scoped; `src/features/agents/api/list-agents.ts:15-26`:

  ```ts
  export const agentsQueryKeys = {
    all: ["agents"] as const,
    workspace: () => [...agentsQueryKeys.all, activeWorkspaceQueryScope()] as const,
    details: () => [...agentsQueryKeys.workspace(), "detail"] as const,
    detail: (agentId: string) => [...agentsQueryKeys.details(), agentId] as const,
    lists: () => [...agentsQueryKeys.workspace(), "list"] as const,
    list: (params: ListAgentsParams = {}) => [...agentsQueryKeys.lists(), params] as const,
  }
  ```

  with `activeWorkspaceQueryScope()` reading
  `getActiveWorkspaceSlug()` from `@/features/workspaces/workspace-context`.
  Reads: `queryOptions` + `useSuspenseQuery`. Mutations: `useMutation` +
  `invalidateQueries` on success (see `api/create-agent.ts`). HTTP via
  `apiRequest<T>(path, { method, body, query })` from `@/lib/api/client`
  (cookies + CSRF handled there).
- **Routing** — `src/app/router.tsx` declares agents routes at lines ~127-143:
  `/agents` (list), `/agents/new`, `/agents/$agentId`, each
  `createRoute({ getParentRoute: () => appRoute, path, component })`, then
  added to `appRoute.addChildren([...])`. Skills mirrors this exactly.
- **Navigation** — `src/config/navigation.ts` exports `mainNavigation`; items
  look like:

  ```ts
  { label: "Agents", to: "/agents", icon: BotIcon, disabled: false },
  ```

  The shell consumes the array in both
  `src/components/shell/primary-navigation.tsx` (desktop sidebar) and
  `src/components/shell/mobile-menu.tsx` — adding an item to `mainNavigation`
  is the only nav change needed.
- **List page pattern** — `src/features/agents/components/agents-table.tsx`:
  a `<Table>` for `md+` plus `ResponsiveList` cards for mobile, and an
  `EmptyState` when empty:

  ```tsx
  if (agents.length === 0) {
    return (
      <EmptyState
        action={<Button render={<Link to="/agents/new" />}><PlusIcon data-icon="inline-start" /> New agent</Button>}
        description="Create the first workspace agent to start conversations and configure approval policies."
        icon={<BotIcon className="size-5" />}
        size="compact"
        title="No agents yet"
      />
    )
  }
  ```

- **Form pattern** — `src/features/agents/components/agent-form.tsx` (mode:
  `"create" | "edit"`, single `useState<AgentFormState>`, sections composed of
  `AgentFormSection`), with a pure model module
  `agent-form-model.ts` (`initialAgentFormState`, `validateAgentFormState`,
  `buildAgentPayload`, `isAgentFormDirty`). Validation is hand-rolled
  (`{fieldId, label, message}[]`), feedback is inline `<Alert>`.
- **The placeholder to replace** —
  `src/features/agents/components/agent-state-section.tsx` renders a read-only
  "Skills" card saying "Skill management is not available in this form yet",
  fed by `agent-form.tsx:163`
  (`<AgentStateSection skillIds={agent?.skill_ids ?? []} />`).
- **The multi-select pattern to copy** —
  `src/features/agents/components/agent-delegation-section.tsx`: a `Select`
  of candidates + an "Allow" `Button` that appends to a string-id array in
  form state, plus removable rows with an `XIcon` button. This is the
  canonical assign-N-items control; reuse its structure verbatim.
- **`skill_ids` in the form model** — `agent-form-model.ts` currently
  hardcodes it away: `buildAgentPayload` returns
  `{ ...basePayload, skill_ids: [], slug: ... }` in create mode (line ~210)
  and **omits** `skill_ids` in edit mode; `AgentFormState` has
  `allowedAgentIds: string[]` but no `skillIds`; `initialAgentFormState` reads
  `agent?.allowed_agent_ids ?? []` (line ~108); `isAgentFormDirty` compares
  `allowedAgentIds` with `stringArraysEqual`.
- **Upload flow exemplar** — three-step signed upload:
  `src/features/workspaces/api/workspace-icon.ts` (create-grant mutation →
  `uploadFileDirectly` → confirm mutation),
  `src/lib/api/direct-upload.ts::uploadFileDirectly(upload, file, maxSizeBytes)`
  (raw `fetch` PUT to `upload.url`, `credentials: "omit"`, client-side size
  check, no progress events), and the UI wiring in
  `src/features/workspaces/components/workspace-settings-form.tsx:54-89`
  (plain `<Input type="file">` → local selection state → sequential
  create/upload/confirm in one try/catch, `isSaving` from combined
  `isPending`). Grant types live in `src/lib/storage.ts`
  (`AssetUploadRequest`, `AssetUploadGrant`).
- **Backend contracts this UI consumes** (from plans 016/017):
  - `GET/POST /skills/`, `GET/PATCH-or-PUT/DELETE /skills/{id}` — `SkillRead`
    has `id, name, human_name, description, instructions, documentation_refs,
    is_active, is_favorite, last_used_at, created_at, updated_at`; list
    response `{skills, total, limit, offset}`. Name rule:
    `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤64; description ≤1024; instructions ≤20000.
    **Check the landed plan-016 code for the actual update verb (PATCH vs PUT)
    and mirror it.**
  - `POST /skills/{id}/documents/upload` → `AssetUploadGrant`;
    `POST /skills/{id}/documents/confirm` (body `{upload_token}`) →
    document entry; `GET /skills/{id}/documents`;
    `GET /skills/{id}/documents/{name}/markdown`;
    `GET /skills/{id}/documents/{name}/download` → signed download;
    `DELETE /skills/{id}/documents/{name}`. Upload request body adds
    `document_name` (snake_case, `^[a-z0-9]+(_[a-z0-9]+)*$`) to the standard
    `{filename, content_type, size_bytes}`. **Read the landed plan-017 route
    schemas and match them exactly.**
- **Quality gate** — `package.json` scripts: `check` =
  `typecheck && lint && format:check && deadcode && arch && build`. `deadcode`
  is knip: do not export anything unused. `arch` is dependency-cruiser
  (`.dependency-cruiser.cjs`): if it forbids a cross-feature import you need,
  STOP and report rather than loosening the rules.

## Commands you will need

| Purpose   | Command (run from `apps/web`)          | Expected on success |
|-----------|----------------------------------------|---------------------|
| Install   | `pnpm install`                         | exit 0              |
| Typecheck | `pnpm typecheck`                       | exit 0              |
| Lint      | `pnpm lint`                            | exit 0 (zero warnings) |
| Full gate | `pnpm check`                           | exit 0              |
| Dev smoke | `pnpm dev` (+ API running)             | screens render      |

## Scope

**In scope**:

- `apps/web/src/features/skills/**` (create: `types.ts`, `api/*`,
  `components/*`, `routes/*`)
- `apps/web/src/app/router.tsx` (three routes)
- `apps/web/src/config/navigation.ts` (one nav item)
- `apps/web/src/features/agents/components/agent-form.tsx`,
  `agent-form-model.ts` (wire `skillIds`)
- `apps/web/src/features/agents/components/agent-skills-section.tsx` (create)
- `apps/web/src/features/agents/components/agent-state-section.tsx` (delete)
- `apps/web/src/features/agents/types.ts` (only if a type tweak is needed —
  `skill_ids` already exists on `Agent`)

**Out of scope** (do NOT touch):

- The conversations feature and stream code — chat-side skill UI is plan 020.
- `src/lib/api/*`, `src/lib/storage.ts`, `src/components/ui/*` — reuse, don't
  modify. If a UI primitive seems missing, compose from existing ones.
- Any new dependency (no toast lib, no combobox lib, no form lib).
- Backend files.

## Git workflow

- Branch: `advisor/019-skills-management-ui`
- Commit style: `Web - Add Skills Management UI`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Types and API modules

`features/skills/types.ts` — `Skill`, `SkillsListResponse`,
`SkillCreateRequest`, `SkillUpdateRequest`, `SkillDocument`,
`SkillDocumentsListResponse` as plain type aliases with snake_case fields
matching the backend schemas (open the landed backend `services/skills/schemas.py`
and `services/skills/documents/domain.py` and transcribe — do not guess).

`features/skills/api/`:

- `list-skills.ts` — `skillsQueryKeys` factory + `skillsQueryOptions` +
  `useSkillsQuery`, copied structurally from `list-agents.ts` (workspace
  scoping included).
- `get-skill.ts`, `create-skill.ts`, `update-skill.ts`, `delete-skill.ts` —
  copy the corresponding agents api files, invalidating `skillsQueryKeys.lists()`
  / `detail(id)` appropriately.
- `skill-documents.ts` — `skillDocumentsQueryOptions(skillId)` (GET list) plus
  mutations `useCreateSkillDocumentUploadMutation`,
  `useConfirmSkillDocumentUploadMutation`, `useDeleteSkillDocumentMutation`,
  modeled on `workspace-icon.ts`; reuse `AssetUploadGrant` from
  `@/lib/storage`.

**Verify**: `pnpm typecheck` → exit 0.

### Step 2: List page

- `features/skills/components/skills-table.tsx` — copy the
  `agents-table.tsx` dual-render structure. Columns: name (link to detail),
  human name, description (truncated), documents count
  (`Object.keys(documentation_refs).length`), active badge, last used.
  EmptyState: icon `SparklesIcon`, title "No skills yet", description
  "Create a skill to package instructions and reference documents your agents
  can activate on demand.", action → `/skills/new`.
- `features/skills/routes/skills-route.tsx` — copy `agents-route.tsx` shape
  (header, stat cards optional — a simple Card-wrapped table is fine, match
  the agents route's structure).

**Verify**: `pnpm typecheck && pnpm lint` → exit 0.

### Step 3: Create/edit form

- `features/skills/components/skill-form-model.ts` — pure module:
  `SkillFormState` (`name`, `humanName`, `description`, `instructions`,
  `isActive`, `isFavorite`), `initialSkillFormState(skill | null)`,
  `validateSkillFormState` (required name matching
  `/^[a-z0-9]+(-[a-z0-9]+)*$/` and ≤64 with the message
  "Use lowercase letters, numbers, and hyphens (e.g. brand-voice).";
  required description ≤1024; required instructions ≤20000),
  `buildSkillPayload(state, mode)`, `isSkillFormDirty`. Copy the
  agent-form-model idioms (validation entries, `optionalText`).
- `features/skills/components/skill-form.tsx` — sections via the same
  `AgentFormSection`-style wrapper (create a local `SkillFormSection` copy in
  `features/skills/components/` rather than importing across features if
  dependency-cruiser complains; check `arch` early):
  - **Identity**: name `Input` (helper: "The agent's stable identifier for
    this skill."), human name `Input`, description `Textarea` with helper
    copy: *"Always visible to the agent — it decides when to activate this
    skill from the name and description alone. Say what the skill does and
    when to use it."*
  - **Instructions**: `Textarea` (tall), helper: *"Loaded only when the agent
    activates the skill. Keep the description above self-sufficient."*
  - **State**: active / favorite selects matching the agent form's
    `isActive`/`isFavorite` handling.
- `features/skills/routes/new-skill-route.tsx` and
  `skill-detail-route.tsx` — copy `new-agent-route.tsx` /
  `agent-detail-route.tsx` (create → navigate to detail; edit with save +
  delete using `window.confirm`, inline `<Alert>` for saved/error states).

**Verify**: `pnpm typecheck && pnpm lint` → exit 0.

### Step 4: Documents section (edit screen only)

`features/skills/components/skill-documents-section.tsx`, rendered in
`skill-detail-route.tsx` below the form:

- List from `skillDocumentsQueryOptions(skillId)`: name, filename, size,
  status badge (`ready` / `failed` with the error in a tooltip/`title`),
  download button (call the download endpoint via `apiRequest`, then
  `window.open(signed.url)` — check the landed response shape), delete button
  (`window.confirm`).
- Upload control: document-name `Input` (validated
  `/^[a-z0-9]+(_[a-z0-9]+)*$/`, helper "Semantic name the agent uses, e.g.
  api_reference") + `<Input type="file" accept=".pdf,.docx,.txt,.md">` +
  upload `Button`. On submit run the three-step sequence exactly as
  `workspace-settings-form.tsx:54-89` does (grant → `uploadFileDirectly` →
  confirm → invalidate the documents query), surfacing errors via inline
  `<Alert>`. A confirm response with `status: "failed"` is a success HTTP-wise
  — show it as "Uploaded, but conversion failed: <error>".
- Empty state: compact `EmptyState` ("No documents", "Upload reference
  documents the agent can read after activating this skill.").

**Verify**: `pnpm typecheck && pnpm lint` → exit 0.

### Step 5: Routing and navigation

- `src/app/router.tsx`: add `skillsRoute` (`/skills`), `newSkillRoute`
  (`/skills/new`), `skillDetailRoute` (`/skills/$skillId`) next to the agents
  routes, and include them in `appRoute.addChildren([...])`.
- `src/config/navigation.ts`: add
  `{ label: "Skills", to: "/skills", icon: SparklesIcon, disabled: false }`
  between Agents and Workspaces (import `SparklesIcon` from `lucide-react`).

**Verify**: `pnpm typecheck` → exit 0; `pnpm dev` → `/skills` renders the
empty state and the nav item highlights.

### Step 6: Agent form skills assignment

- `agent-form-model.ts`:
  - Add `skillIds: string[]` to `AgentFormState`.
  - `initialAgentFormState`: `skillIds: agent?.skill_ids ?? []`.
  - `isAgentFormDirty`: add `!stringArraysEqual(current.skillIds, initial.skillIds)`.
  - `buildAgentPayload`: put `skill_ids: state.skillIds` in `basePayload`
    (both modes) and delete the hardcoded `skill_ids: []` from the create
    branch. Edit mode now sends `skill_ids` — that is correct and safe: the
    backend treats a present field as an explicit set.
- Create `agent-skills-section.tsx` modeled line-for-line on
  `agent-delegation-section.tsx`: props `{skillIds, setField, skills}` where
  `skills` comes from `useSkillsQuery()` (active skills only); Select of
  unassigned skills + "Attach" button; removable rows showing
  `human_name ?? name` with the description as secondary text. Handle the
  "assigned skill no longer in the list" case the way the delegation section
  handles unknown agent ids (render the raw id with a note) — read how it does
  this and match.
- In `agent-form.tsx`, replace `<AgentStateSection skillIds={...} />` with the
  new section and delete `agent-state-section.tsx` (knip will fail the gate if
  the dead file remains).

**Verify**: `pnpm typecheck && pnpm lint` → exit 0;
`grep -rn "agent-state-section" src/` → no matches.

### Step 7: Full gate

**Verify**: `pnpm check` → exit 0 (typecheck, lint, prettier, knip, dependency-
cruiser, build all pass). If `format:check` fails, run `pnpm format` and
re-run. If `arch` fails on a cross-feature import, restructure per its message
(local copy of the section wrapper; skills api imported into features/agents
is expected to be allowed — verify against `.dependency-cruiser.cjs` rules and
STOP if it is explicitly forbidden).

## Test plan

The frontend has no unit-test runner; the gate is `pnpm check` plus a manual
smoke pass with the API running (`pnpm dev` + backend):

1. Create a skill (bad name rejected with inline message; good one lands and
   navigates to detail).
2. Upload a `.md` document → entry appears `ready`; upload a `.pdf` → entry
   appears (`ready` or `failed` shown honestly); delete an entry.
3. Attach the skill to an agent in the agent form; save; reload; the
   assignment persists. Detach; save; persists.
4. Deactivate the skill; the agent form's picker no longer offers it, and the
   existing assignment renders in the "no longer available" style.

## Done criteria

ALL must hold (run from `apps/web`):

- [ ] `pnpm check` exits 0
- [ ] `grep -rn "Skill management is not available" src/` returns no matches
- [ ] `grep -rn "skill_ids: \[\]" src/features/agents/` returns no matches
- [ ] `test ! -f src/features/agents/components/agent-state-section.tsx`
- [ ] `grep -n '"/skills"' src/config/navigation.ts` returns one match
- [ ] `git status` shows no modified files outside the in-scope list (leave
      any unrelated pre-existing working-tree changes untouched)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plans 016/017 have not landed (probe: `GET /api/v1/skills/` 404s with the
  API running, or the backend files named in "Current state" don't exist).
- The landed backend schemas differ materially from the shapes described here
  (e.g. different route paths, different manifest fields) — transcribe from
  the real code only when the difference is naming; report if structural.
- `.dependency-cruiser.cjs` forbids `features/agents` → `features/skills`
  imports (needed for the picker) — report; do not edit the ruleset.
- `pnpm check` fails on files you did not touch (baseline broken).
- You need a UI primitive that genuinely cannot be composed from
  `src/components/ui/*` — report the gap instead of adding a dependency.

## Maintenance notes

- The picker fetches up to the default list page (100 skills). If workspaces
  ever exceed that, the picker needs search/pagination — the delegation
  section will have the same problem at 100 agents; fix both together.
- Upload has no progress indication (the shared `uploadFileDirectly` uses
  `fetch`, which has no upload progress). If large PDFs make this painful,
  swap to XHR in `direct-upload.ts` for all upload flows at once — out of
  scope here.
- Plan 020 adds the chat-side activation indicator and will import
  `skillsQueryOptions` from this feature to resolve skill display names.
- Reviewers should scrutinize: `buildAgentPayload` edit mode now sending
  `skill_ids` (intended change of behavior), and knip/dependency-cruiser
  cleanliness.
