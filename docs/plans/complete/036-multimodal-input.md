# Plan 036: Multimodal chat input over Files

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Sibling-plan pre-flight (run before Step 1)**: hard dependencies that
> must be implemented in code at execution time: 031 (`models/files.py` —
> `File`, `FileRevision`, `FileReference` with
> `target_type="conversation"`, and the file-contract policy) and 032
> (`services/files/` + `/api/v1/files` two-phase upload — attachments are
> uploaded through it before the message is sent). Soft dependencies: 035
> (the `FileCard` component and `features/files/api` upload operations —
> Step 6 creates minimal versions if 035 has not landed) and 034 (the
> `<available_files>` prompt block lists the references this plan creates;
> without 034 they are simply not disclosed in the prompt yet). If a hard
> dependency is missing, STOP.
>
> **Re-probe pydantic-ai before coding**: every multimodal API fact below
> was probed against the installed `pydantic-ai==2.1.0` at `0cbbb39`. Run
> the probe snippet in "Current state" again at execution time; on any
> mismatch (import paths, constructor fields, `run_stream_events` accepting
> `Sequence[UserContent]`, the `ModelMessagesTypeAdapter` round-trip),
> treat it as a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 0cbbb39..HEAD -- apps/api/services/conversations/ apps/api/services/agents/runtime/ apps/api/routes/conversations/ apps/api/core/settings/ apps/web/src/features/conversations/`
> Changes from plans 030–035 landing are expected. For any other in-scope
> file that changed since `0cbbb39`, compare the "Current state" excerpts
> against the live code before proceeding; on a mismatch, treat it as a
> STOP condition. Note `features/conversations/message-parts/` and two chat
> components carried **uncommitted local edits at planning time** — anchor
> Step 7/8 to what is on disk.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM-HIGH (touches the send-message path for every
  conversation, the runtime's user-prompt construction, and message
  persistence; a regression here breaks plain-text chat, so the no-attachment
  path must be provably byte-identical)
- **Depends on**: 031 + 032 (hard — Files substrate and upload API), the
  file-contract policy (031), 035 (soft — card/upload reuse; UI slice
  ordered after 035's card work), 034 (soft — prompt disclosure of the
  references this plan creates)
- **Category**: Phase 3 files & jobs (roadmap `000_MASTER_ROADMAP.md` §4
  row 036 — "From NOTES; new — not in donor roadmap")
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

1. **Attachments ride Files, referenced by id.** The client uploads
   through 032's two-phase flow first, then sends the message with
   `attachments: [file_id, ...]`. The send routes never accept raw bytes —
   upload limits, contract validation, dedup, and storage stay in one
   place (032), and the message payload stays small. Each send creates a
   `FileReference(target_type="conversation")` row (idempotent per
   file×conversation), which is exactly what 034's `<available_files>`
   block lists — attaching a file once makes it readable by the agent in
   every later turn via `read_file`, not just visible to the model in the
   turn's images.
2. **`BinaryContent`, not `ImageUrl`/`DocumentUrl`.** Probed: all three
   exist in `pydantic_ai.messages` (also re-exported from `pydantic_ai`),
   but URL classes require the *provider* to fetch the URL. Local-dev
   storage URLs (`local_fs`) are unreachable from provider backends, and
   signed URLs expire while message history lives forever — a resumed or
   continued conversation would replay dead links. `BinaryContent(data=...,
   media_type=..., identifier=str(file.id))` is provider-uniform and
   round-trips through persistence (decision 4). The `identifier` field
   (probed: pydantic alias on `_identifier`) carries the file id so the
   frontend can render chips from persisted parts without the bytes.
3. **Gating = file contract × model capability × size caps.**
   - Contract category `image`: media type must be in the probed
     `ImageMediaType` set (jpeg/png/gif/webp) **and** the agent's resolved
     catalog model must have `supports_vision`
     (`services/agents/models/domain.py:53-54`; set on every current
     catalog entry in `services/agents/models/registry.py` — the flag the
     roadmap said might be needed **already exists**, no schema change).
     Size ≤ `MAX_FILE_SIZE_IMAGE` (10 MB, `core/settings/files.py:73-78`,
     governance §4 *(enforced today)* — reused, not redefined).
   - Contract category `ingestible-document`: media type must be in the
     probed `DocumentMediaType` set (pdf, plain, csv, docx, xlsx, html,
     markdown, msword, ms-excel). Size ≤ new
     `MAX_MULTIMODAL_DOCUMENT_BYTES` (20 MB — deliberately under
     Anthropic's 32 MB request ceiling with headroom for base64 + text).
   - Contract category `editable-text`: attached as
     `BinaryContent(media_type="text/plain" | actual text type)` — the
     text types are all in the probed document set, so no special path.
     Plan 031's file contract also accepts `text/html`; this plan
     must either map that stored MIME to the provider-supported HTML media
     type or reject it at the model-capability gate rather than weakening
     the shared file contract.
   - Count ≤ new `MAX_CHAT_ATTACHMENTS` (5). Violations are typed
     `AppValidationError`s (RFC 7807) at send time — fail fast in the
     request, never inside the background run.
   - `processing_status` is **not** required to be `ready`: the model gets
     raw bytes, not 033's markdown, so a just-confirmed PDF is attachable
     immediately.
4. **Persisted history carries the bytes; this is an accepted,
   size-capped cost.** Probed round-trip: a `UserPromptPart(content=["…",
   BinaryContent(...)])` inside a `ModelRequest` survives
   `ModelMessagesTypeAdapter.dump_json` → `validate_json` with `data`,
   `media_type`, and `identifier` intact (base64 in the JSON). The
   existing persistence layer (`runtime/persistence.py:100-101` dump,
   `38-45` load) therefore handles multimodal messages **with zero
   changes**, and resumed/continued runs replay attachments correctly.
   Cost: base64 blobs in `conversation_messages.parts` (a 10 MB image ≈
   13.4 MB of JSONB) re-sent to the provider every subsequent turn.
   Mitigations: the decision-3 caps now; plan 013's history trimming preserves
   whole user turns, and any later byte-aware multimodal pressure valve belongs
   in this plan or a follow-up.
5. **Content assembly happens in `execute_run`, ids travel with the
   run.** The send services validate attachments in-request and commit
   `FileReference` rows; the file ids are passed through
   `run_turn_worker` into `execute_run` (explicit parameter) and also
   recorded in the run's metadata (`build_interactive_run_metadata`) for
   audit/debug. `execute_run` loads the blobs via the storage provider and
   builds `user_prompt: [text, *BinaryContent...]` just before
   `run_stream_events`. Probed: `Agent.run_stream_events` (and
   `Agent.run`) accept `user_prompt: str | Sequence[UserContent] | None`.
   Building in the worker-side session (not the request) keeps request
   latency flat and reuses the run's transaction/error handling; a
   storage failure becomes an ordinary failed run.
6. **The resume path needs nothing.** Resume calls pass
   `user_prompt=None` + rehydrated history
   (`runtime/worker.py:118`, `execute_run.py:128-139`); decision 4's
   round-trip means the attachments are already in that history.
7. **No new SSE events.** The frontend parser throws on unknown event
   names (`stream/sse.ts:74`; 000_README records this precedent for
   skills). Attachments render from (a) the client's own pending-message
   state during the turn and (b) persisted user-message parts afterwards —
   both already flow through existing machinery.
8. **Scheduled runs stay text-only in this plan.** `AgentSchedule` prompts
   have no attachment surface; `schedule_run` FileReference targets exist
   in 031's `target_type` vocabulary for a future plan. Delegation
   likewise passes text task instructions (`delegate_to_agent` is
   unchanged) — a delegate reads attached files through 034's `read_file`
   instead.

## Why this matters

This is the NOTES item the roadmap graduated into Phase 3 (§5
"multimodal (036)"): users paste screenshots and PDFs at agents in every
comparable product, and Praxis agents currently cannot see them. Doing it
*over Files* — rather than inlining upload bytes into the chat payload —
is the difference between a demo and a substrate: attachments get
dedup, contract enforcement, revision provenance, signed downloads, an
agent-readable listing (034), and a UI home (035) for free, and the same
`FileReference` mechanism later carries artifact and schedule-run
attachments.

## Current state

All anchors verified at `0cbbb39`.

### Where user text becomes model input (the path this plan widens)

- Route → service: `routes/conversations/create_turn.py` /
  `create_conversation.py` are thin wrappers over
  `services/conversations/create_turn_stream.py` and
  `create_conversation_stream.py`.
- `services/conversations/schemas.py` —
  `ConversationCreateRequest` (17-37) and `ConversationTurnCreateRequest`
  (39-57): `user_prompt` (1–20000 chars, stripped) +
  `client_message_id`. **This is where `attachments` is added and
  validated structurally.**
- `services/conversations/create_turn_stream.py` — validates conversation
  state, creates the run with
  `build_interactive_run_metadata(...)` (99-110), commits, then spawns
  `run_turn_worker(run_id=..., conversation_id=...,
  user_prompt=payload.user_prompt, sink=..., client_message_id=...)`
  (115-124). `create_conversation_stream.py` does the same after creating
  the conversation (fallback title from `payload.user_prompt` at line 70 —
  title generation stays text-only).
- `services/agents/runtime/worker.py` — `run_turn_worker(*, run_id,
  conversation_id, user_prompt: str, sink, client_message_id)` (33-37)
  forwards `user_prompt` to `execute_run` (64); the resume worker passes
  `user_prompt=None` (118).
- `services/agents/runtime/execute_run.py` — `user_prompt: str | None`
  parameter (87), guard requiring a prompt or deferred results (128-133),
  and the hand-off `runtime_agent.agent.run_stream_events(user_prompt,
  ...)` (201-208). **The type widens here.**
- `services/agents/runtime/persistence.py` — user prompts are persisted
  from pydantic-ai's `new_messages()` via
  `ModelMessagesTypeAdapter.dump_json` (100-101) and rehydrated via
  `validate_python` (38-45); `_role_for_message` maps `user-prompt` parts
  to role `user` (122-135). Decision 4: no changes needed — pin with a
  test.
- Attachment validation seam: nothing exists — 032's files service plus a
  new `services/files/` operation added here (Step 2).

### Model catalog capability

- `services/agents/models/domain.py:45-54` — `ModelInfo` carries
  `supports_vision: bool = False` (53-54). `registry.py` sets it on every
  current entry (e.g. lines 21-28, 53-60, 109-116); `get_model(provider,
  model)` (144-152) resolves it. `resolve_agent_model(agent)` returns the
  provider/model pair to look up.

### Probed against installed pydantic-ai 2.1.0 (re-run at execution time)

```python
# from apps/api: uv run python - <<'EOF' ... EOF
from pydantic_ai import Agent
from pydantic_ai.messages import (
    BinaryContent, ImageUrl, DocumentUrl, UserContent, UserPromptPart,
    ModelRequest, ModelMessagesTypeAdapter, ImageMediaType, DocumentMediaType,
)
```

- `UserContent` union: `str | TextContent | (ImageUrl | AudioUrl |
  DocumentUrl | VideoUrl | BinaryContent | UploadedFile, discriminated on
  "kind") | CachePoint`; `UserPromptPart.content: str |
  Sequence[UserContent]`.
- `Agent.run` and `Agent.run_stream_events`: `user_prompt: str |
  Sequence[UserContent] | None`.
- `BinaryContent` fields: `data: bytes`, `media_type: AudioMediaType |
  ImageMediaType | DocumentMediaType | str`, `vendor_metadata: dict |
  None`, `identifier` (alias for `_identifier`), `kind="binary"`;
  `.is_image` works; `identifier` round-trips.
- `ImageUrl`/`DocumentUrl` fields: `url`, `force_download`,
  `vendor_metadata`, `media_type` + `identifier` aliases;
  `ImageUrl(url=".../a.png").media_type` infers `image/png`. (Recorded for
  completeness — decision 2 rejects them for this plan.)
- `ImageMediaType` = `image/jpeg, image/png, image/gif, image/webp`;
  `DocumentMediaType` = `application/pdf, text/plain, text/csv,
  docx-openxml, xlsx-openxml, text/html, text/markdown,
  application/msword, application/vnd.ms-excel`. Plan 031 stores HTML as
  `text/html`; 036 owns any pass-through mapping because model
  support is provider-specific and the file contract is shared.
- Round-trip: `ModelMessagesTypeAdapter.dump_json([ModelRequest(parts=
  [UserPromptPart(content=["look", BinaryContent(data=b"\x89PNG",
  media_type="image/png", identifier="file-abc")])])])` →
  `validate_json` returns `BinaryContent` with `data`, `media_type`, and
  `identifier` preserved.

### Frontend (anchored to disk, including uncommitted message-parts edits)

- Composer — `features/conversations/components/conversation-composer.tsx`:
  create/turn modes (27-41), submit builds `PendingUserMessage` and sends
  `{agent_id?, client_message_id, user_prompt}` (73-110). **Attach control
  and `attachments` land here.**
- Request types — `features/conversations/types.ts:84-90`
  (`user_prompt`, `client_message_id?`); transport
  `features/conversations/api/create-turn-stream.ts` posts the payload
  as-is.
- Pending messages — `message-parts/types.ts:57-62` `PendingUserMessage`
  (`clientMessageId`, `conversationId`, `text`, `createdAt`).
- Parsing — `message-parts/parse.ts:147-155`: `user-prompt` parts run
  `extractContentText(part["content"])`; the array walker (295-313) pulls
  `text`/`content` string fields per item, so **binary items currently
  fall through to an "unsupported part" preview** — Step 8 fixes this
  (chips, and base64 must never reach the render tree).
- `ParsedConversationMessage` — `message-parts/types.ts:44-55` (`text`,
  `thinking`, `toolActivities`, `unsupportedParts`) — gains
  `attachments`.
- SSE protocol — `stream/protocol.ts:12-24` event whitelist;
  `stream/sse.ts:74` throws on unknown names. Untouched.
- Card/upload reuse — 035's `features/files/components/file-card.tsx`
  (props are primitive `{fileId, name, ...}` by design) and
  `features/files/api/request-file-upload.ts` / `confirm-file-upload.ts`;
  upload plumbing `src/lib/api/direct-upload.ts:5`.

### Will exist after sibling plans (verify at pre-flight)

`models/files.py` `File` (contract category, `content_type`, `size_bytes`,
`processing_status`, soft-delete), `FileReference(target_type=
"conversation", ...)` (031); `services/files/` upload/confirm/read ops and
the blob-read seam over `services/storage` (032); 035's card + upload API
files.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Backend lint | `cd apps/api && uv run ruff check .` | exit 0 |
| Backend tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/conversations tests/services/agents/runtime tests/services/files -q` | all pass |
| Re-probe | the probe snippet above | matches recorded facts |
| Frontend gate | `cd apps/web && pnpm check` | exit 0, zero warnings |
| Regression | `cd apps/api && uv run pytest tests/services/agents tests/routes -q` | all pass |

