# Storage and file contracts

Read this before changing storage provisioning, uploads, file revisions,
or file links. Backend paths are relative to `apps/api/`.

## Document attachment limits

The document attachment settings are defined as follows:

| Setting | Default | Purpose |
|---|---:|---|
| `MAX_FILE_SIZE_DOCUMENT` | `104857600` | Maximum raw upload size for documents. Configuration accepts up to `262144000` bytes. |
| `MAX_MULTIMODAL_DOCUMENT_BYTES` | `20971520` | Maximum PDF attachment size sent to a model as raw bytes. |
| `CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS` | `60` | Maximum time for on-demand chat attachment conversion. Configuration accepts 5–300 seconds. |

## Storage providers and upload lifecycle

Storage goes through the `services/storage` provider abstraction.
`local_fs` is the local default; cloud providers (`gcs`, `s3`, `azure_blob`)
must stay behind the `StorageProvider` contract, with their SDKs as
optional extras (`gcp`, `aws`, `azure`). Public assets stay in one shared
public bucket; managed avatar/icon keys retain their existing `users/...`
and `workspaces/...` roots, so deployment URLs and public-access policies
must not insert an extra prefix. Every private key must use
`workspaces/{workspace_id}/...`
and resolves unconditionally to that workspace's dedicated bucket/container.
GCS bucket creation must pass the configured immutable
`GCS_WORKSPACE_BUCKET_LOCATION`; provisioned GCS workspace buckets retain
object versioning and a 30-day soft-delete policy alongside uniform access
and public-access prevention. Their signed-upload CORS policy is converged
from the explicit `ALLOWED_CORS_ORIGINS` allowlist; GCP bootstrap applies the
same policy to the shared public-assets bucket. GCS client ADC must explicitly
request the `cloud-platform` OAuth scope so metadata-server credentials can
call IAM `signBlob`; the runtime service account must also retain Service
Account Token Creator on itself. S3 workspace buckets use the
account-regional
namespace and derive their physical name from the configured prefix, compact
workspace UUID, `AWS_ACCOUNT_ID`, and `AWS_REGION`; retain ownership controls,
versioning, HTTPS-only policy, blocked public access, and the encryption
baseline when changing S3 provisioning.
Workspace creation enqueues `storage.provision_workspace_bucket`, while
first writes and signed uploads retain an idempotent provisioning backstop.
Cloud identities must be able to inspect, create, harden, and read/write
bucket tags or labels without discarding provider- or operator-owned values.
Direct-upload grants target unique temporary keys only; confirmation
validates and conditionally promotes bytes to a distinct create-only durable
key. Upload capabilities bind the exact client-declared byte length; Azure
uploads use the bounded signed API relay because Blob SAS cannot constrain
request size. Managed asset and skill-document grants persist consumption
state so confirmation is replay-safe and crash-idempotent, and the storage
sweeper deletes expired unconfirmed objects and grant rows. File-folder
deletion remains synchronous only for at most 100 live files; reject larger
folders before locking their files, and keep the folder-level audit's file ID
sample bounded while per-file deletion events retain the complete audit trail.
For a clean local reset from the repository root, remove
`apps/api/.local/storage` and re-upload development files; there is deliberately
no compatibility read path.

## Runtime file references

User-facing workspace File links use the stable Markdown target
`/files?fileId=<uuid>`. Runtime instructions require agents to use that target
when a tool returns a File reference and forbid bare download labels.
Artifact references use `/artifacts/<uuid>` and must not use File targets.

## Frontend file links

Conversation Markdown treats `/files?fileId=<uuid>` as an authenticated
download action: clicking it mints a fresh signed URL through the Files API.
If the ID belongs to an artifact instead, the link opens that artifact's
management page after the Files API reports that no file exists.
Other internal and external Markdown links retain their normal behaviour.
