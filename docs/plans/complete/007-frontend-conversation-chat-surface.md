# Plan 007: Add Conversation Chat Routes And Refresh Heal Loop

> **Executor instructions**: Follow this plan step by step. This slice builds the
> usable conversation surface on top of the transport from Plan 006. Do not build
> full agent management forms, schedule CRUD screens, or approval decision
> controls in this plan. When done, update the status row for this plan in
> `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat fdf7220..HEAD -- apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/routes apps/web/src/components apps/web/src/features/conversations apps/web/src/features/agents apps/web/src/lib/api apps/api/services/conversations/schemas.py apps/api/services/agents/runtime/events.py docs/plans`
>
> If any in-scope file changed since this plan was written, compare the "Current
> State" excerpts below against the live code before proceeding. If Plan 006 has
> not landed or its exported stream API differs from this plan's assumptions,
> stop and refresh this plan.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: Plan 006 frontend agent stream transport
- **Category**: feature
- **Planned at**: commit `fdf7220`, 2026-07-01
- **Status**: TODO

## Why This Matters

The backend can now run interactive agent turns, persist the transcript even
after disconnect, and expose an active-run status endpoint. The web app still
has no conversation route, no composer, and no refresh recovery behavior. Users
cannot actually talk to the agents through the product.

This plan adds the first real chat surface: conversation list/detail routes,
message rendering from persisted Pydantic AI rows, a composer that streams over
the custom SSE protocol, and the documented refresh heal loop. Approval decisions
are displayed as pending work but are submitted in Plan 008.

## Current State

Current router:

```tsx
// apps/web/src/app/router.tsx:70
const homeRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: HomeRoute,
})
...
appRoute.addChildren([
  homeRoute,
  workspacesRoute,
  workspaceSettingsRoute,
  profileRoute,
  oauthLinkCallbackRoute,
])
```

Current navigation:

```ts
// apps/web/src/config/navigation.ts:10
{
  label: "Agents",
  to: null,
  icon: BlocksIcon,
  disabled: true,
}
```

Current home placeholders:

```tsx
// apps/web/src/routes/home.tsx:88
<CardDescription>No agents are connected yet.</CardDescription>
...
<CardDescription>Scheduled runs will appear here.</CardDescription>
...
<CardDescription>Approval requests will appear here.</CardDescription>
```

Relevant backend read contracts:

- `ConversationRead` includes `id`, `title`, `source`, `last_message_at`,
  `active_agent_id`, and `agent_slug`.
- `ConversationMessageRead` includes `role`, `parts`, `metadata`, `tool_name`,
  `sequence`, and `client_message_id`.
- `ConversationActiveRunResponse` returns `active_run: AgentRunRead | null`.

The accepted streaming plan says refresh recovery is DB-heal, not live token
resume:

- on mount, load persisted messages and active-run status;
- if an active run exists, show working state and poll active run + messages with
  backoff until terminal;
- do not try to reattach to the old SSE stream.

## Commands You Will Need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Typecheck | `cd apps/web && pnpm typecheck` | exit 0, no TS errors |
| Lint | `cd apps/web && pnpm lint` | exit 0, no warnings |
| Build | `cd apps/web && pnpm build` | exit 0 |

There is currently no frontend unit-test script in `apps/web/package.json`.
Use typecheck/lint/build plus manual local verification.

## Scope

**In scope**:

- `apps/web/src/app/router.tsx`
- `apps/web/src/config/navigation.ts`
- New route files under `apps/web/src/features/conversations/routes/`
- New chat components under `apps/web/src/features/conversations/components/`
- New message parsing helpers under `apps/web/src/features/conversations/`
- Query/stream integration using the Plan 006 API modules
- Small updates to `apps/web/src/routes/home.tsx` to link to conversations

**Out of scope**:

- Full agent create/edit/delete UI.
- Schedule create/edit/delete UI.
- Approval approve/deny forms and resume submission.
- Backend API changes.
- Live stream resume after refresh.
- Rich markdown rendering, file attachments, images, or multimodal input.
- Agent delegation transcript UI.

## Git Workflow

- Suggested branch: `advisor/007-conversation-chat-surface`.
- Commit style should match recent history, for example:
  `Web - Add Conversation Chat Surface`.
- Do not push or open a PR unless the operator asks.

## Steps

### Step 1: Add Conversation Routes

Edit `apps/web/src/app/router.tsx` and register authenticated routes:

- `/conversations`
- `/conversations/$conversationId`

Create route components:

```text
apps/web/src/features/conversations/routes/conversations-route.tsx
apps/web/src/features/conversations/routes/conversation-route.tsx
```

`/conversations` should show a dense work-focused layout with:

- a conversation list ordered by recent activity;
- an empty state when no conversations exist;
- a "New conversation" action that opens a compact dialog or side panel;
- an agent selector for starting the first turn, using `listAgents` from Plan
  006. If no active agents exist, show a disabled composer state. Do not link to
  an Agents screen: Plan 008 runs after this plan, so the `/agents` route does
  not exist yet at execution time. Plan 008 adds that link when it lands.

`/conversations/$conversationId` should show:

- the conversation title and primary agent slug/id;
- the persisted message list;
- live stream state when a turn is running;
- a composer for sending the next prompt to the conversation's active agent.

Use TanStack Router patterns already present in `router.tsx`. Keep routes under
the authenticated `appRoute`.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 2: Add Navigation And Home Links

