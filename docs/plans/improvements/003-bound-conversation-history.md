# Plan 003: Bound conversation history reads and paginate the messages API

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/improvements/README.md`.
>
> **Drift check (run first)**: `git diff --stat a0eea1c..HEAD -- apps/api/services/agents/runtime/persistence.py apps/api/services/agents/runtime/history.py apps/api/services/conversations/list_messages.py apps/api/routes/conversations/list_messages.py apps/api/core/settings/agents.py apps/web/src/features/conversations/api/list-messages.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches runtime history semantics; skills/capability replay must survive)
- **Depends on**: none (001 recommended first for the test gate)
- **Category**: perf
- **Planned at**: commit `a0eea1c`, 2026-07-06

## Why this matters

Every agent turn re-reads and re-deserializes the entire conversation
transcript from Postgres, and the messages REST endpoint ships the entire
transcript in one response. The in-memory trimmer (`ProcessHistory`) then
throws most of it away — so long-lived conversations (exactly what scheduled
agents produce) pay linearly growing DB I/O, CPU, and latency per turn, and
unbounded response payloads per page load. The code itself flags this:
`load_message_history`'s docstring says "Pending: this intentionally returns
the full stored history."

The hard constraint: history trimming replays dropped capability-load pairs
so agents don't silently lose loaded skills (see `docs/plans/000_README.md`,
the 013/018 interaction note). A naive `LIMIT N` DB read would cut
capability-load messages out before the trimmer ever sees them — the plan
below backfills them explicitly.

## Current state

Relevant files (under `apps/api/` unless noted):

- `services/agents/runtime/persistence.py` — full-history DB read (lines 20-46):

  ```python
  async def load_message_history(
      db: AsyncSession,
      *,
      conversation_id: UUID,
  ) -> list[ModelMessage]:
      """Load persisted Pydantic AI history for a conversation.

      Pending: this intentionally returns the full stored history. ...
      """
      rows = await db.scalars(
          select(ConversationMessage)
          .where(
              ConversationMessage.conversation_id == conversation_id,
              ConversationMessage.deleted == False,  # noqa: E712
          )
          .order_by(ConversationMessage.sequence)
      )
      stored = [
          row.parts
          for row in rows
          if (row.metadata_json or {}).get("source") == PYDANTIC_AI_MESSAGE_SOURCE
      ]
      if not stored:
          return []
      return list(ModelMessagesTypeAdapter.validate_python(stored))
  ```

  `PYDANTIC_AI_MESSAGE_SOURCE = "pydantic_ai"`. Called from
  `services/agents/runtime/execute_run.py:173`. One `ConversationMessage`
  row ≈ one `ModelMessage`; `parts` is a `JSONB` column and `metadata_json`
  is a `JSONB` column named `"metadata"` (`models/conversation.py:137-138`);
  `sequence` is `BigInteger` with index
  `ix_conversation_messages_conversation_sequence (conversation_id, sequence)`.

- `services/agents/runtime/history.py` — `trim_history(messages, *, max_turns,
  keep_turns)` trims prior history at user-turn watermarks and, crucially,
  reconstructs `LoadCapabilityCallPart`/`LoadCapabilityReturnPart` pairs from
  the **dropped** prefix into synthetic messages (lines 21-60). It is invoked
  as a `ProcessHistory` capability built in
  `services/agents/runtime/capabilities.py`, driven by settings.

- `core/settings/agents.py` — `AGENT_HISTORY_MAX_TURNS: int | None`
  (line 74; `None` disables trimming), `AGENT_HISTORY_KEEP_TURNS: int`
  (line 79, validated `> 0` and `< max_turns` in
  `core/settings/__init__.py`).

- `services/conversations/list_messages.py` — service (lines 25-45): selects
  ALL non-deleted messages ordered by `sequence`, returns
  `ConversationMessagesResponse(messages=[...], total=len(messages))`. No
  limit.

- `routes/conversations/list_messages.py` — route: no query params.

- Pagination convention to copy: `services/conversations/list_conversations.py`
  caps at 500 and uses limit/offset-style params; mirror its parameter naming
  and validation style.

- Frontend consumer: `apps/web/src/features/conversations/api/list-messages.ts`
  (TanStack Query read; types in `apps/web/src/features/conversations/types.ts`).
  API types are hand-written per feature; use `type` aliases, not `interface`.

## Commands you will need

