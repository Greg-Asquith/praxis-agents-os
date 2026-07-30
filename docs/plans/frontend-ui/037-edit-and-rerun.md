# Plan 037: Edit & run again — steering tools after they ran

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: TODO — ready for execution; the maintainer decision is
  recorded below (2026-07-30).
- **Written**: 2026-07-30 against HEAD `c4777c1` (clean working tree).
- **Priority**: P1 (maintainer confirmed this is the intended Google Ads
  report editing experience).
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
the system executes *exactly that call* — verbatim args, through the
normal dispatch choke point — with the result landing in the transcript
as a normal tool row. This follows the established rule that tool-UI
actions are real governed actions rather than composer prefill.

## Decision taken (maintainer, 2026-07-30)

**Option A, without model continuation.** The re-run executes the tool
directly with the user's args exactly as submitted — no model call before
the tool (nothing rewords the query) and no model call after it (no
narration turn). The transcript gains one tool row with the fresh result,
nothing else. Option B (instructed turn) is rejected: the user's edit
must be executed, not paraphrased.

Two consequences the design below absorbs:

- **The user's submission is the approval.** Since the user authored the
  exact arguments and clicked run, showing a second approval card would
  be asking them to approve their own input. The re-run executes with
  approved semantics (`ctx.tool_call_approved=True`, so in-body
  `ApprovalRequired` gates like core-memory writes are satisfied), and
  the audit record carries the acting user, `source_tool_call_id`, and
  original vs edited args — the same accountability an approval decision
  produces. Server-side permission checks are what make this safe: the
  acting user must hold the same access an approver would need.
- **The result must still reach the agent's history.** Future turns must
  see the re-run call and result exactly as they see approval-resumed
  calls, or the agent will contradict what the user is looking at.
  Persistence must reuse the existing tool-call/result part shapes — see
  step 1; if provider history cannot represent a tool call outside a
  model response, follow whatever representation the existing persisted
  history replay already uses for tool parts, and STOP if none fits.

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

1. **Backend — direct governed tool execution**: a new request shape on
   the existing conversation entry points (not a bypass route), e.g.
   `{"rerun": {"source_tool_call_id": ..., "tool_name": ...,
   "args": {...}}}`, producing a run that contains exactly one tool call
   and its result — **no model invocation before or after**.
   - Server re-derives everything it can: the tool must exist, be mounted
     for this agent (`build_runtime_tools` outcome), be available
     (workspace settings + `availability_check`), and the source tool call
     must belong to this conversation. Client args are validated against
     the tool's input schema before execution.
   - Execution goes through the normal dispatch choke point
     (`dispatch.py`) with approved semantics
     (`ctx.tool_call_approved=True` — the user's submission is the
     approval, per the decision above). Envelope rules unchanged
     (interactive runs are `allow`; this feature is interactive-only).
     Result bounding, integration fan-out, and per-resource audit all
     apply exactly as in a model-initiated call.
   - Audit: record the run as a user-initiated re-run with the acting
     user, `source_tool_call_id`, original args, and edited args —
     mirror the `original_args`/`effective_args` shape from
     `approval_events.py:265-313`.
   - Persistence: the tool call + result persist as the same message
     parts an approval-resumed call produces, so the transcript renders
     the standard tool row and subsequent model turns see the call and
     result in history. Verify the persisted-history replay path accepts
     a tool part authored this way before building the route.
2. **Eligibility contract**: a tool row offers re-run iff (a) the tool's
   presentation declares ≥1 editable arg field, (b) the conversation is
   interactive and not read-only for this user, (c) the acting user holds
   the access an approver of this tool would need (write tools included —
   the submission is the approval), and (d) the activity is settled
   (completed or failed — never running). Server enforces (a)–(c) again;
   the client check is cosmetic.
3. **Frontend affordance**:
   - Add "Edit & Run Again" to settled tool rows meeting step 2, in both
     the generic row (`tool-call-row.tsx`) and via the shared result-card
     kit so custom presenters (Google Ads report, BigQuery query, Gmail
     search, KB search) inherit it without per-presenter code.
   - Clicking opens the same field editor geometry as the approval card
     (reuse `ApprovalRequestFields` with a `Run Again` primary action;
     non-editable fields shown locked). Pre-filled from
     `replay_args ?? args`.
   - Submit dispatches the re-run request through the existing stream
     hook; the run streams into the transcript as any run does. Disable
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

- If the direct call cannot be routed through `dispatch.py`'s existing
  choke point without duplicating policy/envelope logic, stop and report;
  a second enforcement path is worse than no feature.
- If persisted history cannot represent a tool call + result without a
  surrounding model response (breaking provider replay on the next
  turn), stop and report the representation options — do not fabricate
  synthetic assistant messages without a maintainer decision.
- If scheduled/event/delegated conversations would gain the affordance,
  stop — this plan is interactive-runs-only by design.

## Verification

- `make check` at repo root.
- Manual (`make dev`): run a Google Ads report (or any read tool with
  editable fields under a test provider), edit the query from the settled
  row, confirm the exact edited query executes with no model call and the
  fresh result renders as a normal tool row; then send a follow-up chat
  message and confirm the agent's answer reflects the re-run result (it
  is in history); confirm the audit trail records the acting user with
  original and edited args.
