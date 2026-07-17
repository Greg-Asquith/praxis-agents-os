# Plan 032: Resilient conversation streams across navigation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Written**: 2026-07-17, anchors verified against `89ac993`. Unlike most
  of this series this is a correctness plan, not a visual one (precedent:
  plan 014). It fixes a diagnosed production bug and hardens the stream
  lifecycle around it.
- **Priority**: P1 — the bug soft-locks conversations. Approval runs are
  unrecoverable without a page refresh.
- **Effort**: M
- **Risk**: MEDIUM — touches router-level pending behavior (global),
  route loading for the conversation area, and the stream state machine.
  Each layer is independently small and independently shippable; the test
  surface for the reducer change must grow with it.
- **Depends on**: nothing in the series. Touches
  `src/app/router.tsx`, `src/routes/`, and
  `src/features/conversations/` (stream + route files) — file-disjoint
  from any outstanding visual plan.

## The bug (diagnosed 2026-07-17)

Starting a conversation from `/conversations/new` sometimes freezes the
page after the redirect to `/conversations/{id}`: nothing streams, the
composer stays disabled with "The current turn is still running", and —
worst case — a run that suspends for tool approval never shows its
approval card, so the user cannot act at all. A page refresh always
recovers, because the server-side run was never affected.

The verified failure chain:

1. Sending on `/new` opens the SSE `POST /conversations/` inside
   `useAgentStream.runStream`. The `conversation.created` event triggers
   `navigate()` to the detail route
   (`conversation-runtime-provider.tsx:41-50`).
2. TanStack Router propagates match state through
   `@tanstack/react-store`'s `useStore`, which is built on
   `useSyncExternalStore`. External-store updates de-opt React
   transitions to **synchronous renders**, so if the incoming screen
   suspends, React cannot keep showing the old one.
3. The incoming screen *can* suspend post-commit: `ConversationDetail`
   calls `useSuspenseQueries([agentQueryOptions(…), …])`
   (`conversation-route.tsx:138-140`). Conversation, messages, and
   active-run are pre-seeded by `seedStreamQueryCache`, and the router
   awaits lazy route chunks before committing, but the **agent detail
   query is cold** on the first conversation with that agent since page
   load (or after query GC).
4. No route in `src/app/router.tsx` sets `pendingComponent` or
   `wrapInSuspense`, and the router sets no `defaultPendingComponent`,
   so every match renders in a `SafeFragment` (verified in
   `@tanstack/react-router` `Match.js`, v1.171.13). The only real
   Suspense boundary is the top-level one in `Matches()` — **above**
   `ConversationRuntimeProvider`.
5. The suspension therefore reverts the *root* boundary to its
   fallback. React 18+ cleans up effects in a tree hidden behind a
   Suspense fallback, which runs `useAgentStream`'s unmount cleanup
   (`use-agent-stream.ts:58-63`) — **aborting the live SSE fetch**.
6. `runStream` swallows the `AbortError` (`use-agent-stream.ts:104-107`)
   without dispatching anything. Neither `finishClosedStream` nor
   `resetSettledRun` applies, so the reducer is left permanently at
   `status: "running"`, `done: false`, `isStreaming: true`, with frozen
   message drafts. When the agent query resolves the tree un-hides, but
   nothing reconnects.
7. The stuck state then shadows reality: `streamActiveRun` (built from
   stream state, **not gated on the stream belonging to this
   conversation**) takes precedence over the polled active-run query
   (`conversation-route.tsx:89-98,137`), so `shouldLoadApprovalState`
   never sees `awaiting_approval`, the approval card never loads, and
   the composer never unlocks.

Why it is intermittent: the tree only hides if something actually
suspends during the commit. When the agent detail is already cached the
swap is instant and the stream survives — which is why the failure
correlates with "the agent started replying before the switch finished"
(the slow switches are the suspended ones).

The same class of failure exists beyond the `/new` flow: opening any
conversation from the sidebar while a stream is live in this workspace
suspends on cold messages/active-run/agent queries and kills that
stream the same way.