## Scope

**In scope (backend):**

- `apps/api/core/settings/files.py` (extend — `MAX_CHAT_ATTACHMENTS`,
  `MAX_MULTIMODAL_DOCUMENT_BYTES`)
- `apps/api/services/files/resolve_chat_attachments.py` (create) and
  `apps/api/services/files/build_attachment_user_content.py` (create) —
  one operation per file, per AGENTS.md
- `apps/api/services/conversations/schemas.py` (extend both request
  models), `create_turn_stream.py`, `create_conversation_stream.py`,
  `utils.py` (`build_interactive_run_metadata` gains attachment ids)
- `apps/api/services/agents/runtime/worker.py` (thread the ids),
  `execute_run.py` (widen `user_prompt`, assemble content)
- `apps/api/tests/services/files/` (attachment ops),
  `tests/services/conversations/` (send-path validation),
  `tests/services/agents/runtime/` (content assembly + persistence
  round-trip)

**In scope (frontend):**

- `apps/web/src/features/conversations/types.ts` (payload types),
  `components/conversation-composer.tsx` (attach control + chips),
  `message-parts/types.ts` + `parse.ts` (attachments on parsed messages),
  `components/message-row.tsx` (render attachment chips),
  `attachments.ts` (create — feature-local upload orchestration +
  part guards)
