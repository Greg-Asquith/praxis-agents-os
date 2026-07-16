# Plan 014: Remove unneeded useEffects

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Completed**: 2026-07-16
- **Written**: 2026-07-16 (anchors verified at `b011664`)
- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM — the OAuth code exchange and the run heal loop are
  behavioral, not cosmetic. Every step preserves observable behavior;
  the wins are structural (less effect machinery, fewer re-render
  cascades, deleted dedup scaffolding).
- **Depends on**: nothing structurally. Do not run concurrently with
  012/013 (013 sweeps labels across the same route files). This is a
  code-health plan, not a visual one — it rides in this series because
  it came out of the same review pass.

## Goal

Maintainer directive (2026-07-16): find every `useEffect` in `apps/web`
and remove the ones that better code makes unnecessary — less/no
`useEffect` is the target.

The audit found **13 call sites in 12 files**. Eight can go; five are
legitimate (external-system sync or unmount cleanup — exactly what
effects are for) and stay, with their justification recorded here so
nobody re-audits them from scratch.

The governing rule (React's own "you might not need an effect", applied
to this codebase): effects are only for synchronizing with systems
outside React — network connections, the DOM, timers needing unmount
cleanup. Everything else — data fetching on navigation, derived state,
persisting user choices — belongs in route loaders, render-time
derivation, event handlers, or the query layer.

## The audit (verified 2026-07-16 at `b011664`)

**REMOVE — route-entry actions become route loaders (step 1):**

| Site | What it does today |
|------|--------------------|
| `features/auth/routes/oauth-login-callback-route.tsx:68` | Fires the OAuth login code exchange once on mount |
| `features/auth/routes/oauth-link-callback-route.tsx:66` | Fires the OAuth account-link exchange once on mount |
| `features/integrations/routes/oauth-callback-route.tsx:52` | Fires the integration OAuth exchange once on mount |
| `features/workspaces/routes/accept-invitation-route.tsx:55` | Accepts the invitation token once on mount |

All four are the same shape: an on-mount effect guarded by a
`startedRef` **and** a module-level promise `Map` (dedup against
StrictMode double-fire), feeding `useState` for error/success. None of
that is reactive — it is "when this route is entered, do X", which is
what TanStack Router loaders are for. Loaders run once per navigation,
so the `startedRef` + effect + state plumbing dissolves.

**REMOVE — plain restructures (steps 2–4):**

| Site | What it does today | Replacement |
|------|--------------------|-------------|
| `features/workspaces/components/active-workspace-provider.tsx:57` | Persists the active slug to localStorage whenever `activeWorkspace` changes | Write in the `setWorkspaceBySlug` event handler |
| `features/conversations/stream/use-agent-stream.ts:53` | Mirrors reducer state into `stateRef` every render | Track state in the dispatch path (the reducer is pure) |
| `features/conversations/hooks/use-conversation-heal-loop.ts:17` | Hand-rolled polling loop (250/750/1500ms, error cap) while a run status is polling | TanStack Query `refetchInterval`; delete the hook |
| `features/conversations/routes/conversation-route.tsx:125` | Clears persisted pending messages once the server copy appears in `messagesQuery.data` | Derive the visible list during render |

**KEEP — legitimate effects (do not re-propose removing; step 5
records why in code where a comment is warranted):**

| Site | Why it stays |
|------|--------------|
| `stream/use-agent-stream.ts:57` | Aborts the SSE connection on unmount — external-connection cleanup, the canonical effect |
| `hooks/use-conversation-auto-scroll.ts:28` | Scrolls the DOM after React commits new content — there is no event for "commit finished"; DOM sync is what effects are for |
| `hooks/use-conversation-run-state.ts:102` | Reconciles the shared stream reducer with server truth across approval/settle races. The reset would otherwise need to fire from every settle path; approvals depend on it. Risk outweighs the win |
| `hooks/use-conversation-read-receipt.ts:17` | Syncs "viewed" to the server when data says unread — condition is data-driven, no user event exists |
| `hooks/use-clipboard-copy.ts:30` | Clears the copied-state timeout on unmount — timer cleanup |

## Steps

### 1. Convert the four route-entry effects to loaders

Routes are code-defined in `src/app/router.tsx` (the callback routes sit
at lines 58, 98, 250, 261; `beforeLoad` auth gating already exists —
loaders slot in beside it). For each of the four routes:

- Add a `loader` that performs the action and **returns** the outcome as
  data — `{ error }` / `{ twoFactorPending }` (login) / the
  `WorkspaceInvitationAcceptResponse` (invitation) — rather than
  throwing, so the component renders the same error/pending/success UI
  from `useLoaderData` instead of local state.
- Loaders cannot use hooks: call the underlying API functions the
  mutation hooks wrap (in each feature's `api/` module) directly, and
  replicate any cache work the mutation hook did via the `queryClient`
  (confirm it is reachable from router context — `beforeLoad` already
  consumes `context`; extend the context if it only carries auth).
- **Keep the module-level promise `Map`s** — they move from "StrictMode
  guard" to "loader re-run guard" (OAuth codes and invitation tokens are
  single-use; a stale-loader re-run or preload must not re-fire the
  exchange). Delete the `startedRef`, the effect, and the
  error/success `useState` in each component. Also set the callback
  routes' loader `staleTime` so revisits don't re-run (executor: check
  the current TanStack Router option name).
