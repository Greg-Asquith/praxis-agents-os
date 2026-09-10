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
must not insert an extra prefix. Every workspace-private key must use
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

## Platform-private storage

`StorageBucket.PLATFORM_PRIVATE` resolves `platform/...` keys to a dedicated
deployment-owned private bucket or container. `StorageBucket.PRIVATE` keeps
its workspace namespace and per-workspace resolution. Pass the complete
`StorageObjectRef` through operations; a key alone does not identify a bucket.
Same-bucket promotion preserves create-only destination writes and source
validation.

`services/storage/copy_object.py` copies pinned content between workspace-private
and platform-private storage. Domain callers must persist the destination
identity for retries, serialise writes to it with resource locks, and supply an
authorisation callback. The callback checks source visibility and destination
write authority before any storage access and again before promotion. Owning
services retain transactional audit and database writes; their product routes
remain pending.

Copies verify the expected size and SHA-256 digest, reject public storage, and
write a fresh create-only destination. Source metadata is omitted and copies
use `private, no-store`. Reads enforce a 262,144,000-byte ceiling before buffer
growth. The byte-oriented provider contract buffers at most that payload plus
its conversion copy and bounded stream chunks; input is released before
promotion. No unbounded whole-object reads are used by the copy service.

Temporary keys derive from the destination identity under `copy-staging/` in
the destination namespace. Cleanup waits for writes to finish even after
cancellation. Retrying the same destination validates existing content and
removes a stage left by process interruption or a failed deletion. Callers must
retain that identity until completion or explicit cleanup; there is no separate
copy-stage sweeper. A lost promotion response can recover the complete object
without overwriting or deleting it.

Cloud adapters require these settings when platform storage is used:

| Provider | Setting |
| --- | --- |
| GCS | `GCS_PLATFORM_PRIVATE_BUCKET` |
| S3 | `S3_PLATFORM_PRIVATE_BUCKET` |
| Azure Blob | `AZURE_STORAGE_PLATFORM_PRIVATE_CONTAINER` |

An empty value fails before provider I/O. The configured name must differ
from the public resource and must not start with `WORKSPACE_BUCKET_PREFIX`
followed by `-`, which is reserved for workspace buckets. Platform storage
never provisions a workspace bucket or adopts public cache defaults.

Local development uses separate `platform_private/` object and metadata
roots. Signed downloads use the existing private route with an explicit
`bucket` query value; the signature binds the class, key, expiry, and download
options. Upload signatures also bind content type and exact declared size.
Changing a capability's namespace or class fails. Public routes cannot read
platform bytes. Local filesystem storage remains local-only.

GCP bootstrap creates and hardens the platform-private bucket alongside the
public-assets bucket, retaining the explicit `ENV_FILE` and typed approval
gate. Local filesystem storage creates its separate platform roots on demand.
S3 and Azure create and harden their configured platform resource before the
first platform write, signed upload, or promotion. Successful provisioning is
cached per provider instance. Failed hardening blocks the write and retries
on the next attempt.

S3 uses the configured globally unique bucket name and `AWS_REGION`, with the
same blocked public access, ownership controls, encryption, versioning,
HTTPS-only policy, and browser CORS allowlist as workspace buckets. It preserves
operator policy statements and tags, adding `praxis-platform=true`. Azure
creates a private container, disables public access on an existing container,
and preserves metadata and stored access policies, adding `praxis_platform=true`.
Grant the runtime identity the corresponding provisioning and object permissions
on this resource as well as workspace resources. For Azure, configure
account-level encryption, secure transfer, blob versioning, and retention before
deployment; container provisioning does not manage those
settings. If browsers read signed Blob URLs directly, configure Blob service
CORS with the explicit application origin allowlist. Uploads use the signed
API relay and its existing CORS policy.

Provider contracts are verified with deterministic doubles. Live GCS, S3, and
Azure verification remains pending. Platform publication and workspace
consumption remain pending.

## Platform upload and maintenance services

The File upload and confirmation services accept an explicit platform scope
from an authorised caller. They check super-admin authority before opening a
maintenance transaction. The HTTP upload routes retain workspace scope;
platform management routes and publication remain pending.

Platform grants bind the creator, unique staging key, storage class, persisted
grant ID, and intended File revision. Confirmation checks the exact declared
size before create-only promotion. It consumes the grant and commits the draft
revision with a strict global audit event. A retry can recover promoted bytes
after a database failure. Replacement revisions leave the published pointer
unchanged. Platform Files have no folder and do not count towards workspace
storage usage. Workspace confirmation also checks the persisted declared size.

Ingestible platform revisions enqueue `files.extract_platform` with the
initiating user's concurrency ownership. The handler verifies their live
super-admin authority before maintenance access. Conversion reads bounded
bytes outside the write transaction. A locked recheck of the parent, current
revision, content hash, and publication state prevents stale, deleted, or
withdrawn work from persisting. Extraction never publishes content.

Extraction uses a deterministic, create-only Markdown object. A retry validates
existing bytes before adopting an output left by a failed database transaction.
Interrupted storage writes are cleaned while the parent lock remains held.

Worker startup ensures two explicit maintenance jobs. Each
`platform.files.sweep_deleted` pass processes at most 100 revisions across
expired File tombstones, including unrecorded deterministic extraction outputs.
Live platform Knowledge Base pins prevent purge. Each
`platform.files.sweep_uploads` pass processes at most 100 expired grants,
removing staging and unreferenced promoted objects. Provider deletion failures
retain database evidence for retry. The workspace File and knowledge sweepers
exclude platform rows. Neither platform job accepts tenant or user ownership.

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

## Files in shared chats

Workspace chat sharing publishes saved display content without granting file,
Artifact, or provider permissions. Shared transcripts keep stable File and
Artifact references and obtain downloads through the existing access checks.
They do not persist additional signed URLs or fetch through the chat owner's
personal connections. Missing content shows an unavailable state.

Stopping chat sharing does not revoke independent workspace file access,
downloaded copies, or previously issued download URLs.