| Purpose | Command (from `apps/api/`) | Expected on success |
|---------|---------------------------|---------------------|
| Lint | `uv run ruff check .` | exit 0 |
| Runtime tests | `TEST_DATABASE_URL=<url> uv run pytest tests/services/agents/runtime -q` | all pass |
| Conversations tests | `TEST_DATABASE_URL=<url> uv run pytest tests/services/conversations tests/routes/conversations -q` | all pass |
| Web gate | `cd apps/web && pnpm check` | exit 0 |

## Scope

**In scope**:
- `apps/api/services/agents/runtime/persistence.py`
- `apps/api/core/settings/agents.py` (one new setting)
- `apps/api/services/conversations/list_messages.py`
- `apps/api/services/conversations/schemas.py` (add `has_more` to `ConversationMessagesResponse`)
- `apps/api/routes/conversations/list_messages.py`
- `apps/api/tests/services/conversations/**`, `apps/api/tests/services/agents/runtime/**`, `apps/api/tests/routes/conversations/**` (new/updated tests)
- `apps/web/src/features/conversations/api/list-messages.ts`, `apps/web/src/features/conversations/types.ts` (additive response field only)

**Out of scope**:
- `services/agents/runtime/history.py` (`trim_history`) — do NOT change the
  trimmer; this plan feeds it a bounded superset, nothing else.
- The SSE stream path and `ProcessHistory` capability wiring in
  `capabilities.py`.
- Any UI "load older messages" affordance — deferred follow-up.
- Summarization of dropped history — explicitly rejected for now; windowing only.

## Git workflow

- Branch: `advisor/003-bound-conversation-history`
- Commit per step; message style e.g. `API - Bounded History Load`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Probe the persisted capability part shape

The backfill query in Step 2 matches JSONB by `part_kind` literals. Confirm
them against the installed pydantic-ai 2.1.0 before writing SQL:

```bash
cd apps/api && uv run python -c "
from pydantic_ai.messages import LoadCapabilityCallPart, LoadCapabilityReturnPart
import inspect
print(inspect.getsource(LoadCapabilityCallPart)[:400])
print(inspect.getsource(LoadCapabilityReturnPart)[:400])
"
```

Record the exact `part_kind` literal values (expected to be strings like
`"load-capability-call"` / `"load-capability-return"`, but use what the
source says). Also open one persisted `ConversationMessage.parts` value from
a dev DB or an existing runtime test fixture to confirm the stored JSON shape
is `{"parts": [{"part_kind": ..., ...}], ...}` per message.

**Verify**: both literals recorded; stored shape confirmed. If the stored
shape nests differently, STOP.

### Step 2: Bound the runtime history read with capability backfill

In `core/settings/agents.py`, add beside the existing history settings:

```python
AGENT_HISTORY_DB_MAX_MESSAGES: int = Field(
    default=500,
    ge=50,
    le=5000,
    description="Max persisted messages loaded per turn before trimming",
)
```

Rewrite `load_message_history` in `services/agents/runtime/persistence.py`:

1. Keep the exact current behavior when `settings.AGENT_HISTORY_MAX_TURNS is
   None` (trimming disabled → windowing must be disabled too, or resumed
   conversations would silently lose old context).
2. Otherwise:
   - Move the source filter into SQL:
     `ConversationMessage.metadata_json["source"].astext == PYDANTIC_AI_MESSAGE_SOURCE`.
   - **Tail window**: select the last `AGENT_HISTORY_DB_MAX_MESSAGES` matching
     rows by `sequence` descending (subquery), re-sorted ascending.
   - **Capability backfill**: select all matching rows with
     `sequence < <lowest sequence in the window>` whose `parts` contain a
     capability part, using JSONB containment with the literals from Step 1:

     ```python
     from sqlalchemy import or_
     capability_filter = or_(
         ConversationMessage.parts.op("@>")(
             {"parts": [{"part_kind": "<call literal>"}]}
         ),
         ConversationMessage.parts.op("@>")(
             {"parts": [{"part_kind": "<return literal>"}]}
         ),
     )
     ```

   - Result = backfilled capability messages (ascending) + window (ascending),
     validated through `ModelMessagesTypeAdapter` exactly as today. The
     existing `trim_history` then treats old capability messages as part of
     the dropped prefix and replays the pairs synthetically — that mechanism
     already exists and must not be duplicated here.
   - Skip the backfill query entirely when the window is not full (fewer
     matching rows than the cap ⇒ nothing was cut).

**Verify**: `uv run ruff check .` → exit 0;
`TEST_DATABASE_URL=<url> uv run pytest tests/services/agents/runtime -q` →
all existing tests pass.

### Step 3: Paginate the messages endpoint

