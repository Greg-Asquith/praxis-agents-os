# Plan 003: Add GCS, S3, And Azure Blob Storage Providers

> **Executor instructions**: Follow this plan step by step. This plan implements
> cloud adapters for the provider-neutral storage package created in Plan 002.
> Keep the adapters behind `services.storage.provider.StorageProvider`; do not
> resurrect the donor app's broader file-management service layer.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- apps/api/services/storage apps/api/core/settings apps/api/pyproject.toml apps/api/uv.lock apps/api/tests/services/storage apps/api/.env.example`
>
> If the Plan 002 storage package changed, inspect the live
> `services/storage/provider.py`, `domain.py`, `factory.py`, and
> `providers/local.py` before implementing this plan.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: Plan 002 backend storage foundation
- **Category**: foundation
- **Planned at**: 2026-07-01
- **Status**: DONE

## Why This Matters

The current storage package is intentionally provider-neutral but only the local
filesystem adapter is implemented. `STORAGE_PROVIDER=gcs`, `s3`, and `azure_blob`
currently fail through explicit unavailable-provider stubs. That is the right
interim behavior, but production deployments need real cloud object storage for
workspace/user assets, future file records, and agent-created artifacts.

The key goal is provider parity for the small storage contract:

- `put_object`
- `get_object`
- `stat_object`
- `delete_object`
- `create_signed_upload`
- `create_signed_download`
- `public_url`

Do not add category uploads, DB file records, tags, revisions, enrichment,
image-processing workflows, or agent-facing file tools here. Those belong on top
of this package.

## Donor App Reference

Use the donor app for provider mechanics only:

`/Users/gregasquith/Desktop/Coding/saas-template-828165aabff38ff2f1972433638f8ebf10c4716a/apps/api/services/storage`

Relevant donor files:

- `gcs/storage_service.py`: GCS client creation, ADC fallback, bucket setup, async
  wrapping of blocking SDK calls.
- `gcs/signed_urls.py`: V4 signed upload/download URLs, content-type binding, and
  response content-disposition.
- `s3/storage_service.py`: boto3 `put_object`, `get_object`, `head_object`,
  `delete_object`, `generate_presigned_url`, not-found normalization, and public
  URL construction through `PUBLIC_ASSETS_BASE_URL`.
- `blob/client.py`: Azure `DefaultAzureCredential`, account URL resolution,
  public/private container clients, managed identity client ID, and user
  delegation key caching.
- `blob/objects.py`: blob upload/download/delete/property lookup and SAS URL
  generation using user delegation keys.
- `blob/uploads.py`, `blob/private_io.py`, and `blob/buckets.py`: useful examples
  of upload/download/delete composition and Azure's lack of dynamic bucket
  semantics.

Do not copy these donor patterns forward:

- the large `StorageServiceProtocol` in `types.py`,
- category-specific upload behavior,
- `upload_base64_*`,
- tenant/user dynamic bucket APIs,
- file workflow, tags, revisions, search, enrichment, or image processing,
- compatibility aliases that reference GCS bucket settings inside S3/Azure
  bucket resolution.

## Target Shape

Replace the unavailable cloud stubs with concrete providers:

```text
apps/api/services/storage/providers/
  gcs.py
  s3.py
  azure_blob.py
```

Keep `factory.py` as the only settings-driven selection point:

```python
if settings.STORAGE_PROVIDER == "gcs":
    return GcsStorageProvider.from_settings(settings)
if settings.STORAGE_PROVIDER == "s3":
    return S3StorageProvider.from_settings(settings)
if settings.STORAGE_PROVIDER == "azure_blob":
    return AzureBlobStorageProvider.from_settings(settings)
```

Cloud providers should not require local HTTP routes. Signed upload/download
URLs should point directly at the cloud object store or CDN.

## Dependencies

Cloud SDKs are heavy and each deployment uses exactly one provider, so they are
**optional extras**, not base dependencies. The base image (and local dev, which
defaults to `local_fs`) must not pull boto3, google-cloud-storage, or the Azure
SDKs. Add one extra per provider in `apps/api/pyproject.toml`:

```toml
[project.optional-dependencies]
gcs = ["google-cloud-storage>=2.18"]
s3 = ["boto3>=1.35"]
azure = ["azure-storage-blob>=12.22", "azure-identity>=1.17"]
```

`uv.lock` locks all extras regardless (one resolution), but `uv sync` only
installs an extra when asked. Local dev stays lean:

```bash
uv sync                 # base + dev groups, no cloud SDKs
uv sync --extra s3      # add the S3 provider SDK
```

Run `uv lock` after editing `pyproject.toml`.

### Build-time provider selection