## Current state (verified 2026-07-17 at `89ac993`)

- `src/app/router.tsx:316-322` — `createAppRouter` sets only
  `defaultPreload: "intent"`; no `defaultPendingComponent`. Routes set
  no `pendingComponent`/`wrapInSuspense`/loaders in the conversation
  area (`:131-156`).
- `src/routes/pending.tsx` — `PendingRoute` (root fallback) renders the
  full-app skeleton via `AppLayoutFallback`; it is designed to replace
  the whole screen, not an outlet region.
- `use-agent-stream.ts:58-63` — unmount effect aborts and nulls
  `abortControllerRef`; `:104-110` — `AbortError` returns silently,
  every other error dispatches `fail`; `:111-139` — `finally` block
  invalidates queries and conditionally dispatches `resetSettledRun`.
- `stream/reducer.ts` — actions: `start`, `reset`, `resetSettledRun`,
  `finishClosedStream`, `event`, `fail`. Nothing represents a
  client-side abort; `resetSettledRun` requires `state.done`.
- `conversation-route.tsx:88-98` — `streamActiveRun` computed from raw
  stream state; `:96-98` gates `initialActiveRun` on
  `isLiveStreamConversation` but `:137`
  (`streamActiveRun ?? activeRunQuery.data.active_run`) and the
  messages `refetchInterval` closure (`:115-121`) do not.
- Healing that already works when stream state is *not* stuck: 1s
  heal-polling while a run is `pending`/`running`
  (`conversation-heal-polling.ts`), approval recovery via
  `useAgentRunApprovalStateQuery` when the active run reports
  `awaiting_approval`, and the reconcile effect in
  `use-conversation-run-state.ts:103-140`.
- Test tooling: vitest in a node environment, pure-function tests only
  (no jsdom/testing-library). Stream tests live at
  `tests/features/conversations/stream/`.

## Design decisions (this plan)

- **Defense in depth, three independent layers.** (1) No suspension may
  climb above `ConversationRuntimeProvider` — every route match gets a
  local Suspense boundary. (2) The conversation routes stop suspending
  post-commit at all — their data moves into route loaders, which run
  before commit while the old screen stays up. (3) The stream state
  machine becomes abort-safe — an aborted stream finalizes
  deterministically and the existing polling/approval recovery takes
  over, so no future abort path (known or unknown) can soft-lock the UI
  again. Layer 3 alone fixes the hard lock; layers 1–2 preserve the
  live experience.
- **No stream reattach in this plan.** Rejoining a live run's event
  stream after a disconnect is the durable-replay vertical
  (`docs/plans/060-durable-stream-replay.md`) and needs backend work.
  Degrading to the existing 1s heal-polling is the honest incremental
  behavior until then. Do not build a reattach endpoint here.
- **Abort-on-unmount stays.** The provider is keyed by workspace id;
  tearing down the stream on workspace switch is a workspace-isolation
  property, not an accident. We make aborts *safe*, we do not remove
  them. Same for navigating out of the conversation area (the runtime
  layout unmounts): the live stream ends by design, the run continues
  server-side, and polling heals the transcript on return.
- **Loaders are additive, not a data-layer migration.** They call
  `queryClient.ensureQueryData` with the existing `queryOptions`
  factories, so cached data (including the stream-seeded cache) makes
  them instant and TanStack Query remains the single data layer. This
  also upgrades `defaultPreload: "intent"` for free — hovering a
  sidebar conversation now prefetches everything it renders.
- **Route-level pending UI is a lightweight, outlet-local fallback** —
  not `AppLayoutFallback`, which paints a full app frame and would nest
  a fake sidebar inside the real one.

## Steps

### 1. Reducer: represent a client-side abort

`src/features/conversations/stream/reducer.ts`:

- Add action `{ type: "abort" }`. Reduction: if `status` is `"idle"` or
  `state.done` is already true, return `state` unchanged; otherwise
  return `{ ...state, done: true }`. Keep the current `status` — the
  active-run query is the authority on what the run is actually doing
  from this point, and `done: true` is what releases every derived
  gate: `isStreaming` (composer), `streamActiveRunFromState` (returns
  `undefined` when `done`, so the polled active-run wins and the
  approval card can load).