1. `services/conversations/list_messages.py`: accept
   `limit: int = 500` and `before_sequence: int | None = None`. Query the
   **latest** `limit` non-deleted messages (with `sequence < before_sequence`
   when given) via descending subquery, return ascending. Compute `has_more`
   (a row exists below the returned window) and keep `total` as the full
   non-deleted count (add a `select(func.count())` — match how
   `list_files.py` builds its `count_stmt`).
2. `services/conversations/schemas.py`: add `has_more: bool = False` to
   `ConversationMessagesResponse`.
3. `routes/conversations/list_messages.py`: add
   `limit: Annotated[int, Query(ge=1, le=500)] = 500` and
   `before_sequence: Annotated[int | None, Query()] = None`, passing through.
   Mirror the query-param style used by `routes/conversations/list_conversations.py`.
4. `apps/web`: add `has_more?: boolean` to the messages response type in
   `features/conversations/types.ts` (or the exact type used by
   `api/list-messages.ts`). No behavior change — the default limit of 500
   covers current usage; a "load older" UI is a recorded follow-up.

**Verify**: `TEST_DATABASE_URL=<url> uv run pytest tests/services/conversations tests/routes/conversations -q` → all pass;
`cd apps/web && pnpm check` → exit 0.

## Test plan

New/extended tests (model after the existing files in
`tests/services/conversations/` and `tests/services/agents/runtime/`; async
modules need `pytestmark = pytest.mark.asyncio` unless plan 001's auto mode
has landed):

- **Windowed load, pairs preserved** (the regression this plan exists for):
  seed a conversation with a capability-load call/return message pair early,
  then more than `AGENT_HISTORY_DB_MAX_MESSAGES` later messages (use a small
  settings override fixture, e.g. cap = 50, the way existing runtime tests
  override settings). Assert `load_message_history` returns ≤ cap + backfill
  messages, includes the capability pair, and
  `ModelMessagesTypeAdapter` round-trips without error.
- **Windowing disabled when trimming disabled**: with
  `AGENT_HISTORY_MAX_TURNS=None`, a conversation larger than the cap loads in
  full.
- **Window not full**: conversation smaller than the cap loads identically to
  the old behavior (byte-equal message list).
- **Pagination**: seed 30 messages; `limit=10` returns the latest 10 ascending
  with `has_more=True` and `total=30`; `before_sequence=<lowest returned>`
  returns the previous 10; walking to the start ends with `has_more=False`.
- **Route contract**: `limit=0` and `limit=501` → 422.

**Verification**: `TEST_DATABASE_URL=<url> uv run pytest tests/services/agents/runtime tests/services/conversations tests/routes/conversations -q` → all pass including the new tests.

## Done criteria

- [ ] `uv run ruff check .` exits 0
- [ ] All commands in the Test plan pass
- [ ] `grep -n "intentionally returns the full stored history" apps/api/services/agents/runtime/persistence.py` returns no match (docstring updated to describe the windowed behavior)
- [ ] `grep -n "AGENT_HISTORY_DB_MAX_MESSAGES" apps/api/core/settings/agents.py` matches
- [ ] `grep -n "has_more" apps/api/services/conversations/schemas.py` matches
- [ ] `cd apps/web && pnpm check` exits 0
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/improvements/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 shows persisted `parts` JSON does not nest as
  `{"parts": [{"part_kind": ...}]}` — the containment filter is then wrong
  and the backfill needs a different design.
- `ConversationMessage.parts` is not JSONB in the live model (containment
  `@>` requires JSONB).
- Any existing runtime test fails after Step 2 in a way not explained by the
  window cap — that suggests approval/tool-return rehydration depends on
  messages the window cut; report with the failing test name.
- The web `list-messages.ts` consumer turns out to render paged data in a way
  that breaks with `limit=500` default (e.g. it asserts on `total ===
  messages.length`).

## Maintenance notes

- Plan 013's trimmer (`trim_history`) and this DB window must stay consistent:
  if `AGENT_HISTORY_MAX_TURNS`'s semantics change, revisit
  `AGENT_HISTORY_DB_MAX_MESSAGES` (it must always cover ≥ max_turns worth of
  messages; 500 messages vs. default turn caps leaves a wide margin — a
  reviewer should sanity-check that margin against the configured defaults).
- Follow-up (deferred): a "load older messages" UI using `before_sequence`;
  moving `total` to an estimate if COUNT ever becomes hot.
- Reviewers should scrutinize: the ascending/descending re-sort correctness at
  window boundaries, and that the backfill can never duplicate a message that
  is also inside the window (`sequence <` strict inequality).
