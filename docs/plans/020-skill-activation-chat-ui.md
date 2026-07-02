# Plan 020: Surface skill activation in the chat UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat ccb721b..HEAD -- apps/web/src/features/conversations`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: docs/plans/018-runtime-skill-disclosure.md (activations must
  exist to render); docs/plans/019-skills-management-ui.md (skill name
  resolution — soft dependency, a fallback is specified)
- **Category**: direction (feature completeness)
- **Planned at**: commit `ccb721b`, 2026-07-01

## Why this matters

After plan 018, agents activate skills mid-conversation via the framework's
`load_capability` tool. Without UI treatment, users see a raw tool row named
"load_capability" with a `skill:{uuid}` argument and a wall of returned
instructions — confusing, noisy, and leaking prompt internals. This plan
renders activation as a compact, human-readable "Activated skill" row in both
the live stream and persisted history.

**Deliberate design decision — do not add a new SSE event.** The frontend SSE
parser hard-rejects unknown event names
(`stream/sse.ts:73-75` throws `Unsupported stream event`), so introducing a
`skill.activated` event server-side would break any client running the older
bundle mid-deploy. Everything needed already flows through the existing
protocol: live activations arrive as `tool.call`/`tool.result` events with
`name == "load_capability"`, and persisted parts carry
`tool_kind: "capability-load"`. All work here is client-side discrimination.

## Current state

All paths relative to `apps/web` unless noted. Verified facts about the wire
format (probed against the backend's pinned `pydantic-ai==2.1.0`):

- **Live stream**: a skill activation produces
  `tool.call {tool_call_id, name: "load_capability", args: {"id": "skill:<uuid>"}}`
  followed by `tool.result {tool_call_id, name: "load_capability", result: <loaded instructions>}`.
  (`args` may arrive as a JSON string rather than an object — the persisted-
  message normalizer already handles that case; handle it here too.)
- **Persisted history**: the parts serialize as
  `{part_kind: "tool-call", tool_kind: "capability-load", tool_name: "load_capability", args: ...}` and
  `{part_kind: "tool-return", tool_kind: "capability-load", tool_name: "load_capability", content: ...}`.
- The capability id format is `skill:{skill.id}` (defined in plan 018,
  `apps/api/services/agents/runtime/skills.py::skill_capability_id`).
- The document-reading tool from plan 018 (`read_skill_document`) is an
  ordinary function tool and renders fine through the existing tool row — no
  work needed for it here.

Frontend pieces:

- `features/conversations/stream/protocol.ts` — event whitelist
  (`STREAM_EVENT_NAMES`) and the discriminated `StreamEvent` union.
  **Unchanged by this plan.**
- `features/conversations/stream/reducer.ts:15-21, 146-175` — `tool.call` /
  `tool.result` land in `state.toolCalls: Record<string, ToolCallState>`:

  ```ts
  export type ToolCallState = {
    tool_call_id: string
    name: string
    args: unknown
    result: unknown
    status: "running" | "awaiting_approval" | "completed"
  }
  ```

  Activation entries therefore already exist in live state with
  `name === "load_capability"`. **The reducer needs no change** unless Step 2
  reveals the live renderer cannot distinguish them (it can, by name).
- `features/conversations/message-parts.ts` — persisted-message parser.
  `ToolActivity` (lines 13-21) has `{id, kind: "call"|"result"|"approval"|"retry"|"unknown",
  status, name, args?, result?, outcome?}`. Tool parts are matched by part
  kind at lines 156-178:

  ```ts
  if (partKind && TOOL_CALL_PART_KINDS.has(partKind)) {
    parsed.toolActivities.push({
      id: stringValue(part["tool_call_id"]) ?? partId,
      kind: "call",
      status: "running",
      name: stringValue(part["tool_name"]) ?? "tool",
      args: normalizeToolArgs(part["args"]),
    })
    return
  }
  ```

  `TOOL_CALL_PART_KINDS = {"tool-call", "builtin-tool-call", "native-tool-call"}`,
  `TOOL_RESULT_PART_KINDS = {"tool-return", ...}` — capability-load parts
  already fall into these sets (their `part_kind` is plain
  `tool-call`/`tool-return`); today they render as a generic tool row. The
  parser does **not** read the `tool_kind` field yet.
  `parseConversationMessages` (lines 54-90) post-processes: result activities
  mark matching call activities `completed`; un-resulted calls become
  `approval`/`unknown` depending on run status.
- `features/conversations/components/tool-call-row.tsx` — the collapsible
  `<details>` row used for tool activities (status icon, verb, Arguments /
  Result JSON blocks). The new activation row is a sibling of this component.
- `features/conversations/components/message-row.tsx` — renders a parsed
  message's `thinking` → `text` → `toolActivities` (via `ToolCallRow`) →
  `unsupportedParts`. This is where the activation row slots in.
- `features/conversations/components/message-list.tsx` — merges live stream
  state into renderable rows; its `buildLiveToolActivities` (around lines
  131-159 per recon — **read the actual function before editing**) converts
  `state.toolCalls` into the same `ToolActivity` shape for in-flight runs.
- Skill display names: plan 019 exposes `skillsQueryOptions` /
  `useSkillsQuery` from `@/features/skills/api/list-skills` (workspace-scoped
  TanStack Query). Skills carry `id`, `name`, `human_name`.
- Conventions: strict TS (`import type`), kebab-case files, no new deps,
  inline path comment at the top of each file. Full gate: `pnpm check`.

## Commands you will need

| Purpose   | Command (run from `apps/web`)          | Expected on success |
|-----------|----------------------------------------|---------------------|
| Install   | `pnpm install`                         | exit 0              |
| Typecheck | `pnpm typecheck`                       | exit 0              |
| Full gate | `pnpm check`                           | exit 0              |

## Scope

**In scope**:

- `apps/web/src/features/conversations/message-parts.ts` (discriminate
  capability-load parts)
- `apps/web/src/features/conversations/components/skill-activation-row.tsx` (create)
- `apps/web/src/features/conversations/components/message-row.tsx` (render the new row)
- `apps/web/src/features/conversations/components/message-list.tsx` (live-stream mapping)
- `apps/web/src/features/conversations/skill-activation.ts` (create — small
  pure helpers: capability-id parsing, display-name resolution types)

**Out of scope** (do NOT touch):

- `stream/protocol.ts`, `stream/sse.ts`, `stream/reducer.ts` — the wire
  protocol and reducer are deliberately unchanged. If you believe a reducer
  change is required, re-read Step 2; if still required, STOP and report.
- Backend files — plan 018 already emits everything needed.
- `tool-call-row.tsx` — regular tools (including `read_skill_document`) keep
  their existing rendering.
- Approval flow components.

## Git workflow

- Branch: `advisor/020-skill-activation-chat-ui`
- Commit style: `Web - Show Skill Activation In Chat`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pure helpers — `features/conversations/skill-activation.ts`

```ts
export const LOAD_CAPABILITY_TOOL_NAME = "load_capability"
export const SKILL_CAPABILITY_PREFIX = "skill:"

export function skillIdFromCapabilityArgs(args: unknown): string | null
```

`skillIdFromCapabilityArgs` accepts the activity's args (object **or** JSON
string — parse defensively like `normalizeToolArgs` in `message-parts.ts`),
reads `id`, and returns the UUID after `SKILL_CAPABILITY_PREFIX`, or `null`
for non-skill capability loads (render those as a plain tool row).

