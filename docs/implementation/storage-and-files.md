<!-- docs/implementation/storage-and-files.md -->

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
services retain transactional audit and database writes; the File workspace-copy
route uses this contract.

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
Azure verification remains pending.

## Platform upload and maintenance services

The File upload and confirmation services accept an explicit platform scope
from an authorised caller. They check super-admin authority before opening a
maintenance transaction. The ordinary HTTP upload routes retain workspace
scope. Explicit platform management routes use `/files/platform`.

Platform grants bind the creator, unique staging key, storage class, persisted
grant ID, and intended File revision. Confirmation checks the exact declared
size before create-only promotion. It consumes the grant and commits the draft
revision with a strict global audit event. A retry can recover promoted bytes
after a database failure. Replacement revisions leave the published pointer
unchanged. Platform Files have no folder and do not count towards workspace
storage usage. Workspace confirmation also checks the persisted declared size.
Platform replacements create a fresh revision even when the bytes match, so
confirmation can restart failed processing and retain its publication intent.

Ingestible platform revisions enqueue `files.extract_platform` with the
initiating user's concurrency ownership. The handler verifies their live
super-admin authority before maintenance access. Conversion reads bounded
bytes outside the write transaction. A locked recheck of the parent, current
revision, content hash, and publication state prevents stale, deleted, or
withdrawn work from persisting.

Extraction publishes only when platform confirmation explicitly requests
`publish_when_ready`. The request defaults to false and is unavailable on the
workspace confirmation route. Ready text and media publish in the confirmation
transaction. Documents retain the intent in their extraction job and publish
the pinned revision only after successful extraction, even if the browser closes.
The worker rechecks live super-admin authority and the parent revision under
lock. Publication verifies source bytes and writes strict global audit evidence
in the same transaction. Failed processing or audit leaves the draft unpublished.
Withdrawal cancels pending publication intent under the same parent lock.

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

## Platform File management API

Every `/files/platform` operation requires an authenticated active workspace
membership and configured super-admin authority. Read-only workspace membership
is sufficient for a super admin. Services check authority before committing the
request transaction and opening maintenance access. Tenant File routes and
agent tools admit published platform Files through tenant visibility checks.

