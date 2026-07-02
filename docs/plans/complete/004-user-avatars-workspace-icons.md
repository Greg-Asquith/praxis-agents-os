# Plan 004: Wire User Avatars And Workspace Icons To Provider-Neutral Storage

> **Executor instructions**: Follow this plan step by step. This slice wires the
> first two user-facing storage use cases on top of the provider-neutral storage
> package from Plan 002: authenticated user avatars and workspace icons. Do not
> implement the broader file library, agent file tools, image-processing
> pipeline, or provider-specific cloud SDK behavior in this plan. When done,
> update the status row for this plan in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 3901cb8..HEAD -- apps/api/models apps/api/alembic/versions/core apps/api/core/settings apps/api/services/storage apps/api/services/auth apps/api/services/users apps/api/services/workspaces apps/api/routes/auth apps/api/routes/workspaces apps/api/tests apps/api/.env.example apps/web/src/components/shell apps/web/src/features/auth apps/web/src/features/workspaces apps/web/src/lib docs/plans`
>
> If any in-scope file changed since this plan was written, compare the "Current
> State" excerpts below against the live code before proceeding. If the storage
> provider contract changed, treat that as a STOP condition until the plan is
> refreshed.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: Plan 002 backend storage foundation
- **Compatible with**: Plan 003 cloud providers; this plan must not import cloud SDKs
- **Category**: feature
- **Planned at**: commit `3901cb8`, 2026-07-01
- **Status**: DONE

## Why This Matters

The repo already has URL fields for user avatars and workspace icons, and the UI
currently exposes raw URL inputs. That is not the target storage shape: user and
workspace assets should be uploaded through the active `StorageProvider`, owned by
the relevant user/workspace, validated by the API, and then surfaced as stable
public URLs.

This plan adds the smallest application layer above storage: short-lived upload
grants, direct browser uploads, confirm/delete operations, durable object-key
columns, audit events, and UI controls. It stays provider agnostic by depending
only on `StorageProvider.create_signed_upload`, `stat_object`, `delete_object`,
and `public_url`.

## Current State

Relevant storage facts:

- `apps/api/services/storage/domain.py:15-64` defines `StorageBucket.PUBLIC`,
  `StorageObjectRef`, `StoredObject.public_url`, and `SignedUpload`.
- `apps/api/services/storage/provider.py:43-64` exposes
  `create_signed_upload`, `create_signed_download`, and `public_url` on the
  provider protocol.
- `apps/api/services/storage/paths.py:100-105` already has
  `unique_object_key(prefix, filename)` for random object names under validated
  prefixes.
- `apps/api/routes/storage/upload_object.py:16-36` accepts signed local uploads.
  Cloud providers in Plan 003 upload directly to the provider URL instead.
- `apps/api/services/storage/factory.py:20-39` selects a singleton provider from
  `settings.STORAGE_PROVIDER`. Application code should call the factory, not
  branch on provider keys.

Relevant model/API facts:

- `apps/api/models/user.py:52-55` has `avatar_url` but no owned object key.
- `apps/api/models/workspace.py:43-46` has `icon_url` but no owned object key.
- `apps/api/services/auth/schemas.py:122-132`,
  `apps/api/services/users/schemas.py:41-74`, and
  `apps/api/services/workspaces/schemas.py:50-75` currently accept raw
  `avatar_url`/`icon_url` strings in mutation requests.
- `apps/api/services/auth/update_current_user.py:21-38`,
  `apps/api/services/users/update_user.py:30-35`, and
  `apps/api/services/workspaces/update_workspace.py:48-50` write those raw URL
  fields directly.
- `apps/api/services/workspaces/utils.py:24-33` defines `MANAGER_ROLES`; use it
  for workspace icon writes.
- `apps/api/services/auth/oauth/utils.py:137-176` already uses short-lived HS256
  JWTs signed with `settings.SECRET_KEY`. Reuse this pattern for upload-confirm
  tokens instead of adding a database upload-grant table.

Relevant settings/UI facts:

- `apps/api/core/settings/files.py:37-48` defines avatar/icon file-size limits.
- `apps/api/core/settings/files.py:75-81` defines allowed image/icon MIME types.
  `ALLOWED_ICON_TYPES` currently includes `image/svg+xml`.
- `apps/web/src/features/auth/components/profile-form.tsx:90-98` renders an
  "Avatar URL" text input.
- `apps/web/src/features/workspaces/components/workspace-settings-form.tsx:108-116`
  renders an "Icon URL" text input.
- `apps/web/src/components/shell/app-shell.tsx:109-112` already displays
  `user.avatar_url` through the shared avatar primitive.

## Target Shape

Add a small provider-neutral asset layer:

```text
apps/api/services/assets/
  __init__.py
  domain.py                    # AssetKind, upload/confirm request/response models
  tokens.py                    # create/verify short-lived asset upload JWTs
  utils.py                     # content-type, size, key, and cleanup helpers
  create_user_avatar_upload.py
  confirm_user_avatar_upload.py
  delete_user_avatar.py
  create_workspace_icon_upload.py
  confirm_workspace_icon_upload.py
  delete_workspace_icon.py