Tests (`tests/features/conversations/stream/reducer.test.ts`):

- abort mid-run (after `message.delta`/`tool.call` events) → `done`
  true, drafts retained, status unchanged.
- abort when idle and abort after `done` → state returned unchanged.
- events arriving after abort are ignored (existing `state.done` gate —
  assert it explicitly for this path).

### 2. `useAgentStream`: finalize aborted streams

`src/features/conversations/stream/use-agent-stream.ts`, in
`runStream`'s `catch`:

```ts
if (isAbortError(error)) {
  if (abortControllerRef.current === null || abortControllerRef.current === abortController) {
    dispatch({ type: "abort" })
  }
  return
}
```

The guard matters: when the abort came from the awaiting-approval
re-entry (`:67-74`), a *new* stream already owns the ref and has
dispatched `start` — the superseded stream must not touch state. When
the abort came from effect cleanup (Suspense hide or real unmount) the
ref is already `null` — dispatch: on a hidden-then-revealed tree this
is exactly the fix, and on a truly unmounted provider it is a no-op.

The `finally` block already runs on this path and already invalidates
the conversation queries — leave it as is. Do not add reconnect logic.

Verification: `pnpm test` (reducer suite), then trace the abort path
manually — temporarily call `stream.abort()` from the console flow in
step 6's QA and confirm the composer unlocks and polling takes over.

### 3. Gate the stream-derived active run by conversation

`src/features/conversations/routes/conversation-route.tsx`:

- Compute `streamActiveRun` only when the stream belongs to this
  conversation: `isLiveStreamConversation ? streamActiveRunFromState(…) : undefined`
  (the `:89-94` computation). Everything downstream — line `:137`'s
  `activeRun`, the messages `refetchInterval` closure, and
  `initialActiveRun` — then inherits the gate.

This closes the shadowing amplifier in general: a stuck or foreign
stream can never mask another conversation's real run state again.

Add a note-sized test only if a pure helper falls out naturally;
otherwise the reducer tests plus manual QA cover this (the file is a
route component, and we do not add jsdom for this plan).

### 4. Local Suspense boundaries for every route match

- Add `src/routes/route-pending.tsx`: `RoutePendingFallback`, a minimal
  outlet-local fallback — a centered `Skeleton` block or spinner that
  fills its container (`flex h-full min-h-0 items-center justify-center`),
  tokens only, no text. It must look sane inside the app canvas *and*
  full-screen (it becomes the fallback for layout-level matches too).
- In `createAppRouter` (`src/app/router.tsx:316-322`) set
  `defaultPendingComponent: RoutePendingFallback`.
- Keep `pendingComponent: PendingRoute` on the root route — it remains
  the fallback for the top-level boundary during initial load.

Why this works (verified against `Match.js` in the installed
`@tanstack/react-router@1.171.13`): a non-root match wraps its component
in `React.Suspense` when it resolves a pending component; with a
`defaultPendingComponent` every match resolves one. A suspension inside
`ConversationRoute` is now caught at the conversation match — *below*
`ConversationRuntimeProvider` — and can never hide the provider again.

Known side effect to accept: routes whose *loaders* exceed the router's
pending thresholds will also show this fallback. That is strictly
better than the current behavior (blank full-app skeleton).

Verification: with the API up, hard-reload on `/agents`, then click
into a conversation — the pending flash (if any) must render inside the
content canvas, never replace the sidebar/app frame.

### 5. Loaders: the conversation routes stop suspending post-commit

`src/app/router.tsx` (loaders live with the route definitions; they
only compose existing `queryOptions` factories):

