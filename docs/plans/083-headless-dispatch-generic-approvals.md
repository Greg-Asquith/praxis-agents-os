# Plan 083: Headless dispatch, app-principal envelopes, and the generic approval primitive

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: implements
> `docs/architecture/internal-applications.md` §5.2–§5.3 and §10 slice 1
> (adopted 2026-07-20, D13; Gate G7 registers here). Re-read §5 before
> coding; the note wins on intent. This plan was written at adoption time,
> ahead of Phase 4a/4b completion — **re-anchor every excerpt below against
> live code at execution time**; treat structural drift in `dispatch.py`,
> envelopes, or the approvals flow as a STOP, not a formality.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/services/agents/runtime/dispatch.py apps/api/services/agents/runtime/envelope*.py apps/api/services/agents/runtime/tools/ apps/api/models/ apps/api/services/audit_events/`

## Status

- **Priority**: P1 (within Phase 7)
- **Effort**: L
- **Risk**: HIGH (a second entrypoint into the audited execution path;
  the entire point is that it cannot bypass anything the agent path
  enforces)
- **Depends on**: hard — 026 (choke point), 054 (envelopes), 082
  (tool version + workspace grants). Soft — 055 (add scenarios if landed).
  Ordering: after Phase 4a/4b product value (040–042); first code slice of
  Phase 7.
- **Category**: Phase 7 internal applications (roadmap §4; design note §10
  slice 1)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **Wrap the choke point; add no layer inside it.** The headless
   entrypoint is a new module (e.g.
   `services/agents/runtime/headless.py`) that mints an envelope, builds
   the minimal runtime context, and calls through the existing
   `dispatch.py` machinery — honoring the module docstring's "wrap this
   module" contract (pinned by the 062–066 rejection of a dispatch
   split). Every audit, output-contract, truncation (076), and envelope
   behavior is inherited, not reimplemented.
2. **The app principal is the user, narrowed.** Signature (final names at
   execution): `execute_headless_tool(db, *, workspace, user, application,
   application_version, tool_name, args) -> HeadlessToolOutcome`. The
   envelope is minted from the user's workspace role **intersected with**
   the application contract's declared scopes; the workspace tool-grant
   seam (082) applies before anything runs. An app can never do what its
   user cannot, and never more than its contract declares.
3. **External writes default to `require_approval`; contracts cannot
   weaken `supports_auto=False`** [default — confirm at review, note
   §5.3]. The app envelope stamps `require_approval` for external-scope
   writes exactly as scheduled runs do (054); a contract may relax
   *internal* writes to auto where the tool supports it, never the
   reverse.
4. **Generic approvals are rows, not paused conversations.** New core
   table `approval_requests`: workspace_id, origin
   (`app` now; `schedule`/`agent` migrate later, see maintenance),
   application_id/version, tool_name/tool_version, args digest + stored
   args (encrypted at rest is unnecessary — args already land in audit
   digests; store plaintext JSONB, size-bounded), requested_by,
   status (`pending/approved/denied/expired/executed/failed`),
   decided_by/decided_at, expiry. A suspended headless call creates a
   row and returns a `pending_approval` outcome with the request id.
5. **Decision executes the call.** Approve → the original call executes
   under the decider-checked envelope (approval satisfies the
   `require_approval` grant, mirroring the conversation resume path);
   deny → terminal denied outcome. The caller (an app frame) polls
   `GET .../approval-requests/{id}` for the outcome. No push channel in
   v1.
6. **Surfaced in the existing approvals surface.** The pending-approvals
   UI treatment gains generic rows (origin-labeled) alongside
   conversation approvals — read + decide routes are this plan's; the UI
   wiring may land with 088 if the web slice is deferred [default —
   confirm at review: backend + minimal list/decide UI here].
7. **Attribution is (user, via application, version).** Tool audit rows
   from headless dispatch carry application id + version in metadata;
   the audit viewer renders them generically until 088.

## Why this matters

This is the enforcement keystone of the internal-applications
architecture: applications get exactly one way to touch the world — the
same audited, effect-classified, envelope-checked dispatch path agents
use. Everything downstream (084 tokens, 085 serving, 086 data, 087 kit)
assumes this seam exists and is airtight. Gate G7 exists to keep it that
way.

## Current state (verify at execution)

- `services/agents/runtime/dispatch.py` — the single choke point; audits
  every invocation, enforces envelopes/output contracts/result bounds;
  docstring pins "wrap this module, don't add layers".
- 054's envelope: principal-derived side-effect grants
  (`require_approval` default for unattended external writes; explicit
  allow for schedules), inherited by delegated children at mint time.
- Approvals today are conversation-coupled: pydantic-ai deferred tool
  requests suspend a run; resume happens through the conversation
  surface. There is no approval row independent of an `agent_run`.
- `models/` has no approval table; audit events carry
  `tool_name`/`tool_provider` columns.
- 082 (must be DONE): tool `version`, workspace tool grants,
  `is_tool_allowed` real.

## Scope

**In scope:**

- `services/agents/runtime/headless.py` (create) — entrypoint + outcome
  types; envelope minting for app principals
- `models/approval_requests.py` (create) + core migration (D5)
- `services/approvals/` (create): create/get/list/decide operations (one
  per file), expiry sweep job kind on the 030 harness, audit writes
- `routes/approvals/` (create): workspace-scoped list (pending +
  decided), get, decide (approve/deny; decider must hold the role the
  tool's effect demands per `governance.md` §1/§2)
- Minimal web approvals-list wiring if decision 6's default stands
- Tests: envelope narrowing, approval lifecycle, denial, expiry,
  cross-workspace isolation, audit attribution
- 055 scenarios for headless dispatch if the scenario suite exists

**Out of scope (do NOT touch):**

- Tokens/auth for app callers (084) — this plan's entrypoint is called
  by trusted route code with an already-resolved user; no new auth
  surface.
- The application model itself (085) — until it lands, `application`
  is typed as an id + version pair; tests use a stub registration.
  If executing after 085, use the real model.
- Migrating conversation approvals onto the generic table — recorded as
  maintenance, not v1.
- Any provider/tool code changes.

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: `main`)
- Commit style: `API - Headless Dispatch & Generic Approvals`
- Do NOT commit without explicit operator approval.

## Steps (coarse — refine against live code at execution)

1. **Envelope minting for app principals**: a mint function taking (user
   role, contract scopes) → envelope with decision 3's defaults; unit
   tests pin the intersection semantics and the no-weakening rule.
2. **Approval model + migration + services**: table per decision 4;
   create/get/list/decide/expire operations; decide validates role,
   records decision, audits.
3. **Headless entrypoint**: build minimal deps, run through dispatch;
   map dispatch outcomes (success/failed/suspended-for-approval) to
   `HeadlessToolOutcome`; suspended → approval row + pending outcome.
4. **Approve-executes path**: decision triggers execution under the
   stored args + fresh envelope check; result stored on the request row
   (bounded, 076 rules apply via dispatch).
5. **Routes** + minimal UI list/decide if in scope.
6. **Tests + scenarios**.

## Test plan

Pinned invariants: **headless calls write the same audit rows as agent
calls** (attributed via app metadata), **an app envelope is never wider
than its user's role or its contract**, **external writes suspend without
an approval**, **an approved request executes exactly once**
(idempotency under double-decide), **cross-workspace requests 404**,
**expiry sweeps pending rows to `expired`**.

## Done criteria

- [ ] Ruff + alembic clean; migration round-trips
- [ ] Headless dispatch reuses `dispatch.py` (no forked execution path —
      review the diff for duplicated audit/envelope logic)
- [ ] Approval lifecycle green end to end incl. expiry sweep
- [ ] DB-backed suites for new modules pass; existing runtime suites
      unchanged
- [ ] `docs/architecture/governance.md` approval rows updated if cells
      flip; `000_README.md` row updated

## STOP conditions

- `dispatch.py`'s structure or its "wrap this module" contract has
  changed such that a headless caller cannot reuse it without edits
  inside the module — reconcile design first.
- 082 is not DONE (no tool `version`/grants to enforce).
- The envelope model (054) has been reworked by an intervening plan —
  re-derive decision 2/3 against the live shape.
- You find yourself adding a second audit writer, a second effect
  classifier, or an approval path that executes outside dispatch — that
  is the exact failure Gate G7 exists to block.
- Storing full args on approval rows conflicts with a governance/audit
  retention rule added since planning — check `governance.md` §3 first.

## Maintenance notes

- **Conversation-approval convergence**: the long-term shape is one
  approval primitive with `origin ∈ {conversation, schedule, app}`;
  migrating the conversation path onto this table is a recorded
  follow-up (FOLLOW_UPS.md) — do not attempt it here.
- 084 consumes the entrypoint from token-authenticated routes; 086's
  data writes do NOT go through dispatch (they are app-surface CRUD, not
  registry tools) — the boundary is: registry tools → dispatch;
  app-native surfaces → their own audited services.
- Reviewers should scrutinize: the role check on decide, the
  double-decide race (row lock), and that pending outcomes leak no
  cross-workspace existence.