```

Use public storage object keys:

```text
users/{user_id}/avatar/{uuid}{ext}
workspaces/{workspace_id}/icon/{uuid}{ext}
```

Persist provider-neutral object keys separately from public URLs:

```text
users.avatar_object_key nullable string
workspaces.icon_object_key nullable string
```

Keep `users.avatar_url` and `workspaces.icon_url` as read projections used by the
frontend. Existing external OAuth avatar URLs can remain as `avatar_url` with
`avatar_object_key = NULL`. New user-uploaded avatars and workspace icons must
set both the object key and the public URL from the active storage provider.

Add authenticated API routes:

```text
POST   /api/v1/auth/me/avatar/upload
POST   /api/v1/auth/me/avatar/confirm
DELETE /api/v1/auth/me/avatar

POST   /api/v1/workspaces/{workspace_id}/icon/upload
POST   /api/v1/workspaces/{workspace_id}/icon/confirm
DELETE /api/v1/workspaces/{workspace_id}/icon
```

The upload route returns an application grant plus the provider's signed upload:

```json
{
  "upload": {
    "ref": {"bucket": "public", "key": "users/<id>/avatar/<uuid>.png"},
    "url": "https://...",
    "method": "PUT",
    "headers": {"content-type": "image/png"},
    "expires_at": "..."
  },
  "upload_token": "<api-signed-token>",
  "max_size_bytes": 5242880,
  "expires_at": "..."
}
```

The client uploads the selected file bytes directly to `upload.url` with
`upload.method` and exactly `upload.headers`, then calls the confirm route with
`upload_token`.

## Provider-Agnostic Rules

- Do not import or branch on GCS, S3, or Azure classes anywhere in this plan.
- Do not change the `StorageProvider` protocol for this slice. Size enforcement
  happens before upload from the declared browser file size and after upload by
  `stat_object`.
- Use `StorageBucket.PUBLIC` for avatars and icons.
- Use `unique_object_key()` for object names. Never use original filenames as
  stable object names.
- Confirm routes must call `stat_object(ref)` and reject if the object is absent,
  content type is not allowed, or `size_bytes` exceeds the relevant setting.
- Confirm routes must set public URLs from `stored.public_url` or
  `provider.public_url(ref)`. Never reconstruct a URL from bucket names.
- If confirm rejects an uploaded object, make a best-effort `delete_object(ref)`
  call before returning the validation error.
- If replacing or deleting an existing managed object, delete the old object key
  best-effort after the database mutation succeeds. Do not delete external OAuth
  avatar URLs where `avatar_object_key` is null.
- Do not store private originals in this slice. Processing/cropping/thumbnails are
  deferred.

## Security And Validation Rules

- Upload-confirm JWT payloads must bind:
  - token type, for example `asset_upload`;
  - asset kind: `user_avatar` or `workspace_icon`;
  - actor user id;
  - target user id or workspace id;
  - storage bucket and object key;
  - expected content type;
  - maximum size bytes;
  - `jti`, `iat`, and `exp`.
- Token TTL should be short, 10 minutes unless there is a strong reason to choose
  otherwise.
- User avatar confirm/delete must require the authenticated user id to match the
  target user id in the token.
- Workspace icon upload/confirm/delete must call `require_workspace_role(...,
  allowed_roles=MANAGER_ROLES)` for the target workspace.
- Avatar uploads must use `ALLOWED_IMAGE_TYPES` and `MAX_FILE_SIZE_AVATAR`.
- Workspace icon uploads must use raster image types only in this slice:
  `image/jpeg`, `image/png`, and `image/webp`.
- Update `ALLOWED_ICON_TYPES` and `apps/api/.env.example` to remove
  `image/svg+xml`, or explicitly filter SVG out in `services/assets/utils.py`.
  Preferred path: remove SVG from the default because there is no sanitizer yet.
- Do not add SVG support unless this same plan also adds a sanitizer and security
  tests. Otherwise defer SVG support to a separate plan.
- Never trust browser-declared size alone. Use it to avoid granting obviously bad
  uploads, then verify the stored object size during confirm.
- Do not proxy cloud uploads through the API to work around CORS. Cloud bucket CORS
  configuration belongs to Plan 003 infrastructure documentation.

## Known Limitations And Accepted Risks

These are deliberate boundaries for this slice. Do not treat them as bugs to fix
here; name them so nobody assumes they are already solved.

- **Upload size cannot be enforced at the signed URL.** A presigned/SAS `PUT`
  does not cap request content-length, so an authenticated user can upload an
  arbitrarily large object to a small-limit avatar/icon URL. The only enforcement
  in this slice is post-upload: confirm calls `stat_object`, rejects when
  `size_bytes` exceeds the limit, and best-effort deletes the object. This means
  the provider may transiently store an oversize object before rejection. Accepted
  for now. The real fix (out of scope) is a size-bounded grant, e.g. an S3
  presigned `POST` with a `content-length-range` condition, or the GCS/Azure
  equivalent.
- **Content type is declared, not sniffed.** `stat_object` returns the
  content-type the client bound into the signed upload header, not a value derived
  from the object bytes. Confirm validates that declared type against the allowed
  set, but a client can upload arbitrary bytes under an allowed image content
  type. This is low-risk for `<img>`-rendered avatars/icons, but magic-byte and
  perceptual validation are explicitly deferred to a later slice.
- **Public URL resolution depends on Plan 003 infrastructure, not this code.**
  For cloud providers, a confirmed `avatar_url`/`icon_url` only resolves if the
  public bucket/container is actually publicly readable or fronted by
  `PUBLIC_ASSETS_BASE_URL`/CDN. That configuration is Plan 003 infra-docs
  territory. Under `local_fs` it works today via the `serve_public_object` route.
  A confirm succeeding while the resulting URL 403s is a provider/bucket
  configuration gap, not a defect in this slice.

## Backend Implementation Steps

### Step 1: Add durable object-key columns

Update:

- `apps/api/models/user.py`
- `apps/api/models/workspace.py`
- new core Alembic migration under `apps/api/alembic/versions/core/`

Add nullable string columns:

```python
avatar_object_key = Column(String, nullable=True)
icon_object_key = Column(String, nullable=True)
```

The migration should add both columns on the core branch. Existing rows keep null
object keys; do not attempt to parse existing URLs.

**Verify**:

```bash
cd apps/api
uv run alembic check
```

Expected result: exits 0 after the migration is created and models/migrations are
in sync.

### Step 2: Remove raw URL mutation from public request schemas

Update:

- `apps/api/services/auth/schemas.py`
- `apps/api/services/users/schemas.py`
- `apps/api/services/workspaces/schemas.py`
- `apps/api/services/auth/update_current_user.py`
- `apps/api/services/users/create_user.py`
- `apps/api/services/users/update_user.py`
- `apps/api/services/workspaces/create_workspace.py`
- `apps/api/services/workspaces/update_workspace.py`

Keep `avatar_url` and `icon_url` in read models. Remove them from create/update
request models and from service mutation logic that writes arbitrary URL strings.

OAuth login may continue to populate `user.avatar_url` from provider profile data
when `avatar_object_key` is null. Do not add workspace external icon URLs.

**Verify**:

```bash
cd apps/api
uv run pytest tests/services/users/test_user_management_services.py \
  tests/services/workspaces/test_workspace_management_services.py
