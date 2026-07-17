# Plan 081 — Agent File Inspection Reliability

**Status:** DONE (2026-07-17)  
**Priority:** P1  
**Effort:** M  
**Depends on:** 034, 036  
**Added:** 2026-07-17

## Objective

Make an agent's `read_file` call content-first and truthful. When Praxis can
resolve an image or extracted document, the model receives that content in the
next request. A signed URL remains an explicit user-download or unsupported-
content fallback and is never presented as a way for the model to inspect an
otherwise unreadable file.

This is one focused Phase 3 reliability slice. It does not add file types,
routes, provider capabilities, UI, or a new SSE event.

## Current-state finding

The existing image branch returns:

```python
ToolReturn(
    return_value=metadata,
    content=[BinaryContent(...)],
    metadata={...},
)
```

Installed `pydantic-ai==2.1.0` defines `ToolReturn.content` as a separate
`UserPromptPart`. Its own API guidance says multimodal content that belongs to
the tool result should instead be returned directly or included in
`return_value`. The OpenAI Responses, Anthropic, and Google serializers in the
installed package all have explicit multimodal `ToolReturnPart` mapping.

The current tool description also gives `content` and `url` equal billing, and
the non-vision retry says to use URL mode. That can lead a model to fetch a
signed link, fail because provider backends cannot reach local storage (or the
link is only a download), and then falsely claim that Praxis could not inspect
the image even though the content branch was available.

## Decisions taken

1. **Native multimodal tool result.** Image content mode returns a
   `ToolReturn` whose `return_value` is `[metadata, BinaryContent]`. This gives
   each provider serializer a real multimodal `ToolReturnPart`, not a detached
   user message. Application metadata remains in `ToolReturn.metadata`.
2. **Keep transport bytes out of SSE.** The runtime event translator emits the
   public metadata mapping for a rich file result instead of serializing the
   `BinaryContent`. The existing versioned `tool_result` event and frontend
   result contract therefore remain unchanged. Persisted transcripts retain
   the native bytes for future model turns; the frontend result parser unwraps
   the metadata-first rich result so reloaded tool rows keep rendering.
3. **Content is the agent default.** The tool description and available-files
   prompt tell the model to call content mode for inspection. URL mode is only
   for an explicit user download or a file category that has no content
   reader.
4. **Truthful failure language.** A model without vision receives a retry that
   states image inspection is unsupported by the configured model and that a
   URL is only useful if the user requested a download. Unknown/unsupported
   file categories use the same distinction. Processing-state guidance keeps
   recommending retry for agent inspection and URL only for user download.
5. **Documents stay extracted-text-first.** Ready ingestible documents return
   bounded extracted markdown exactly as today. Tests pin that the tool result
   entering the next model request contains that markdown, rather than a URL.
6. **URL results retain the file snapshot.** Explicit download results include
   `category`, `media_type`, and `processing_status` (plus revision identity),
   matching the stable metadata already returned by content reads. The
   frontend propagates those fields into its existing file entity so a ready
   image uses the normal thumbnail path instead of a generic file icon.
7. **Provider verification is deterministic and offline.** Runtime tests drive
   a `FunctionModel` through a real tool call and inspect its second request.
   Serializer-level tests construct the native rich result and verify the
   installed OpenAI, Anthropic, and Google mappings preserve image content.
   No live provider calls or credentials are used.
8. **No harness capability or new frontend surface.** Core Pydantic AI rich
   tool returns solve this directly. `pydantic-ai-harness` would add no
   relevant boundary. The React change is limited to parsing the persisted
   metadata-first rich result; there is no new UI, request, state, or event.

## Implementation

1. Update `read_file` and its shared guidance:
   - make the registry description content-first;
   - place image `BinaryContent` in `ToolReturn.return_value` beside metadata;
   - use explicit success/fallback language;
   - reserve signed URLs for user download and unsupported-content fallback;
   - include the common file snapshot in explicit URL results.
2. Add one small runtime event helper that converts rich tool-return content to
   its public metadata mapping while leaving all ordinary tool results intact.
3. Teach the existing frontend file-result parser to unwrap the metadata entry
   from a persisted rich result and retain URL-result image metadata,
   preserving the current tool-row and thumbnail presentation.
4. Extend focused tests to cover:
   - image bytes in a native `ToolReturnPart` and metadata-only SSE output;
   - ready-document markdown in the model's post-tool request;
   - OpenAI, Anthropic, and Google serializer preservation of image content;
   - exact non-vision and unsupported-category URL-only failure behavior;
   - URL mode still creates a signed download with thumbnail metadata when
     explicitly requested.
5. Update the roadmap narrative and status row, then move this document to
   `docs/plans/complete/` only after all done criteria pass.

## Done criteria

- [x] Image content mode reaches the next model request as native
      `BinaryContent` inside the `read_file` tool return.
- [x] Ready document content mode reaches the next model request as bounded
      extracted markdown.
- [x] Deterministic tests cover OpenAI, Anthropic, and Google rich-result
      serialization without network calls.
- [x] SSE `tool_result.result` for an image remains metadata-only; no image
      bytes or data URI enter the stream payload.
- [x] Non-vision and unsupported-category errors distinguish inability to
      inspect from the user's ability to download.
- [x] Explicit URL mode still returns a short-lived signed download.
- [x] URL-mode image results carry the file snapshot and render through the
      existing ready-image thumbnail path.
- [x] No route, SSE event name, schema, migration, setting, or new frontend
      surface; reloaded rich results preserve the existing image file row.
- [x] Focused runtime/web tests, backend Ruff lint/format, full
      database-backed backend suite, and the frontend gate pass.
- [x] `docs/plans/000_MASTER_ROADMAP.md` and `docs/plans/000_README.md` mark
      081 done, and this plan lives under `docs/plans/complete/`.

## STOP conditions

Stop and report rather than improvise if:

- the installed Pydantic AI contract no longer maps multimodal content in
  `ToolReturn.return_value` for any supported provider;
- preserving native tool-result bytes requires changing an SSE event name or
  exposing those bytes to the browser;
- the existing provider catalog no longer supplies an authoritative vision
  capability flag;
- baseline focused runtime/file tests fail before implementation;
- completing the fix requires a new file category, storage contract, route,
  migration, or provider-specific live API behavior.

## Verification

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test \
  uv run pytest tests/services/agents/runtime -q
uv run ruff check .
uv run ruff format --check .
cd ../..
make api-test
cd apps/web
pnpm check
```

**Planned at:** current worktree, 2026-07-17