- The success redirects currently use `window.location.replace(...)` —
  a deliberate full document reload that resets auth/cache state.
  Preserve full-reload semantics from the loader (TanStack `redirect`
  has a document-reload option; verify the installed version's API, or
  call `window.location.replace` in the loader and return a
  never-resolving promise — pick whichever the installed router
  supports cleanly, do not downgrade to an SPA navigate).
- `accept-invitation-route.tsx` reads `token` from search params —
  loaders receive validated search; the missing-token error becomes
  loader data too. `getActiveInvitationState` and the
  `AcceptInvitationState` union collapse to loader-data reads.

### 2. localStorage write moves to the event handler

`active-workspace-provider.tsx`: delete the `useEffect` at line 57 and
call `storeSlug(slug)` inside `setWorkspaceBySlug` instead. The effect
also persisted *auto-resolved* fallbacks, but `chooseWorkspace` derives
the identical fallback from the same inputs on next load — persisting it
was redundant. Only the explicit user switch is worth storing. (The
render-time `setActiveWorkspaceSlug` call at line 55 is a settled
decision — its comment explains why; leave it alone.)

### 3. Replace the heal loop with query-level polling

Delete `use-conversation-heal-loop.ts` and its call in
`conversation-route.tsx:116`. In `ConversationDetail`, add
`refetchInterval` to the two suspense queries the loop was manually
refetching (`conversationActiveRunQueryOptions`,
`conversationMessagesQueryOptions`): a function returning an interval
while `isRunStatusPolling(activeRun?.status)` and `false` otherwise.
For the messages query, drive the condition from the active-run data it
can see via the shared `activeRun` value (executor: `refetchInterval`
callbacks receive the query — thread the run status in whichever way
stays type-clean). Behavior notes:

- The hand-rolled 250/750/1500ms escalation flattens to a fixed
  interval (use 1000ms). That widens the fastest poll by 750ms and
  narrows the steady state by 500ms — acceptable.
- The 3-consecutive-errors cap is subsumed by the query layer's own
  retry/error behavior; polling a failing endpoint stops when the
  status condition can no longer be read as polling. Verify a killed
  API does not leave an infinite fast poll (throttle the interval on
  error state if needed).

### 4. Derive pending-message visibility instead of clearing in an effect

`conversation-route.tsx:125` clears provider state
(`conversation-runtime-provider.tsx:45`) once
`persistedClientMessageIds(messages)` contains a pending message's
client id — i.e. it exists to make the optimistic copy vanish exactly
when the server copy renders, flicker-free. The same handoff is a pure
derivation from the same data source:

- In `ConversationDetail`, compute
  `visiblePendingUserMessages = pendingUserMessages.filter((m) => !persistedIds.has(m.clientMessageId))`
  from `messagesQuery.data.messages` during render, and pass that to
  `MessageList` and the auto-scroll `pendingMessageCount`. Delete the
  effect.
- The provider's stored array still needs pruning (it is per-workspace
  session state and must not grow unbounded): prune at the event sites
  that already know the outcome — the composer's post-send path and
  `removePendingUserMessage` error path (read the composer's send
  handler; `clearPersistedPendingMessages` likely becomes callable from
  there or shrinks to that role). If no clean event site exists for the
  success case, pruning on next `addPendingUserMessage` is acceptable —
  visibility is already correct via the derivation.

### 5. Annotate the keepers

For the five KEEP sites, ensure each effect reads as obviously
intentional. Most already do; add a terse single-line comment only
where the justification is non-obvious (`use-conversation-run-state.ts`
is the one that likely warrants it). No behavior changes.

### 6. Verify

- `grep -rn "useEffect" apps/web/src` returns exactly the five KEEP
  sites.
- `cd apps/web && pnpm check` passes.
- Manual QA against `pnpm dev`:
  - OAuth login (full round trip), OAuth account link from profile,
    integration connect, and invitation accept all still complete once,
    render their error states on a bad/missing token, and redirect with
    a full document load on success.
  - Workspace switching persists across a reload; a fresh profile still
    resolves default workspace → first workspace.
  - A conversation with an in-flight run still heals after a dropped
    stream (kill the tab's network mid-run, watch the run settle via
    polling); approvals still render and resume.
  - Sending a message shows the optimistic copy, which hands off to the
    server copy without flicker or duplication.

## STOP conditions

- The installed TanStack Router version cannot express a loader-time
  full-document redirect or per-route loader staleness cleanly — stop
  and report with the version and the API gap; do not reintroduce the
  effect quietly or downgrade the redirect to SPA navigation.
- The mutation hooks being bypassed in step 1 turn out to do cache work
  that cannot be replicated from the loader (no queryClient in router
  context and no clean way to add it) — stop and report.
- `refetchInterval` cannot reproduce the heal loop's stop-on-settled
  guarantee (e.g. polling continues after a run settles, or an API
  outage produces an unbounded fast poll) — stop and report; the heal
  loop guards stuck approval runs and must not regress.
- Step 4's derivation produces flicker or duplicate messages in real
  streaming (the handoff timing is the whole point) — stop and report
  rather than adding the effect back with tweaks.