Build time and run time are separate phases, so the runtime `STORAGE_PROVIDER`
env var is not visible during `uv sync` in the image build. Bridge them with a
Docker build ARG that names the extra, defaulting to none so the base image stays
minimal:

```dockerfile
# apps/api/Dockerfile (builder stage)
ARG STORAGE_EXTRA=""
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev ${STORAGE_EXTRA:+--extra ${STORAGE_EXTRA}}
```

The deploy config supplies both from one source of truth: `--build-arg
STORAGE_EXTRA=gcs` at build and `STORAGE_PROVIDER=gcs` at run. Keep them derived
from the same deployment variable so the installed SDK and the selected provider
cannot drift. Local Compose leaves `STORAGE_EXTRA` unset (defaults to `local_fs`,
no SDK).

**Mirror this pattern for the future cloud secret-manager work.** Define
`gcp-secrets` / `aws-secrets` / `azure-secrets` extras (or fold each cloud's
secret SDK into that cloud's storage extra if they always deploy together) and
select them at build with the same ARG mechanism, driven by the secret-manager
provider setting. This keeps one selection pattern across every cloud seam.

## Provider Rules

### Shared Rules

- Preserve the `StorageProvider` protocol exactly unless implementation proves
  the contract is missing something essential.
- Always run blocking SDK calls inside `asyncio.to_thread`.
- Use `StorageObjectRef.bucket` to choose public/private bucket or container.
- Run object keys through existing `StorageObjectRef` validation; never trust SDK
  paths directly.
- Return `StoredObject` with size, etag, content type, cache control when known,
  metadata, public URL for public objects, and updated timestamp when available.
- Normalize bad provider config into `StorageProviderUnavailableError` or
  `StorageError` with provider/operation context.
- Do not silently fall back between providers.
- Set `provider_key` on each adapter (`"gcs"`, `"s3"`, `"azure_blob"`) to match
  the factory's selection keys.

### Contract parity with the local provider

Cloud adapters must behave identically to `providers/local.py` for these edges,
or callers and tests will diverge by provider:

- **`get_object` raises `StorageNotFoundError`** on a missing object.
  **`stat_object` returns `None`** (does not raise) when the object is absent —
  the "normalize not-found to `StorageNotFoundError`" rule is scoped to
  `get_object` only, because the protocol types `stat_object` as
  `StoredObject | None`.
- **`create_signed_download` for a `PUBLIC` ref returns `public_url`** (as local
  does), not a signed URL. Only `PRIVATE` refs get a real signed/SAS download URL.
- **`public_url` is set on `StoredObject` for public objects and `None` for
  private objects**, in both `put_object` and `stat_object` results.
- **`SignedUpload.headers` must carry exactly what the client has to send** for
  the signature to verify — the bound `content-type` at minimum — since cloud
  presigners/SAS bind those values into the signature.

### Public URL delivery (provider asymmetry — intentional)

Settings already encode this and adapters must respect it:

- **S3 requires `PUBLIC_ASSETS_BASE_URL`** (enforced in settings validation).
  Build public URLs from it; never expose raw `s3://`/regional bucket URLs.
- **GCS and Azure do not require `PUBLIC_ASSETS_BASE_URL`.** Prefer it when set;
  otherwise fall back to the provider's native public object/container URL, and
  only when the bucket/container is deliberately public.
- Private objects are never served through `public_url`; they require signed
  download URLs regardless of provider.

### GCS

Use donor references:

- `gcs/storage_service.py`
- `gcs/signed_urls.py`

Implementation notes:

- Create a `google.cloud.storage.Client`.
- Prefer Application Default Credentials.
- Support the donor's inline/base64 service-account fallback only if the helper
  already exists in this repo or can be added cleanly without coupling storage to
  model-provider code.
- Validate `GCS_PUBLIC_ASSETS_BUCKET` and `GCS_PRIVATE_ASSETS_BUCKET`.
- `put_object`: `bucket.blob(ref.key).upload_from_string(...)`.
- `get_object`: `blob.exists()` then `download_as_bytes()`.
- `stat_object`: `blob.reload()` or equivalent metadata fetch; map size,
  content type, cache control, etag/md5/generation as available.
- `create_signed_upload`: V4 signed URL, method `PUT`, content type bound.
- `create_signed_download`: V4 signed URL, optional response
  `Content-Disposition` for forced downloads.
- `public_url`: prefer `PUBLIC_ASSETS_BASE_URL`; otherwise use provider public URL
  only when the bucket is deliberately public.

### S3

Use donor reference:

- `s3/storage_service.py`

Implementation notes:

- Create a boto3 S3 client in `AWS_REGION` (typed setting now exists in
  `core/settings/aws.py`; required for `STORAGE_PROVIDER=s3` via settings
  validation). Use `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` when set,
  otherwise fall back to the default boto3 credential chain (instance role).
- `S3_PUBLIC_ASSETS_BUCKET`, `S3_PRIVATE_ASSETS_BUCKET`, `AWS_REGION`, and
  `PUBLIC_ASSETS_BASE_URL` are already enforced for `s3` in settings validation.
- `put_object`: include `ContentType`, optional `CacheControl`, and metadata.
- `get_object`: read and close `response["Body"]`.
- `stat_object`: `head_object`; map `ContentLength`, `ContentType`,
  `CacheControl`, `Metadata`, `ETag`, `LastModified`.
- `delete_object`: check existence before delete so return value stays truthful.
- `create_signed_upload`: `generate_presigned_url("put_object", ...)` with
  `ContentType`.
- `create_signed_download`: `generate_presigned_url("get_object", ...)` with
  optional `ResponseContentDisposition`.
- `public_url`: build from `PUBLIC_ASSETS_BASE_URL`; do not expose raw S3 URLs by
  accident.

### Azure Blob

Use donor references:

- `blob/client.py`
- `blob/objects.py`
- `blob/uploads.py`
- `blob/private_io.py`
- `blob/storage_common.py`

Implementation notes:

- Create `DefaultAzureCredential`, passing
  `AZURE_MANAGED_IDENTITY_CLIENT_ID` when set.
- Resolve account URL from `AZURE_STORAGE_ACCOUNT_URL` or
  `https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net`.
- Validate `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_PUBLIC_CONTAINER`, and
  `AZURE_STORAGE_PRIVATE_CONTAINER`.
- Use configured public/private containers only. Do not add dynamic container
  creation.
- `put_object`: `upload_blob(..., overwrite=True, content_settings=ContentSettings(...))`.
- `get_object`: `exists()` then `download_blob().readall()`.
- `stat_object`: `get_blob_properties`; map size, content settings, metadata,
  etag, and last modified.
- `delete_object`: delete with snapshots included when present.
- `create_signed_upload` / `create_signed_download`: generate SAS URLs with user
  delegation keys, not storage account keys.
- Cache user delegation keys with an expiry buffer, following the donor app's
  `blob/client.py` approach.
- Document required Azure roles for SAS generation:
  `Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey`.
- `public_url`: prefer `PUBLIC_ASSETS_BASE_URL`; otherwise build the container
  URL only when public container access is intentional.

## Testing Strategy

Unit-test provider behavior without real cloud accounts by mocking SDK clients.

Add tests under:

```text
apps/api/tests/services/storage/
  test_gcs_provider.py
  test_s3_provider.py
  test_azure_blob_provider.py
  test_provider_factory.py
```

Minimum coverage:

- factory returns concrete provider for `gcs`, `s3`, and `azure_blob`,
- missing required settings fail clearly,
- `put_object` passes content type, cache control, and metadata to SDK calls,
- `get_object` returns bytes and maps not-found to `StorageNotFoundError`,
- `stat_object` maps provider metadata into `StoredObject`,
- `delete_object` returns false for absent objects and true for deleted objects,
- signed upload binds method/key/content type,
- signed download passes forced-download content disposition,
- public URL uses `PUBLIC_ASSETS_BASE_URL` for S3/Azure/GCS when set.

Do not require live cloud credentials in normal CI. If live smoke tests are added,
mark them explicitly and skip unless provider-specific env vars are set.

## Verification

Run from `apps/api`:

```bash
uv lock
uv run ruff check services/storage tests/services/storage core/settings pyproject.toml
uv run pytest tests/services/storage
```

If optional live smoke tests are added, run them manually with explicit provider
credentials and document the exact env vars required.

## STOP Conditions

- Any implementation needs DB-backed file metadata. Stop and write the
  `services/files` plan first.
- Any provider needs public bucket/container permissions changed automatically.
  Stop; cloud infrastructure policy should be explicit and reviewed.
- Any test requires real cloud credentials in normal CI. Replace it with mocked
  SDK tests and mark live tests separately.
- The provider contract needs workspace/user/run semantics. Stop and build that
  in the future file-service layer, not in cloud adapters.
- Azure SAS generation cannot work with user delegation keys in the target
  environment. Stop and decide explicitly whether account-key SAS is acceptable;
  do not silently downgrade.

## Follow-Up Work

- Authenticated file metadata and upload grants in `services/files`.
- Avatar and workspace icon upload/confirm routes using signed uploads.
- Agent-facing file tools scoped by workspace, conversation, and run.
- Optional live smoke test target per provider.
- Infrastructure docs for required buckets/containers, CORS rules, IAM roles, and
  CDN/public asset configuration.