```

Expected result: all selected tests pass, adjusted for the removed request fields.

### Step 3: Add asset upload grant models and token helpers

Create `apps/api/services/assets/domain.py` with Pydantic models for:

- `AssetUploadRequest`: `filename`, `content_type`, `size_bytes`.
- `AssetUploadGrant`: `upload`, `upload_token`, `max_size_bytes`, `expires_at`.
- `AssetConfirmRequest`: `upload_token`.
- `AssetKind`: `user_avatar`, `workspace_icon`.

Create `apps/api/services/assets/tokens.py` that mirrors the OAuth state pattern
from `apps/api/services/auth/oauth/utils.py:137-176`:

- sign with `jwt.encode(..., settings.SECRET_KEY.get_secret_value(),
  algorithm="HS256")`;
- decode with `jwt.decode(..., algorithms=["HS256"])`;
- convert expired/invalid/mismatched tokens into `AuthorizationError` or
  `AppValidationError` with no token contents echoed back to the client.

Create `apps/api/services/assets/utils.py` for:

- comma-separated content-type parsing from settings;
- raster-only icon allowed types;
- extension selection from content type;
- object-key creation with `unique_object_key`;
- `StorageObjectRef` creation for the public bucket;
- stored-object validation;
- best-effort deletion with logged errors.

**Verify**:

```bash
cd apps/api
uv run ruff check services/assets
```

Expected result: Ruff exits 0.

### Step 4: Add user avatar service operations

Create:

- `apps/api/services/assets/create_user_avatar_upload.py`
- `apps/api/services/assets/confirm_user_avatar_upload.py`
- `apps/api/services/assets/delete_user_avatar.py`

Behavior:

- Create upload:
  - validate requested content type against `settings.ALLOWED_IMAGE_TYPES`;
  - validate declared `size_bytes <= settings.MAX_FILE_SIZE_AVATAR`;
  - create a public ref under `users/{user.id}/avatar/`;
  - call `get_storage_provider().create_signed_upload(ref, content_type=...,
    expires_in=timedelta(minutes=10))`;
  - return the signed upload plus upload token.
- Confirm:
  - verify token type/kind/actor/target;
  - stat the object;
  - validate content type and final size;
  - set `user.avatar_object_key` and `user.avatar_url`;
  - audit with `record_user_audit_event(..., AuditAction.UPDATE, details={
    "fields": ["avatar_url", "avatar_object_key"], "storage_provider": ... })`;
  - best-effort delete any previous managed object after the DB mutation.
- Delete:
  - clear `avatar_object_key` and `avatar_url`;
  - audit the update;
  - best-effort delete the previous managed object.

**Verify**:

```bash
cd apps/api
uv run pytest tests/services/assets/test_user_avatar_assets.py
```

Expected result: new tests pass.

### Step 5: Add workspace icon service operations

Create:

- `apps/api/services/assets/create_workspace_icon_upload.py`
- `apps/api/services/assets/confirm_workspace_icon_upload.py`
- `apps/api/services/assets/delete_workspace_icon.py`

Behavior:

- All operations call `require_workspace_role(..., allowed_roles=MANAGER_ROLES)`.
- Create upload validates raster icon content type and
  `size_bytes <= settings.MAX_FILE_SIZE_ICON`.
- Object keys live under `workspaces/{workspace.id}/icon/`.
- Confirm sets `workspace.icon_object_key` and `workspace.icon_url`, records a
  workspace audit event with fields `["icon_url", "icon_object_key"]`, and
  returns `WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)`.
- Delete clears both icon fields, audits the update, and best-effort deletes the
  previous managed object.

**Verify**:

```bash
cd apps/api
uv run pytest tests/services/assets/test_workspace_icon_assets.py
```

Expected result: new tests pass.

### Step 6: Add API routes and OpenAPI coverage

Create one route-operation file per endpoint:

```text
apps/api/routes/auth/create_avatar_upload.py
apps/api/routes/auth/confirm_avatar_upload.py
apps/api/routes/auth/delete_avatar.py
apps/api/routes/workspaces/create_icon_upload.py
apps/api/routes/workspaces/confirm_icon_upload.py
apps/api/routes/workspaces/delete_icon.py
```

Register them in the existing package `__init__.py` files.

Add route tests:

```text
apps/api/tests/routes/auth/test_avatar_assets.py
apps/api/tests/routes/workspaces/test_workspace_icon_assets.py
```

Minimum route coverage:

- unauthenticated upload request returns 401;
- avatar upload/PUT/confirm works against `local_fs`;
- confirm rejects a token for another user;
- delete clears a managed avatar;
- workspace member/read-only cannot create or confirm icon uploads;
- workspace owner/admin can upload/PUT/confirm/delete an icon;
- invalid MIME and oversize requests return 400;
- OpenAPI includes all six new routes.

Update `apps/api/tests/contract/test_openapi_routes.py`.

**Verify**:

```bash
cd apps/api
uv run pytest tests/routes/auth/test_avatar_assets.py \
  tests/routes/workspaces/test_workspace_icon_assets.py \
  tests/routes/storage/test_local_storage_routes.py \
  tests/contract/test_openapi_routes.py