**Verify**: `pnpm typecheck` → exit 0.

### Step 2: Discriminate in the persisted parser

In `message-parts.ts`:

- Extend `ToolActivity` with an optional field: `toolKind?: string`. Keep
  `kind` untouched — the completed/approval post-processing in
  `parseConversationMessages` keys off `kind: "call"|"result"` and must keep
  working for activations too (an activation has a call and a return like any
  tool).
- In the `TOOL_CALL_PART_KINDS` branch and the `TOOL_RESULT_PART_KINDS`
  branch, add `toolKind: stringValue(part["tool_kind"]) ?? undefined` to the
  pushed activity. Mind `exactOptionalPropertyTypes`: only include the
  property when defined, e.g. spread `...(toolKind ? { toolKind } : {})`.

**Verify**: `pnpm typecheck` → exit 0.

### Step 3: The activation row — `components/skill-activation-row.tsx`

A compact, non-collapsible row (visually lighter than `ToolCallRow` — model
its container styling on the collapsed `ToolCallRow` summary line so it sits
naturally in the same stack):

- Props: `{ activity: ToolActivity }`.
- Resolve the skill: `skillIdFromCapabilityArgs(activity.args)`, then look up
  the display name via `useSkillsQuery()` **wrapped in a graceful fallback**:
  the conversations route must not suspend or error on the skills query. Use
  a non-suspense lookup — e.g. `useQuery(skillsQueryOptions())` with
  `enabled` and render the raw fallback until data arrives. If plan 019's api
  module only exports suspense hooks, import `skillsQueryOptions` and call
  `useQuery` here directly.