- If 035 has not landed: minimal `features/files/types.ts` +
  `api/request-file-upload.ts` + `api/confirm-file-upload.ts` +
  `components/file-card.tsx` (created here exactly as 035 specifies, so
  035 adopts rather than duplicates them)

**Out of scope (do NOT touch):**

- New SSE event names, `stream/protocol.ts`, `stream/sse.ts` (decision 7).
- `runtime/persistence.py` (decision 4 — pin with a test instead).
- Attachments for schedules and delegation (decision 8), audio/video
  content types, `UploadedFile`/`CachePoint`, provider `vendor_metadata`.
- Model-catalog schema changes — `supports_vision` already exists.
- Paste-image-from-clipboard and drag-drop (follow-up polish; the file
  picker ships first).
- 033's markdown pipeline — raw bytes go to the model here; markdown is
  `read_file`'s business (034).

## Git workflow

- Branch: `advisor/036-multimodal-input`
- Commit style: backend commit `API - Multimodal Chat Attachments`,
  frontend commit `Web - Chat Attachment Composer & Rendering`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

Extend `FilesSettingsMixin` (`core/settings/files.py`):

```python
MAX_CHAT_ATTACHMENTS: int = Field(default=5, ge=1, le=20,
    description="Max file attachments per chat message")
MAX_MULTIMODAL_DOCUMENT_BYTES: int = Field(default=20971520, ge=1048576, le=33554432,
    description="Max document size passed to the model as multimodal input (20MB)")
```

