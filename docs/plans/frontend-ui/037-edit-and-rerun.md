# Plan 037: Edit & run again — steering tools after they ran

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: TODO — **needs a maintainer product decision before
  execution** (see "Open decision" below).
- **Written**: 2026-07-30 against HEAD `c4777c1` (clean working tree).
- **Priority**: P2 (P1 if the maintainer confirms this is the intended
  Google Ads report editing experience).
- **Effort**: L — new dispatch entry point, run-lifecycle wiring, and the
  row affordance.
- **Risk**: HIGH-ADJACENT — a new way to make an agent execute a tool.
  Everything must flow through the existing governance choke points
  (policy, envelope, approval, audit); nothing here may bypass them.
- **Depends on**: 035 (typed editors), 036 (editable declarations exist on
  read tools).

## Goal

Plans 035/036 make arguments editable **at approval time**. But the tools
users most want to steer — `google_ads_run_report`,
`bigquery_run_query`, `gmail_search_messages`, `search_knowledge` — are
read tools that auto-run by default and never show an approval card. Today
the only way to fix a wrong GAQL query is to type a correcting chat
message and hope the model reproduces the query faithfully.

After this plan, a completed (or failed) tool row whose presentation
declares editable fields grows an **"Edit & Run Again"** action: the user
edits the arguments in the same field editors the approval card uses, and
the system runs *exactly that call* as a new governed turn in the same
conversation — the agent then narrates the fresh result. This follows the
established rule that tool-UI actions dispatch governed turns rather than
prefill the composer (the Gmail reply action set this precedent).

## Open decision (maintainer)

How faithful must the re-run be?

- **Option A — seeded tool call (recommended)**: a new run in the same
  conversation whose first step is the requested tool executed verbatim
  with the edited args through the normal dispatch layer (policy check,
  envelope check, in-body `ApprovalRequired` all apply — an
  approval-policy tool re-run suspends into the normal approval card).
  The tool result then enters model history and the model continues the
  turn, narrating the result. Deterministic execution, normal governance,
  normal transcript.
- **Option B — instructed turn**: dispatch a structured user-role turn
  ("Run {tool} again with these arguments: …"). Zero new dispatch
  machinery, but the model may reword or "improve" the query — the user's
  edit is advisory, which defeats the point of field-level editing.

This plan is written for Option A. If the maintainer chooses B, steps 1–3
collapse into a message-template and most of the risk disappears (along
with the determinism).

## Current state (verified 2026-07-30 at `c4777c1`)

- Completed tool rows render via `tool-call-row.tsx:110-174` (generic) or
  custom presenters; result rows already host actions (file open/rename in
  `file-tool-row.tsx`, artifact Open, Gmail reply-via-governed-composer).
- Turn dispatch: conversations accept user turns over SSE
  (`resume-run-stream.ts` / turn-start equivalents in
  `apps/web/src/features/conversations/stream/use-agent-stream.ts`); runs
  are created server-side with server-minted envelopes
  (`services/agents/runtime/envelope.py:46` — interactive → `allow`).
- The dispatch layer already has the single choke point where policy,
  envelope, bounded results, and audit converge
  (`services/agents/runtime/dispatch.py:144-165`, `:335-354`) — the
  seeded call must enter through it, not around it.
- Tool identity for a historical row: activity carries `name` and `args`;
  presentations come from `GET /tools/presentations`
  (`use-tool-presentations.ts`). Editable fields per tool exist after 036.
- Historical note: `staged_tool_content.py` shows the codebase already has
  precedent for replay-safe argument variants (`replay_args`); re-run
  should reuse `replay_args ?? args` semantics like
  `approval-decisions.ts:56-60` does.

## Steps

1. **Backend — seeded-tool-call turn**: a new request shape on the
   existing conversation-turn entry point (not a new bypass route), e.g.
   `{"rerun": {"source_tool_call_id": ..., "tool_name": ...,
   "args": {...}}}`.
   - Server re-derives everything it can: the tool must exist, be mounted
     for this agent (`build_runtime_tools` outcome), be available
     (workspace settings + `availability_check`), and the source tool call
     must belong to this conversation. Client args are validated against
     the tool's input schema before the run starts.
   - The run executes the call through the normal dispatch path: policy
     `approval` ⇒ suspend into the standard approval card (with args
     pre-filled from the edit); envelope rules unchanged (interactive runs
     are `allow`; this feature is interactive-only).
   - Audit: record the run as user-initiated re-run with
     `source_tool_call_id`, original args, and edited args — mirror the
     `original_args`/`effective_args` shape from
     `approval_events.py:265-313`.
   - After the tool result is in history, the model continues the turn
     normally (summarize/answer). No special-cased transcript shape: it's
     a normal run with a first tool call the user authored.
2. **Eligibility contract**: a tool row offers re-run iff (a) the tool's
   presentation declares ≥1 editable arg field, (b) `effect=read` **or**
   the tool's resolved policy is `approval` (external writes re-run only
   through their approval card), (c) the conversation is not read-only for
   this user, and (d) the activity is settled (completed or failed — never
   running). Server enforces (a)–(c) again; the client check is cosmetic.
3. **Frontend affordance**:
   - Add "Edit & Run Again" to settled tool rows meeting step 2, in both
     the generic row (`tool-call-row.tsx`) and via the shared result-card
     kit so custom presenters (Google Ads report, BigQuery query, Gmail
     search, KB search) inherit it without per-presenter code.
   - Clicking opens the same field editor geometry as the approval card
     (reuse `ApprovalRequestFields` with a `Run Again` primary action;
     non-editable fields shown locked). Pre-filled from
     `replay_args ?? args`.
   - Submit dispatches the seeded turn through the existing stream hook;
     the new run streams into the transcript as any turn does. Disable
     the affordance while the conversation has an active run.
4. **Google Ads proof case**: `google_ads_run_report` — edit the GAQL
   query on a completed report row, run again, get a fresh report card.
   One test walks this end to end (mock provider transport, per the
   provider test pattern).
5. **Tests**: API — schema validation rejects unknown tool/foreign
   `source_tool_call_id`/unmounted tool; approval-policy tool suspends;
   audit record shape; envelope untouched. Web — eligibility matrix,
   editor prefill, dispatch payload, running-state lockout.

## STOP conditions

- Maintainer has not chosen Option A vs B — stop before writing code.
- If the seeded call cannot be routed through `dispatch.py`'s existing
  choke point without duplicating policy/envelope logic, stop and report;
  a second enforcement path is worse than no feature.
- If scheduled/event/delegated conversations would gain the affordance,
  stop — this plan is interactive-runs-only by design.

## Verification

- `make check` at repo root.
- Manual (`make dev`): run a Google Ads report (or any read tool with
  editable fields under a test provider), edit the query from the settled
  row, confirm a new governed turn runs the exact edited query and the
  agent narrates the result; confirm an approval-policy tool re-run lands
  on the standard approval card instead of executing directly.