```

Expected result: all selected tests pass.

### Step 7: Wire the frontend direct-upload client

Add a small direct-upload utility, for example
`apps/web/src/lib/api/direct-upload.ts`.

Rules:

- Do not use `apiRequest` for the direct `PUT`; cloud upload URLs are not API
  JSON endpoints and should not receive API cookies, CSRF headers, or
  `X-Workspace`.
- Use `fetch(upload.url, { method: upload.method, headers: upload.headers, body:
  file })`.
- Throw a normal `Error` on non-2xx upload responses. Include status code, not
  provider response bodies.
- Client-side validate `file.size <= max_size_bytes` before the direct upload.

Add typed API hooks:

```text
apps/web/src/features/auth/api/avatar.ts
apps/web/src/features/workspaces/api/workspace-icon.ts
```

Add shared frontend types for `SignedUpload` and `AssetUploadGrant`, either in
feature type files or a small shared storage type file.

**Verify**:

```bash
cd apps/web
pnpm typecheck
```

Expected result: exits 0.

### Step 8: Replace URL inputs with file controls and previews

Update:

- `apps/web/src/features/auth/components/profile-form.tsx`
- `apps/web/src/features/workspaces/components/workspace-settings-form.tsx`
- `apps/web/src/features/workspaces/components/workspaces-table.tsx`
- `apps/web/src/components/shell/app-shell.tsx`

Profile form:

- Remove the "Avatar URL" input.
- Show the current avatar with `Avatar`, `AvatarImage`, and fallback initials.
- Add a file input accepting `image/jpeg,image/png,image/webp`.
- On submit, save display name and, when a file is selected, run:
  create upload -> direct PUT -> confirm.
- Add a remove avatar button when `user.avatar_url` is present.

Workspace settings form:

- Remove the "Icon URL" input.
- Show current workspace icon preview with fallback initials or first letter.
- Add a file input accepting `image/jpeg,image/png,image/webp`.
- On submit, save workspace name and, when a file is selected, run:
  create icon upload -> direct PUT -> confirm.
- Add a remove icon button when `workspace.icon_url` is present.
- Keep controls disabled for users without manager role.

Workspace display:

- Show workspace icons, when present, in the workspace switcher and workspace
  table. Use stable square dimensions and fallback text so layout does not shift.

**Verify**:

```bash
cd apps/web
pnpm typecheck
pnpm lint
pnpm build
```

Expected result: all commands exit 0.

### Step 9: Update environment docs and final checks

Update `apps/api/.env.example`:

- keep avatar/icon size settings;
- remove `image/svg+xml` from `ALLOWED_ICON_TYPES`;
- add a comment or nearby note that SVG icon upload is deferred until sanitizer
  support exists.

Run the focused full verification:

```bash
cd apps/api
uv run ruff check models services/assets services/auth services/users services/workspaces \
  routes/auth routes/workspaces tests/services/assets tests/routes/auth \
  tests/routes/workspaces tests/contract/test_openapi_routes.py core/settings/files.py
