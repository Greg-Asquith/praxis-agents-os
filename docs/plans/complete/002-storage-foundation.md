# Plan 002: Implement The Backend Storage Foundation

> **Executor instructions**: Follow this plan step by step. Keep this slice
> focused on provider-neutral object storage. Do not build the full user-facing
> file library, search/enrichment pipeline, or agent skill file tools in this
> plan. When done, update the status row for this plan in `docs/plans/000_README.md`.
>
> **Retrospective note**: This plan was written after implementation had already
> started. Treat it as the recorded execution plan for the storage foundation
> slice, not as a claim that planning happened before coding.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- apps/api/services/storage apps/api/routes/storage apps/api/middleware/body_size.py apps/api/routes/__init__.py apps/api/tests/services/storage apps/api/tests/routes/storage apps/api/tests/contract/test_openapi_routes.py`
>
> If any in-scope file changed outside this storage slice, compare the plan below
> against the live code before proceeding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: agent runtime foundation through `docs/architecture/agent-runtime.md`
- **Category**: foundation
- **Planned at**: retrospective during implementation, 2026-07-01
- **Status**: DONE

## Why This Matters

Agents need durable file I/O before skills, delegation, generated artifacts,
workspace icons, and user avatars can be wired cleanly. The backend already has
provider selection settings (`STORAGE_PROVIDER`, `LOCAL_STORAGE_ROOT`, public
asset settings, and cloud bucket placeholders), but no storage service package.

The old reference system split storage and files, but the boundary became messy:
provider adapters, upload routes, DB file records, revisions, tags, enrichment,
and public access policy were intertwined. This repo should start with a smaller
foundation:

- object refs and provider contracts,
- local filesystem provider for development,
- signed local upload/download capabilities that mirror cloud signed URLs,
- explicit stubs for cloud providers until their SDK-backed adapters are added,
- tests around path safety and signed capabilities.

Authenticated file records, agent-facing filesystem tools, icon/avatar upload
flows, metadata tables, content extraction, and search should be separate follow-up
work.

## Pydantic AI And Harness Constraints

The storage layer should be easy to expose to Pydantic AI tools later:

- Keep provider operations async and typed.
- Use Pydantic models for object refs and operation results so future tool returns
  are machine-consumable.
- Put common, safe file-read/list/write tools behind normal Pydantic AI tools
  first.
- Consider `pydantic-ai-harness` Code Mode only after there is a concrete toolset
  where safe file operations benefit from batching, loops, or `asyncio.gather`.
- Do not put approval-required, deferred, or high-risk external-system actions
  behind Code Mode.

## Target Shape

Add a backend package under `apps/api/services/storage`:

```text
services/storage/
  domain.py              # StorageBucket, StorageObjectRef, StoredObject, signed URL models
  provider.py            # StorageProvider protocol
  factory.py             # settings-driven provider singleton
  errors.py              # structured storage exceptions
  paths.py               # object-key validation and HTTP header helpers
  providers/
    local.py             # local_fs provider
    unavailable.py       # explicit pending cloud-provider adapter
```

Add provider-neutral storage HTTP routes under `apps/api/routes/storage`:

```text
routes/storage/
  public_object.py       # GET /storage/public/{object_key:path}
  private_object.py      # GET /storage/private/{object_key:path}
  upload_object.py       # PUT /storage/upload/{bucket}/{object_key:path}
```

These are low-level storage capability routes. They stay provider-neutral at the
HTTP layer; storage service operations resolve the active provider and use the
local adapter only when local signed URLs need an API target. Do not add
authenticated "create upload for avatar" or "attach file to run" routes in this
plan.

## Implementation Steps

1. Add storage domain contracts:
   - `StorageBucket` with `public` and `private`.
   - `StorageObjectRef` with strict relative object-key validation.
   - `StoredObject`, `SignedUpload`, and `SignedDownload`.

2. Add structured storage errors:
   - validation error: 400,
   - invalid/expired signature: 403,
   - object not found: 404,
   - unavailable configured provider: 501.

3. Add local filesystem provider:
   - store objects below `{LOCAL_STORAGE_ROOT}/public` and `/private`,
   - use sidecar metadata for content type, cache control, etag, and app metadata,
   - guard against absolute paths, `..`, empty path segments, backslashes, and
     control characters,
   - provide HMAC-signed upload and private download URLs.

4. Add provider factory:
   - `local_fs` returns the local provider,
   - `gcs`, `s3`, and `azure_blob` return explicit unavailable providers for now,
   - do not silently fall back to local storage.

5. Add local provider HTTP routes:
   - public object GET,
   - signed private object GET,
   - signed upload PUT.

6. Update middleware route limits:
   - allow `/api/v1/storage/upload` to exceed the default request body limit
     up to the largest configured storage file limit.

7. Add focused tests:
   - local put/get/stat/delete,
   - public URL generation,
   - signed upload signature binding,
   - object-key traversal rejection,
   - ASGI route coverage for signed upload/download and public serving,
   - OpenAPI route registration.

## STOP Conditions

- A requirement appears to persist file metadata in the database. Stop and write a
  separate `files` package/database plan instead of folding it into provider
  storage.
- A cloud provider must work end to end in this slice. Stop and plan the SDK,
  credentials, signed URL, and bucket/container behavior per provider.
- A route would need to loosen auth, CORS, CSRF, cookie, or provider validation.
  Stop and design an explicit local-only path instead.
- Agent skills need a workspace filesystem abstraction immediately. Stop and
  design the agent-facing tool API on top of this storage package rather than
  embedding agent semantics inside the provider.

## Verification

Run from `apps/api`:

```bash
uv run pytest tests/services/storage/test_local_provider.py \
  tests/routes/storage/test_local_storage_routes.py \
  tests/contract/test_openapi_routes.py

uv run ruff check services/storage routes/storage \
  tests/services/storage tests/routes/storage \
  tests/contract/test_openapi_routes.py middleware/body_size.py routes/__init__.py
```

Expected result: tests pass and Ruff exits 0.

## Follow-Up Work

- Add an authenticated `services/files` package for durable file records,
  ownership, upload grants, and attachment to users, workspaces, conversations,
  and agent runs.
- Add user avatar and workspace icon upload/confirm flows that use this storage
  provider package.
- Add agent-facing file tools on top of file records and scoped storage refs.
- Add real GCS/S3/Azure adapters.
- Consider Code Mode only for safe, local, high-volume file toolsets after the
  normal Pydantic AI tool surface exists.