The management API exposes these operations:

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/files/platform/uploads` | Upload grant for a draft or replacement selected by `file_id` |
| `POST` | `/files/platform/uploads/confirm` | Confirmed immutable draft revision |
| `GET` | `/files/platform/` | Bounded list of live drafts and published Files |
| `GET` | `/files/platform/{file_id}` | Draft metadata and the published revision ID |
| `PATCH` | `/files/platform/{file_id}` | Name and description update |
| `GET` | `/files/platform/{file_id}/revisions` | Bounded revision history |
| `POST` | `/files/platform/{file_id}/restore` | Independent draft revision referencing earlier immutable bytes |
| `POST` | `/files/platform/{file_id}/publish` | Atomic publication of the reviewed current revision |
| `POST` | `/files/platform/{file_id}/withdraw` | Removed publication visibility |
| `DELETE` | `/files/platform/{file_id}` | Tombstone for the existing retention worker |
| `GET` | `/files/platform/{file_id}/content` | Bounded text in a JSON response |
| `GET` | `/files/platform/{file_id}/preview` | Bounded image, video, or PDF bytes |

Publication requires `expected_current_revision_id` to match the locked parent,
ready processing, and stored bytes matching the confirmed size and digest.
The revision marker, published pointer, and strict global audit commit together.
Audit failure rolls back the operation. Replacement uploads and restoration
advance only the draft pointer. Withdrawal retains historical publication
markers and hides all revisions through the parent visibility boundary.
A replacement or restore after withdrawal clears the inactive published pointer
so its fresh draft can process. Earlier publication markers remain intact.
Extraction ignores metadata-only edits when checking the conversion snapshot;
revision identity and publication state still guard persistence.
Metadata edits preserve the extension and reject folder, ownership, and
publication fields. Deletion retains bytes for the existing cleanup worker.

Content and preview requests accept an optional `revision_id`, check its parent
and platform ownership, and authorise every fetch. They return no signed URL
and use `Cache-Control: no-store`. Binary previews add `nosniff` and a restrictive
sandbox Content Security Policy. Admin details use authenticated content reads,
sandboxed HTML previews, and temporary media URLs that are revoked
when the preview closes. Ingestible documents, including PDFs, use bounded stored
Markdown in admin previews. Downloaded bytes and
previously issued signed capabilities retain their existing recall limits.

## Published Files in workspaces

Tenant File lists, details, revision content, previews, and downloads admit
published platform Files alongside workspace Files. Revision reads validate
the parent and publication marker. Platform summaries use the published
revision, including its size, type, hash, and ready processing state. Draft
replacement metadata stays outside tenant responses. Withdrawal or deletion
hides every revision from fresh reads and signed-link creation. Existing
signed capabilities retain their bounded lifetime.

Conversation attachments pin the platform revision when the reference is
created. Reattaching the same File preserves its pin. Attachment conversion,
prompt metadata, `read_file`, and `run_code` inputs honour that pin after a
later publication. Workspace attachments retain their existing current-revision
behaviour. References and target identifiers belong to the consuming workspace;
another workspace cannot discover them. File tools and entity search use the
same publication boundary. Platform content retains the existing untrusted
content framing.

Ordinary mutations, replacement uploads, restores, and folder moves reject
platform targets with an instruction to make a workspace copy. Agent writes
and code outputs retain workspace ownership, including during a super-admin
conversation.

`POST /files/{file_id}/copy` requires an active workspace editor and accepts
`revision_id` and `request_id`. The revision must be published under a live,
published platform parent. Retain the request ID when retrying the same copy;
use a fresh ID for a separate copy. The result has a fresh workspace File
identity and one revision. It carries no source history, references, grants,
or private provenance. Document copies use local extraction rather than copying
derived Markdown. A strict workspace audit records the source platform
File and revision. Later source publication or withdrawal leaves the copy
independent.

Copy operations reserve a deterministic destination through the existing upload
records before storage work. A scoped maintenance lock holds only the already
authorised platform parent; tenant writes and live editor checks remain in the
workspace session. The source lock covers the destination and audit commit,
so publication and withdrawal cannot change source authority midway through a
copy. Failed database writes can recover the same bytes on retry. Expired,
unconsumed reservations retain cleanup ownership of the destination and copy
stage; failed deletion retains the reservation for another pass.

In **Files**, the scope tabs read **All**, the workspace name, and **Shared**.
The filter applies before pagination and totals. At the workspace root, folders
and files form one list sorted together by the chosen column (most recently
updated first by default) and paged 10 rows at a time; folder views contain
workspace Files only. Name sorting uses case-sensitive Unicode code-point order
in both the API (`COLLATE "C"`) and the browser merge. Every tab shares the same
columns; the selection column
stays empty for shared files. Each row shows the type and description under the
name. Search results also show the folder. Processing and failed states appear beside
the name; ready files carry no status badge. **Search files** matches names
across every folder, including in the **Shared** tab, and hides folder rows
while a query is active. Selecting files reveals **Move to Folder…** and
**Delete** for the selection, and the
header checkbox selects every workspace file on the page. Dropping files
anywhere on the page uploads them to the open folder or the root. **Shared**
badges identify platform material. Published shared details offer **View**,
**Download**, and **Make a workspace copy** for workspace editors. Copies open
as independent local Files. Shared Files have no rename, delete, restore, or
move action in the ordinary detail or table.

For supported documents and images, **Add to chat** opens a new conversation with
the File ready in the composer. Choose an agent and enter a message before
sending. The route checks fresh File access before preparing the attachment;
the normal send path pins the published revision when it accepts the File.
Editable text, including HTML, supports attachments. Audio and video do not.

Super admins upload directly through **Upload Files** in the **Shared** tab.
The tab states that uploads become available in every workspace after processing.
Confirmation opts into durable automatic publication. It does not require a
separate review or Publish action. Super admins see pending and failed files
through the paginated management list, with the same supported sort fields as
the tenant list. Other members see published files only. Admin details show
processing status and authenticated previews until publication, then expose the
ordinary viewing, attachment, and workspace-copy actions.

Workspace read-only membership does not remove super-admin upload authority.
Read-only members can browse workspace folders and files, but have no upload,
folder management, selection, rename, restore, or delete controls.
Platform upload confirmation invalidates management and tenant File caches;
processing queries poll until completion. Management queries remain separate
from tenant File caches. The management API retains explicit draft creation,
publication, and withdrawal for other callers. There is no separate management
popover. Uploads outside the Shared tab retain workspace ownership.

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