uv run alembic check
uv run pytest tests/services/assets tests/routes/auth/test_avatar_assets.py \
  tests/routes/workspaces/test_workspace_icon_assets.py \
  tests/routes/storage/test_local_storage_routes.py \
  tests/services/users/test_user_management_services.py \
  tests/services/workspaces/test_workspace_management_services.py \
  tests/contract/test_openapi_routes.py

cd ../web
pnpm typecheck
pnpm lint
pnpm build
```

Expected result: all commands exit 0.

## Test Plan

New backend service tests:

- `tests/services/assets/test_user_avatar_assets.py`
  - creates signed public upload under `users/{id}/avatar/`;
  - rejects invalid content type;
  - rejects declared oversize file;
  - confirms uploaded object and updates `avatar_url` plus `avatar_object_key`;
  - rejects confirm when token actor/target does not match;
  - deletes previous managed object best-effort on replace/delete.
- `tests/services/assets/test_workspace_icon_assets.py`
  - owner/admin can create and confirm icon upload;
  - member/read-only cannot mutate icon;
  - rejects SVG unless sanitizer support was deliberately added;
  - rejects final stored object size above `MAX_FILE_SIZE_ICON`;
  - audits confirmed and deleted icon changes.

New backend route tests:

- `tests/routes/auth/test_avatar_assets.py`
- `tests/routes/workspaces/test_workspace_icon_assets.py`

Use existing local storage test patterns from
`tests/routes/storage/test_local_storage_routes.py:20-29` and
`tests/support/storage.py:8-12` to force `STORAGE_PROVIDER=local_fs` and clear the
provider singleton.

Frontend verification:

- `pnpm typecheck`, `pnpm lint`, and `pnpm build`.
- Manually verify in local dev that selecting an avatar/icon previews the file,
  saves it, reloads to the persisted public URL, and remove clears it.

## Done Criteria

- [x] `users.avatar_object_key` and `workspaces.icon_object_key` exist in models
      and a core Alembic migration.
- [x] Raw `avatar_url`/`icon_url` user inputs are removed from public mutation
      schemas and frontend forms.
- [x] Avatar and workspace icon upload/confirm/delete routes are registered in
      OpenAPI.
- [x] Upload/confirm/delete service logic uses only `StorageProvider`, never
      provider SDKs or provider-key branches.
- [x] Confirm routes verify existence, content type, size, actor/target binding,
      and public URL availability before mutating DB state.
- [x] Workspace icon writes require owner/admin role.
- [x] SVG workspace icon upload is rejected or explicitly sanitized with tests.
- [x] New service and route tests pass.
- [x] API Ruff, Alembic check, focused pytest, web typecheck, web lint, and web
      build all exit 0.
- [x] `docs/plans/000_README.md` marks this plan DONE after implementation.

## STOP Conditions

Stop and report back instead of improvising if:

- The implementation appears to require a full DB-backed file metadata or upload
  grant table. That belongs in the future `services/files` plan.
- A cloud provider requires changing the `StorageProvider` protocol to make this
  work. Refresh Plan 003/004 together instead.
- The browser cannot PUT directly to a cloud signed URL because bucket CORS is
  missing. Do not proxy through the API; fix cloud CORS/infrastructure docs.
- Product requires SVG workspace icons in this slice and no sanitizer exists.
- The provider cannot return a public URL for public objects after upload.
- Tests require live cloud credentials in normal CI.

## Maintenance Notes

- This plan intentionally leaves image resizing, cropping, thumbnail generation,
  malware scanning, perceptual validation, and SVG sanitization out of scope.
- Replaced or failed uploads can still leave orphaned public objects if best-effort
  deletion fails. Add a cleanup job after the broader file metadata layer exists.
- Future file records should treat `avatar_object_key` and `icon_object_key` as
  early owned-asset references, not as a general file library.
- When Plan 003 cloud providers land, rerun the avatar/icon service tests with
  mocked providers and add optional live smoke tests only behind explicit
  provider env vars.