- `conversationRoute`:

  ```ts
  loader: async ({ context, params }) => {
    const conversation = await context.queryClient.ensureQueryData(
      conversationQueryOptions(params.conversationId)
    )
    await Promise.all([
      context.queryClient.ensureQueryData(conversationMessagesQueryOptions(params.conversationId)),
      context.queryClient.ensureQueryData(conversationActiveRunQueryOptions(params.conversationId)),
      context.queryClient.ensureQueryData(modelCatalogQueryOptions()),
      ...(conversation.active_agent_id
        ? [context.queryClient.ensureQueryData(agentQueryOptions(conversation.active_agent_id))]
        : []),
    ])
  }
  ```

  In the live `/new` flow every one of these except the agent is
  already in the cache (stream-seeded), so the redirect stays instant;
  the agent fetch happens pre-commit with the old screen visible.

- `newConversationRoute`: `ensureQueryData` for the agents list and
  model catalog options used by `NewConversationRoute` — cold entry to
  `/new` during a live run is the same bug class.

Rules: `ensureQueryData` only — never `fetchQuery` (must not refetch
data the stream just seeded); no data returned from the loader (the
components keep reading through their existing hooks); no
`beforeLoad` changes.

Verification: `pnpm check`; then in the browser confirm (network tab)
that opening a conversation issues the agent fetch *before* the URL
content swaps, and that the swap itself no longer flashes any fallback
once caches are warm.

### 6. Manual QA — reproduce the original bug, confirm it is dead

Needs `make dev` and an agent whose tools require approval.

1. Hard-reload the app (cold query cache). From `/conversations/new`,
   send a prompt to an approval-tool agent.
2. **Before the fix** this intermittently froze: full-app skeleton
   flash during the redirect, `POST /conversations/` shown as
   *cancelled* in the network tab, composer stuck on "The current turn
   is still running", no approval card, and (dev) a React console
   warning about a component suspending "while responding to
   synchronous input".
3. **After the fix**, in the same cold-cache scenario: the redirect
   keeps the app frame; the SSE request stays open through the
   navigation; text streams live; the approval card appears; approving
   resumes and streams live; the composer re-enables at the end.
4. Regression sweep: send a plain text turn and navigate to another
   conversation mid-stream, then back — no stuck spinner, transcript
   heals; switch workspace mid-stream — stream ends, no console
   errors, the new workspace is unaffected; stop button still cancels.
5. Run both themes through the new `RoutePendingFallback` (force it by
   throttling the network and hard-reloading into a conversation URL).

## STOP conditions

- If `Match.js` in the installed router version does not wrap matches
  in `Suspense` when `defaultPendingComponent` is set (re-verify after
  any dependency bump), stop — the containment layer needs
  `wrapInSuspense: true` per route instead, and that choice should be
  made deliberately.
- If the loader on `conversationRoute` measurably delays opening
  *cached* conversations (it must resolve synchronously from cache),
  stop and investigate before shipping.
- If any test in the existing stream/reducer suites needs its
  *expectations* changed (rather than new cases added), stop — the
  reducer changes here are strictly additive.
- If fixing this appears to require a backend change, stop — the wire
  protocol and endpoints are out of scope; reattach belongs to plan
  060.

## Considered and rejected (do not re-propose)

- **Reattach/replay of live run streams** — right fix long-term,
  belongs to plan 060 (backend event persistence + replay endpoint),
  not a UI-series patch.
- **Moving the stream out of React entirely** (module-level stream
  manager) — removes the effect-cleanup abort by construction, but
  re-implements workspace-scoped lifecycle and cache-write fencing that
  the keyed provider gives us for free. Not warranted once aborts are
  safe.
- **Hoisting `ConversationRuntimeProvider` to the app layout** so
  streams survive leaving the conversation area — widens the surface
  where a suspension sits above the provider and changes
  workspace-isolation review scope; separate proposal if ever wanted.
- **Suppressing the abort by skipping cleanup when "hidden"** — React
  gives no reliable hidden-vs-unmounted signal in cleanup; guessing
  risks leaking cross-workspace streams. Rejected on security grounds.

## Final verification

- `cd apps/web && pnpm check` — typecheck, eslint (zero warnings),
  vitest, prettier, knip, depcruise, build all green.
- Manual QA script in step 6 passes in full, both themes.
- Update the status row in `docs/plans/frontend-ui/README.md`.