Image size reuses `MAX_FILE_SIZE_IMAGE` (73-78) — do not add a second
image cap.

**Verify**: settings import prints both values; ruff exit 0.

### Step 2: Attachment service operations

`services/files/resolve_chat_attachments.py`:

```python
async def resolve_chat_attachments(
    db, *, workspace_id: UUID, agent: Agent, file_ids: Sequence[UUID],
) -> list[File]:
```

Dedupes ids preserving order; enforces `MAX_CHAT_ATTACHMENTS`; loads
`File` rows scoped to `workspace_id` and not deleted (a foreign or
missing id → `NotFoundError` naming the id); per decision 3 validates
contract category ∈ {image, ingestible-document, editable-text}, media
type against the probed pydantic-ai sets (declare the two frozensets in
this module with a comment tying them to the probe — they gate what we
*send*, independent of 031's broader upload contract), size against the
right cap, and — for images — `get_model(*resolve_agent_model(agent))
.supports_vision`, raising `AppValidationError` with the model's display
name when false. All failures are typed `core/exceptions` types; no
HTTPException.

`services/files/build_attachment_user_content.py`:

```python
async def build_attachment_user_content(db, *, files: Sequence[File]) -> list[BinaryContent]:
```

Reads each file's current-revision blob through 032's read seam (the
storage provider, `services/storage/provider.py:31` `get_object`) and
returns `BinaryContent(data=blob, media_type=file.content_type,
identifier=str(file.id))` per file, in order. No validation here — it
runs post-commit inside the run and trusts Step 2's resolver.

Also ensure a `FileReference` creation op exists for
`target_type="conversation"` (032/031 likely ship
`create_file_reference`; if so, reuse it — idempotent on
file×conversation, e.g. `ON CONFLICT DO NOTHING` against its uniqueness).

**Verify**: ruff; unit tests in Step 5.

### Step 3: Send-path plumbing

1. `services/conversations/schemas.py` — both request models gain
   `attachments: list[UUID] = Field(default_factory=list)` with a
   validator deduping while preserving order (length is enforced by the
   resolver so the error is a problem+json 422 either way; keep the
   schema permissive and the resolver authoritative).
2. `create_turn_stream.py` / `create_conversation_stream.py` — after the
   existing conversation/run guards and **before** creating the run:
   `files = await resolve_chat_attachments(db, workspace_id=workspace.id,
   agent=<active agent>, file_ids=payload.attachments)` (the agent row is
   already loaded in both paths); create the conversation-scoped
   `FileReference` rows; include `attachment_file_ids` in
   `build_interactive_run_metadata` (`utils.py`) so the run row records
   provenance; commit as today; pass `attachment_file_ids=[f.id for f in
   files]` to `run_turn_worker`. Validation failures happen pre-commit in
   the request → the client gets a 422 and **no run is created**.
3. `runtime/worker.py` — `run_turn_worker` gains
   `attachment_file_ids: Sequence[UUID] = ()` and forwards to
   `execute_run`. The resume worker path (118) is untouched
   (decision 6).

**Verify**: `uv run pytest tests/services/conversations -q` (existing
suite green — no-attachment requests behave identically);
`uv run ruff check .`.

### Step 4: Runtime content assembly

`runtime/execute_run.py`:

1. Widen the signature: `user_prompt: str | Sequence[UserContent] | None`
   and add `attachment_file_ids: Sequence[UUID] = ()` (import
   `UserContent` from `pydantic_ai.messages`).
2. After `load_actor_context` (and before `run_stream_events`), when
   `attachment_file_ids` is non-empty: load the `File` rows
   (workspace-scoped re-check — the worker session is new), call
   `build_attachment_user_content`, and set
   `user_prompt = [user_prompt, *binary_contents]` (text first). A
   missing/deleted file at this point (deleted between send and
   execution) raises — becoming an ordinary `persist_failed_run` with a
   clear `error_code`, which the existing failure path already streams
   (316-345).
3. `run_stream_events(user_prompt, ...)` (201-208) needs no other change
   — probed signature accepts the sequence. `new_messages()` persistence
   picks the multimodal user prompt up automatically (decision 4).

**Verify**: targeted test (Step 5) proves a run through pydantic-ai's
test/function model receives `UserPromptPart.content` as a list with one
`BinaryContent`; the no-attachment path passes the plain string exactly as
before (assert identity, pinning risk note in Status).

### Step 5: Backend tests

Async modules set `pytestmark = pytest.mark.asyncio`; DB-backed tests use
`conftest.py` fixtures + `tests/factories/` and skip without
`TEST_DATABASE_URL`; live LLM calls are blocked — runtime tests drive
`execute_run` with the stubbed model the existing
`tests/services/agents/runtime/test_runtime_core.py` uses.

- `tests/services/files/test_resolve_chat_attachments.py`: happy path per
  category; over-count; over-size per cap; unsupported media type;
  foreign-workspace id → `NotFoundError`; deleted file rejected; image +
  non-vision catalog entry → `AppValidationError` naming the model
  (add a non-vision entry via monkeypatched catalog — every real entry
  currently supports vision); duplicate ids collapse.
- `tests/services/files/test_build_attachment_user_content.py`: returns
  ordered `BinaryContent` with `identifier == str(file.id)` and the
  file's media type; storage read errors propagate.
- `tests/services/conversations/test_chat_attachments.py`: turn request
  with attachments creates conversation-scoped `FileReference` rows
  (idempotent on resend of the same file), records ids in run metadata,
  and rejects invalid attachments with 422 problem+json **without
  creating a run**; empty `attachments` behaves exactly as before
  (compare against a no-field request).
- `tests/services/agents/runtime/test_multimodal_prompt.py`: `execute_run`
  with `attachment_file_ids` produces a persisted user message whose
  parts round-trip through `load_message_history` with `BinaryContent`
  intact (decision 4 pinned); the resume path replays it without
  re-reading storage; text-only runs pass an unmodified `str`.

**Verify**: the Commands-table test line passes; without
`TEST_DATABASE_URL` the DB tests skip.

### Step 6: Frontend payloads and upload orchestration

1. `features/conversations/types.ts` — both request types gain
   `attachments?: string[]`.
2. `features/conversations/attachments.ts` (create) — the feature-local
   seam: `MessageAttachment` type (`fileId`, `name`, `mediaType`,
   `sizeBytes`), `isBinaryUserContentPart(item)` guard for parse.ts
   (`kind === "binary"`, reads `media_type` + `identifier`, **never**
   `data`), and `uploadChatAttachment(file): Promise<MessageAttachment>`
   composing 035's `requestFileUpload` → `uploadFileDirectly` →
   `confirmFileUpload`. If 035 is absent, create those two API operation
   files + `features/files/types.ts` exactly per 035 Step 1/2 (pre-flight
   note) so 035 adopts them.
3. All requests remain inside `apiRequest`/`uploadFileDirectly` — no raw
   `fetch` in features (lint/manual grep).

**Verify**: `pnpm typecheck` clean; `grep -rn "fetch(" src/features/conversations`
→ nothing new.

### Step 7: Composer attach control

`conversation-composer.tsx`:

- Paperclip `Button` (ghost, in the action row next to Send) triggering a
  hidden `<input type="file" multiple>`; an `accept` hint built from the
  image + document media types (server remains authoritative).
- Selected files upload immediately via `uploadChatAttachment` with a
  per-chip busy state; failures render in the existing `Alert` and drop
  the chip. Chips (name, size, remove ×) render above the textarea; cap
  client-side at `5` with a friendly message (mirror of
  `MAX_CHAT_ATTACHMENTS` — a mismatch only means a server 422, which the
  composer already displays).
- Send: include `attachments: attachmentIds` in both `sendFirstMessage`
  and `sendTurn` payloads; disable Send while any upload is in flight;
  allow attachments-with-text only (prompt stays required — matches the
  backend's unchanged `user_prompt` min length). On send-failure restore
  chips along with the prompt text (the existing 106-110 error path).
- `PendingUserMessage` (`message-parts/types.ts:57-62`) gains
  `attachments?: MessageAttachment[]` so the optimistic bubble shows
  chips instantly; `pending-messages.ts` threads it through.

**Verify**: manual — attach two images, send; chips show on the pending
bubble; a failed upload never blocks sending without it.

### Step 8: Rendering persisted attachments

1. `message-parts/parse.ts` — in the `user-prompt` branch (147-155):
   when `part["content"]` is an array, split items — strings/text items
   feed the existing text extraction; items passing
   `isBinaryUserContentPart` become `attachments` entries
   (`fileId: identifier`, `mediaType: media_type`, name unknown →
   `null`); binary items must not reach `extractContentText` or the
   unsupported-part preview (no base64 in the DOM, ever). Unknown item
   kinds keep the current unsupported-part fallback.
2. `message-parts/types.ts` — `ParsedConversationMessage.attachments:
   ParsedAttachment[]` (default `[]`).
3. `message-row.tsx` — user messages render attachment chips under the
   text: 035's `FileCard` fed `{fileId, name: name ?? mediaType}` (its
   props are primitive by design), giving Open/Download via the signed-URL
   flow. Pending bubbles reuse the same chip from
   `PendingUserMessage.attachments` (which does know the name).

**Verify**: after a multimodal turn, reloading the conversation shows the
user message with chips (from persisted parts) and the chips' Open action
works; a pre-existing text-only conversation renders unchanged.

### Step 9: Gate + manual matrix

`cd apps/web && pnpm check` and `cd apps/api && uv run ruff check . &&
uv run pytest tests/services -q` — then the manual matrix in "Test plan"
against a local API with a vision-capable model configured.

## Test plan

Backend coverage is Step 5 (~16–20 tests). Pinned invariants: **the
no-attachment path is unchanged** (plain `str` all the way through, same
persisted shape), **validation is pre-run** (bad attachments → 422, no
run row, no FileReference), **multimodal history round-trips** (send →
persist → reload → resume without storage access), and **workspace
isolation** (foreign file ids unresolvable).

Manual matrix (frontend has no test framework): image attach + "what is
in this image" answered by a vision model; PDF attach + content question;
attachment visible in 034's `<available_files>` on the *next* turn and
readable via `read_file`; chips after reload; send failure restores
chips; 5-attachment cap message; non-image+non-document file rejected
with the server's problem detail; stale client (built before this plan)
still parses a multimodal conversation's stream — it must, since no event
names changed (decision 7); the file appears on 035's `/files` page.

## Done criteria

- [ ] `uv run ruff check .` exits 0; no migration needed (this plan adds
      no tables — assert `uv run alembic check` is clean)
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/files tests/services/conversations tests/services/agents/runtime -q` exits 0
- [ ] `pnpm check` exits 0 from `apps/web`
- [ ] Re-probe output matches the recorded pydantic-ai facts (attach the
      output to the completion report)
- [ ] `stream/protocol.ts` and `stream/sse.ts` untouched
      (`git diff --stat` shows no changes there)
- [ ] `runtime/persistence.py` untouched; the round-trip test passes
- [ ] Base64 never rendered: `parse.ts` drops `data` fields before
      anything reaches components (code-review check)
- [ ] Manual matrix completed and reported (state which rows ran with
      034/035 present vs created-minimal)
- [ ] `docs/plans/000_README.md` status row updated (add the 036 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- The sibling pre-flight fails: 031/032 not implemented, `FileReference`
  lacks `target_type="conversation"`, or 032 exposes no blob-read seam
  usable from the runtime.
- **The re-probe mismatches the recorded facts** — `run_stream_events`
  rejecting `Sequence[UserContent]`, `BinaryContent`/`identifier` field
  changes, or the `ModelMessagesTypeAdapter` round-trip dropping bytes or
  identifiers. Reconcile the design before coding, not after.
- You feel the need to add an SSE event name (e.g. `message.attachment`)
  — the client-first protocol rule applies (000_README precedent);
  decision 7 says this plan must not need it.
- `execute_run`'s prompt hand-off or the persistence dump/load moved from
  the "Current state" anchors (something reshaped the runtime first).
- The conversations request schemas gained conflicting fields (another
  plan extended the send path in parallel).
- Persisted multimodal history breaks resume in testing (the decision-4
  bet failing) — that forces the storage-backed rehydration alternative,
  which is a design change, not a patch.
- Existing `tests/services/conversations` or runtime tests fail before
  your changes.

## Maintenance notes

- **Plan 013 (history trimming) interaction**: multimodal user parts are
  the heaviest history items. Plan 013 is now turn-boundary based and must not
  split a text+attachment user prompt; byte-aware trimming or storage-backed
  rehydration remains a future pressure valve for this plan family.
- **The base64-in-history cost is a recorded tradeoff** (decision 4). If
  workspaces hit real bloat, the escape hatch is storage-backed
  rehydration: persist a placeholder keyed by `identifier` and re-read
  blobs at `load_message_history` time — a contained change inside
  `persistence.py` because `identifier` already carries the file id.
- **Provider document support varies** beneath the uniform
  `DocumentMediaType` set; a provider rejecting a docx surfaces as a
  failed run with the provider's error. If that gets noisy, add a
  per-provider allowed-media-type map next to `supports_vision` in the
  catalog — data, not code branches.
- **Scheduled/delegated attachments** (decision 8) ride the same
  `FileReference` targets when someone needs them; the runtime assembly
  seam built here (`attachment_file_ids` on `execute_run`) is already
  principal-agnostic.
- Reviewers should scrutinize: FileReference idempotency under message
  retries (`client_message_id` conflicts), the 422-before-run guarantee
  (no orphaned runs from bad attachments), that run metadata records ids
  (not content), and that the composer cannot send while an upload is
  mid-flight (double-submit protection interacting with the existing
  stream-blocking logic at `conversation-composer.tsx:54-66`).