- Render: a sparkles icon, the label
  `Activated skill: <human_name ?? name ?? shortened-id>`, and a subtle status
  treatment — pending result (`status === "running"`) shows the loading style
  `ToolCallRow` uses; completed shows a done check. Do **not** render the
  result content (the loaded instructions are prompt internals).
- If `skillIdFromCapabilityArgs` returns `null` (non-skill capability), the
  caller falls back to `ToolCallRow` (see Step 4) — this component may assume
  a skill id.

**Verify**: `pnpm typecheck && pnpm lint` → exit 0.

### Step 4: Route activities to the right row

In `message-row.tsx`, where `toolActivities` map to `ToolCallRow`, branch:

```ts
const isSkillActivation =
  activity.toolKind === "capability-load" ||
  activity.name === LOAD_CAPABILITY_TOOL_NAME
```

- `isSkillActivation && skillIdFromCapabilityArgs(activity.args)` →
  `SkillActivationRow`.
- `isSkillActivation` with a null skill id → keep `ToolCallRow` (unknown
  capability kind; honest fallback).
- Suppress the duplicate: an activation produces both a call and a result
  activity with the same id; render the **call** activity only (its status is
  upgraded to `completed` by the parser once the result exists) and skip
  result activities whose `toolKind === "capability-load"`. Check how the
  existing renderer deduplicates call/result pairs for regular tools first —
  mirror whatever it does (if it renders both today, only change behavior for
  capability-load activities).

In `message-list.tsx`, read `buildLiveToolActivities` and make the live
mapping carry the same information: live `ToolCallState` has no `tool_kind`,
so set `toolKind: "capability-load"` when
`name === LOAD_CAPABILITY_TOOL_NAME` while building the live activities. No
reducer change.

**Verify**: `pnpm typecheck && pnpm lint` → exit 0.

### Step 5: Full gate + manual smoke

**Verify**: `pnpm check` → exit 0. Manual smoke with the full stack running
(backend with plans 016–018 landed, a skill assigned to an agent):

1. Ask the agent something that triggers the skill → during the run a
   "Activated skill: <name>" row appears with a loading state, then completes.
2. Reload the conversation → the activation row renders identically from
   persisted history (this exercises the `message-parts.ts` path).
3. An agent turn using a regular tool still renders the normal `ToolCallRow`,
   including `read_skill_document` calls.

## Test plan

No frontend unit-test runner exists; correctness rests on `pnpm check` plus
the manual smoke above. Keep `skill-activation.ts` pure and small so it is
trivially reviewable (id parsing is the only logic that could silently break —
double-check the `skill:` prefix constant against
`apps/api/services/agents/runtime/skills.py` after plan 018 lands).

## Done criteria

ALL must hold (run from `apps/web`):

- [ ] `pnpm check` exits 0
- [ ] `grep -rn "capability-load" src/features/conversations/` matches in
      `message-parts.ts`, `message-list.tsx` (or the row component), per Steps 2–4
- [ ] `grep -n "skill.activated" src/` returns no matches (no new SSE event
      was introduced)
- [ ] `git diff --name-only` shows only in-scope files (leave any unrelated
      pre-existing working-tree changes untouched)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 018 has not landed (no `services/agents/runtime/skills.py` in the API).
- The persisted parts do not contain a `tool_kind` field when you inspect a
  real conversation row after an activation (serializer behavior differs from
  the probe) — report what the parts actually contain.
- Rendering the activation row requires changing `stream/reducer.ts` or
  `stream/protocol.ts` after all — report why before touching them.
- The capability id prefix in the backend is not `skill:` (drift against plan
  018).
- `pnpm check` fails on files you did not touch.

## Maintenance notes

- If a richer activation payload is ever needed (e.g. skill description in the
  row without a lookup), the right mechanism is a **new SSE event added to
  `STREAM_EVENT_NAMES` first (client tolerates it), deployed, then emitted by
  the backend** — a two-step rollout. The parser throwing on unknown events is
  the constraint that forces this order; alternatively make `parseSseFrame`
  skip unknown events (a one-line forward-compatibility change worth
  considering in any future protocol work).
- When plan 013 (history trimming) lands, capability-load pairs must survive
  trimming or reloaded conversations will lose their activation rows *and*
  the agent will lose its loaded skills — the runtime note in plan 018 covers
  the authoritative constraint.
- Reviewers should scrutinize: the null-skill-id fallback (non-skill
  capabilities must not render as skills) and that the loaded-instructions
  content never renders in the UI.