Edit `apps/web/src/config/navigation.ts`.

Add a first-class navigation item for conversations using an existing lucide icon
such as `MessagesSquareIcon`. Keep the current disabled Agents item untouched
unless Plan 008 has already landed.

Edit `apps/web/src/routes/home.tsx` so the placeholder agent/schedule/approval
cards do not imply those surfaces work yet. Add a clear action to open
`/conversations`. Do not turn the home route into a marketing page.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 3: Render Persisted Pydantic AI Messages

Create helpers, for example:

```text
apps/web/src/features/conversations/message-parts.ts
apps/web/src/features/conversations/components/message-list.tsx
apps/web/src/features/conversations/components/message-row.tsx
apps/web/src/features/conversations/components/tool-call-row.tsx
```

Persisted message rows are Pydantic AI serialized messages, not simple chat text.
Implement a defensive parser that extracts:

- user text from request parts with `part_kind: "user-prompt"`;
- assistant text from response parts with text content;
- tool calls/results from parts that include `tool_name`, `tool_call_id`, or
  `part_kind` values such as `"tool-call"` and `"tool-return"`;
- fallback labels for unknown or unsupported parts without dumping huge JSON into
  the main conversation.

Keep the UI compact and operational:

- user messages aligned distinctly from assistant messages;
- assistant messages readable as normal paragraphs;
- tool activity in small bordered rows/cards with name, status, and optional
  collapsed JSON args/result;
- pending approvals displayed as requiring action but without approve/deny
  controls in this plan.

Do not add markdown or syntax highlighting unless already present in the repo.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 4: Wire Composer Streaming

Create a composer component:

```text
apps/web/src/features/conversations/components/conversation-composer.tsx
```

Use the Plan 006 `useAgentStream` hook:

- Starting a new conversation calls the create-conversation stream endpoint with
  `agent_id`, `user_prompt`, and a generated `client_message_id`.
- Sending a follow-up calls `POST /conversations/{id}/turns`.
- Disable the composer while local stream state is `pending`, `running`, or
  `awaiting_approval`.
- On stream finish, invalidate/refetch conversation list and message list queries.
- If a stream reports `conversation.created`, navigate to the created
  conversation detail route once the conversation id is known.

Generate `client_message_id` in the browser with `crypto.randomUUID()` where
available. Keep it stable per submission attempt so a retry can detect duplicate
messages.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 5: Implement Refresh Heal Loop

In the conversation detail route, implement DB-heal recovery:

- Query messages with TanStack Query.
- Query `/conversations/{id}/active-run`.
- If `active_run` exists, show a working indicator tied to
  `active_run.status`.
- Poll messages and active-run with backoff `[250, 750, 1500]` ms while a run is
  active.
- Stop polling when `active_run` becomes `null` or reports a terminal status.
- Do not attempt to reconnect to a previous stream.

The user should be able to refresh mid-run and see:

- persisted messages so far;
- a working state while the detached backend task continues;
- the final persisted reply after polling observes completion.

**Verify**:
`cd apps/web && pnpm typecheck` -> exit 0.

### Step 6: Run The Frontend Gate

Run:

```bash
cd apps/web
pnpm typecheck
pnpm lint
pnpm build
```

Expected result: all commands exit 0.

## Test Plan

No frontend test runner exists yet. Verification is:

- typecheck, lint, and production build;
- manual local run with API credentials or `TestModel`-backed backend fixtures if
  available;
- browser refresh during a running turn to confirm the route uses DB-heal rather
  than live stream resume.

Manual cases to exercise:

- no conversations;
- no active agents;
- create first conversation;
- send follow-up prompt;
- refresh while a turn is running;
- backend returns `awaiting_approval`;
- backend returns stream `error`;
- duplicate `client_message_id` conflict from a retry.

## Done Criteria

- [ ] `/conversations` and `/conversations/$conversationId` routes exist under
      the authenticated app route.
- [ ] Navigation exposes conversations.
- [ ] Persisted `ConversationMessageRead.parts` rows render into readable
      user/assistant/tool UI.
- [ ] Composer sends create and follow-up streamed turns through the Plan 006
      transport.
- [ ] Refresh heal loop polls active run + persisted messages until terminal.
- [ ] Approval-required state is visible but not actionable yet.
- [ ] `cd apps/web && pnpm typecheck` exits 0.
- [ ] `cd apps/web && pnpm lint` exits 0.
- [ ] `cd apps/web && pnpm build` exits 0.
- [ ] No backend source files are modified.
- [ ] `docs/plans/000_README.md` status row updated.

## STOP Conditions

Stop and report back if:

- Plan 006 has not landed or does not expose a stream hook/reducer.
- Backend persisted message shape cannot be parsed without changing API schemas.
- The route needs live stream resume to satisfy product expectations. That
  conflicts with the accepted DB-heal architecture.
- You need to loosen CORS, cookies, CSRF, or workspace headers to make streaming
  work.
- The frontend build fails twice after reasonable fixes.

## Maintenance Notes

This plan intentionally keeps approval decisions out of the chat route. Plan 008
should add approve/deny controls by reusing the pending approval state rendered
here and the `resumeRun` transport from Plan 006.

Future generated stream types should replace `message-parts.ts` assumptions where
possible, but the UI should still handle unknown Pydantic AI parts defensively.
