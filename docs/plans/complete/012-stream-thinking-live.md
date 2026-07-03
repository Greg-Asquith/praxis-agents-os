# Plan 012: Stream thinking parts live over SSE and render them in the chat UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat 1a51665..HEAD -- apps/api/services/agents/runtime/events.py apps/web/src/features/conversations/stream apps/web/src/features/conversations/components`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes the SSE translator and the web protocol/reducer — the live chat path)
- **Depends on**: none
- **Category**: bug / product gap
- **Planned at**: commit `1a51665`, 2026-07-01

## Why this matters

The backend deliberately enables model reasoning: agents can set the unified
`thinking` model setting, and `services/agents/models/resolution.py:60-69` even
requests OpenAI reasoning *summaries* specifically "so the transcript can show
real thinking". Persisted messages carry `ThinkingPart`s, and the web app
already renders them from stored rows (`message-parts.ts:143-149`,
`ThinkingParts` in `message-row.tsx:112-130`). But the live SSE translator
drops thinking entirely — during a run the user sees nothing until the
post-run refetch, when "Thought" sections suddenly appear. The repo's intent
doc (`docs/pydantic-ai/13-advanced-and-ecosystem.md`, "How Praxis should use
this") prescribes: "surface `ThinkingPart` deltas as a distinct streamed SSE
event to the web app so reasoning is observable but visually separable from
output."

This plan also fixes a small convention violation in the same function:
`docs/pydantic-ai/99-applying-to-praxis.md` records the decision
"`isinstance` over discriminator strings … check types, not strings, in the
sink translator", but `events.py:116-117` compares
`part.__class__.__name__ == "TextPart"`.

## Current state

### Backend

- `apps/api/services/agents/runtime/events.py` — translates Pydantic AI stream
  events into Praxis SSE events. Message events today:

  ```python
  # events.py:20-22
  EVENT_MESSAGE_START = "message.start"
  EVENT_MESSAGE_DELTA = "message.delta"
  EVENT_MESSAGE_END = "message.end"
  ```

  ```python
  # events.py:63-89 (abridged)
  if isinstance(event, PartStartEvent) and _is_text_part(event.part):
      message_id = state.start_message(event.index, run_id)
      await sink.emit(EVENT_MESSAGE_START, {"message_id": message_id, "role": "assistant"})
      if event.part.content:
          await sink.emit(EVENT_MESSAGE_DELTA, {"message_id": message_id, "text": event.part.content})
      return

  if isinstance(event, PartDeltaEvent):
      text_delta = getattr(event.delta, "content_delta", None)
      message_id = state.active_message(event.index)
      if message_id is not None and text_delta:
          await sink.emit(EVENT_MESSAGE_DELTA, {"message_id": message_id, "text": text_delta})
      return

  if isinstance(event, PartEndEvent):
      message_id = state.end_message(event.index)
      ...
  ```

  ```python
  # events.py:116-117
  def _is_text_part(part: Any) -> bool:
      return part.__class__.__name__ == "TextPart"
  ```

  `EventTranslationState` (`events.py:35-52`) tracks
  `active_message_ids: dict[int, str]` keyed by part index and mints ids
  `f"{run_id}:assistant:{n}"`.

- Verified against installed `pydantic-ai==2.1.0`: `TextPart`, `ThinkingPart`,
  `TextPartDelta`, `ThinkingPartDelta` are importable from
  `pydantic_ai.messages`. `ThinkingPartDelta` has `content_delta: str | None`
  and `signature_delta: str | None` — **`content_delta` can be None** when only
  a signature arrives; guard for that. A `PartStartEvent` for a thinking part
  carries a `ThinkingPart` with `.content`.

- The stream protocol is versioned: `events.py:31-32` defines
  `STREAM_PROTOCOL_VERSION = "1"` and the `X-Praxis-Stream-Version` header.
  Adding an **optional** field to `message.start` is backward-compatible;
  do NOT bump the version.

- Backend contract tests for translation live in
  `apps/api/tests/services/agents/runtime/test_runtime_core.py`
  (`test_event_translation_emits_message_and_tool_events`,
  `test_event_translation_emits_text_from_part_start` — they call
  `emit_agent_stream_event` directly with hand-built events and a
  `CollectingSink`). SSE route contract tests live in
  `apps/api/tests/routes/conversations/test_turn_streaming.py`.

### Frontend

- `apps/web/src/features/conversations/stream/protocol.ts:51-53` —

  ```ts
  | {
      event: "message.start"
      data: StreamEnvelope & { message_id: string; role: "assistant" }
    }
  ```

- `apps/web/src/features/conversations/stream/reducer.ts:8-13` —

  ```ts
  export type ChatMessageDraft = {
    id: string
    role: "assistant"
    text: string
    status: "streaming" | "complete"
  }
  ```

  `upsertMessageStart` / `appendMessageDelta` / `completeMessage`
  (`reducer.ts:217-263`) manage drafts; `appendMessageDelta` creates a draft
  if a delta arrives for an unknown id (keep that behavior).

- `apps/web/src/features/conversations/components/message-list.tsx:93-102` —
  renders stream drafts via `AssistantDraftRow` (in `message-row.tsx`).

- Persisted-history rendering of thinking (the visual style to match) —
  `apps/web/src/features/conversations/components/message-row.tsx:112-130`:
  a `<details className="group/thinking ...">` with a "Thought" summary and
  italic bordered body. Reuse this exact presentation for the live channel
  (extract or replicate; prefer extracting a small shared component in
  `message-row.tsx`).

- There is NO web test runner (no vitest/jest). Frontend verification is
  `pnpm check` (typecheck + lint + format:check + knip + depcruise + build).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| API tests | `cd apps/api && uv run pytest tests/services/agents/runtime tests/routes/conversations -q` | all pass |
| Web install | `cd apps/web && pnpm install` | exit 0 |
| Web full check | `cd apps/web && pnpm check` | exit 0 |

## Scope

**In scope**:
- `apps/api/services/agents/runtime/events.py`
- `apps/api/tests/services/agents/runtime/test_runtime_core.py` (extend)
- `apps/web/src/features/conversations/stream/protocol.ts`
- `apps/web/src/features/conversations/stream/reducer.ts`
- `apps/web/src/features/conversations/components/message-list.tsx`
- `apps/web/src/features/conversations/components/message-row.tsx`
- `docs/plans/000_README.md` (status row)

**Out of scope**:
- `message-parts.ts` persisted-history parsing — already handles thinking.
- The SSE sink/transport layer (`sinks.py`, `streaming.py`, `sse.ts`) — the new
  events ride the existing envelope.
- Thinking signatures (`signature_delta`) — never sent to the client.
- OpenAI `provider_details['raw_content']` fallbacks — summaries arrive as
  regular `ThinkingPart` content; do not special-case providers.
- Approval/deferred replay events (`approval_events.py`).

## Git workflow

- Branch: `advisor/012-stream-thinking-live`
- Two commits, matching repo style: `API - Stream Thinking Parts` then
  `Web - Live Thinking Display`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Translate thinking parts in the backend

In `apps/api/services/agents/runtime/events.py`:

1. Import the part/delta types:
   `from pydantic_ai.messages import TextPart, TextPartDelta, ThinkingPart, ThinkingPartDelta`
   (extend the existing import block).
2. Replace `_is_text_part` with `isinstance` checks and delete the helper.
3. Extend `EventTranslationState` so each active message also records its
   channel. Change `active_message_ids: dict[int, str]` to hold a small tuple
   or add a parallel `dict[int, str]` of channels; mint thinking ids as
   `f"{run_id}:assistant:{n}"` exactly like text (the counter is shared — ids
   stay unique and ordered).
4. In `emit_agent_stream_event`:
   - `PartStartEvent` with `isinstance(event.part, TextPart)` → current
     behavior, but include `"channel": "text"` in the `message.start` payload.
   - `PartStartEvent` with `isinstance(event.part, ThinkingPart)` → same flow
     with `"channel": "thinking"`; emit an initial `message.delta` when
     `event.part.content` is non-empty.
   - `PartDeltaEvent` → keep the existing lookup; it already works for both
     channels because `content_delta` exists on `TextPartDelta` and
     `ThinkingPartDelta`. Replace the `getattr` with
     `isinstance(event.delta, (TextPartDelta, ThinkingPartDelta))` +
     `event.delta.content_delta`, keeping the None/empty guard (thinking
     deltas may carry only a signature).
   - `PartEndEvent` → unchanged (pops whatever channel was active at that index).

`message.delta` and `message.end` payloads stay channel-free — the client
correlates by `message_id`.

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime -q` → existing translation tests pass (they assert text behavior, which is unchanged apart from the additive `channel` field — update their expected payloads to include `"channel": "text"`).

### Step 2: Backend tests

In `apps/api/tests/services/agents/runtime/test_runtime_core.py`, model after
`test_event_translation_emits_text_from_part_start`:

1. `PartStartEvent(index=0, part=ThinkingPart(content="Let me think"))` →
   `message.start` with `channel == "thinking"` plus a `message.delta` with the
   initial text.
2. `PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=" more"))` →
   `message.delta` for the same `message_id`.
3. `PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=None, signature_delta="sig"))`
   → no event emitted.
4. Interleaving: thinking part at index 0 then text part at index 1 → two
   distinct `message_id`s, channels `thinking` and `text`, both closed by their
   `PartEndEvent`s.

**Verify**: `cd apps/api && uv run pytest tests/services/agents/runtime tests/routes/conversations -q` → all pass

### Step 3: Extend the web protocol and reducer

1. `protocol.ts`: change the `message.start` variant to
   `data: StreamEnvelope & { message_id: string; role: "assistant"; channel?: "text" | "thinking" }`.
2. `reducer.ts`: add `channel: "text" | "thinking"` to `ChatMessageDraft`;
   `upsertMessageStart` takes the channel (default `"text"` when absent);
   `appendMessageDelta`'s draft-creation fallback defaults to `"text"`.

**Verify**: `cd apps/web && pnpm typecheck` → exit 0 (expect errors first until step 4 updates consumers — run it after step 4 if so).

### Step 4: Render live thinking

1. In `message-row.tsx`, extract the `<details>` "Thought" presentation from
   `ThinkingParts` into a reusable component that accepts content strings and
   an id prefix, and add a draft variant (or extend `AssistantDraftRow`) that
   renders a streaming thinking draft with the same collapsed-by-default
   `<details>` style.
2. In `message-list.tsx`, render `streamMessages` with
   `message.channel === "thinking"` through that thinking presentation instead
   of the plain `AssistantDraftRow` text path. Keep ordering as-is (drafts
   render in array order, which matches emission order).

Match existing component conventions (function components, Tailwind classes in
the file's style, no default scaffold copy).

**Verify**: `cd apps/web && pnpm check` → exit 0

### Step 5: End-to-end sanity

Run the focused API stream-route tests once more plus web build:

**Verify**: `cd apps/api && uv run pytest tests/routes/conversations -q && cd ../web && pnpm build` → all pass / exit 0

## Test plan

Backend cases in Step 2 (start/delta/signature-only/interleaving). Frontend has
no test runner — correctness there is `pnpm check` plus the reducer's
compile-time exhaustiveness. If a manual check is possible, stream a turn from
an agent whose model has `thinking` enabled and confirm a collapsed "Thought"
block fills during the run and matches the persisted rendering after refresh.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run pytest -q` exits 0; new thinking-translation tests pass
- [ ] `grep -n "__class__.__name__" apps/api/services/agents/runtime/events.py` returns no matches
- [ ] `grep -n "ThinkingPart" apps/api/services/agents/runtime/events.py` shows the isinstance handling
- [ ] `cd apps/web && pnpm check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back if:

- `ThinkingPart`/`ThinkingPartDelta` import fails or lacks `content`/`content_delta`
  (package drift).
- Existing translation tests fail for reasons other than the additive
  `channel` field.
- The reducer change would require touching `sse.ts` or `use-agent-stream.ts`
  (it should not — those are event-name agnostic transports).
- You find live thinking already rendered somewhere (feature landed since
  commit `1a51665`).

## Maintenance notes

- Provider-native tool activity (web search, code execution) also arrives as
  parts via `PartStartEvent`/`PartDeltaEvent` in 2.x (the old
  `BuiltinToolCallEvent` classes were removed). When native tools are adopted,
  this translator is the place to map those part kinds — the channel field
  established here generalizes.
- Reviewers should check the interleaving behavior: a thinking part and a text
  part can be open at different indexes simultaneously; ids must not collide
  and `message.end` must close the right one.
- Deferred: any UI affordance to auto-expand thinking while streaming; redacted
  thinking parts (persisted parser handles `redacted-thinking`; the live
  translator ignores them — acceptable for now).
