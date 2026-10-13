# Video tools

Read this before changing the media renderer, its API client, or anything that
decodes, cuts, or measures video. Plan 248 builds this foundation; the
model-facing video tools (plans 249 and 250) are pending. For upload limits
and video in chat, see [Storage and files](storage-and-files.md#video-uploads-and-attachments).

## Media renderer

ffmpeg parses attacker-controlled media, so it never runs in the API or worker.
It runs in the media renderer, a separate service:

- `apps/renderer/driver/` is the shared driver: a stdlib-only HTTP server,
  signed URL transfers, the child launcher, the seccomp filter, resource
  limits, and the start-up self-check. A future document renderer reuses it
  with its own image.
- `apps/renderer/media/` holds the ffmpeg operations and the image. The image
  builds a pinned ffmpeg from source with only the demuxers, decoders,
  encoders, and filters the operations use, plus `libx264`, AAC, and `libass`.
  Network protocols are compiled out, and the build fails if any remain.

One request runs one typed operation:

| Operation | Arguments | Outputs |
|---|---|---|
| `probe` | none | none; duration, dimensions, frame rate, codecs, audio, rotation |
| `scene_cuts` | `threshold` (0.05 to 0.95), optional range, `max_cuts` | none; cut times in milliseconds |
| `cut` | `start_ms`, `end_ms` | one MP4. Stream copy when H.264 or HEVC with AAC or no audio starts on a keyframe (within 20 ms); otherwise H.264 and AAC re-encode |
| `extract_audio` | optional range | one M4A, mono 16 kHz AAC |
| `frames` | `times_ms` (1 to 20), `max_edge_px` (64 to 1920) | one JPEG per time |

Arguments are numbers only. The driver rejects unknown fields and any value of
the wrong type, and builds every ffmpeg argument itself. A range must start
before the end of the video; an end past it is trimmed to the end. A frame time
must be strictly before the end.

Every operation, `probe` included, downloads the whole input. Container
metadata can sit anywhere in the file, so a head-and-tail read can report a
video without its audio.

### Isolation

Each native command runs as a child of the driver:

- **Before exec:** `RLIMIT_AS` (`RENDERER_CHILD_MEMORY_BYTES`), `RLIMIT_CPU`,
  `RLIMIT_FSIZE` (the output limit), `RLIMIT_NPROC`, and `RLIMIT_CORE=0`, then
  `no_new_privs` and the seccomp filter. The filter kills other architectures
  and x32 calls, allows only `AF_UNIX` sockets, and returns `EPERM` for
  io_uring, ptrace, and `process_vm_readv`/`writev`.
- **Environment:** only `HOME`, `TMPDIR`, `PATH`, and `LANG`.
- **Driver memory:** the driver is non-dumpable, so a child can't read its
  memory or `/proc/<pid>/environ`.
- **After each request:** the driver kills the child's process group, then
  every other process under its user with `kill(-1, SIGKILL)`, which the kernel
  applies atomically against fork, so a child that keeps forking can't outrun
  it. It then checks that none is left and deletes the request's directory. If
  a process survives, the driver exits and Cloud Run starts a clean instance.
- **Fail closed:** on start, the driver refuses to run if an ancestor other
  than PID 1 shares its user, because `kill(-1)` would reach it. It then runs a
  probe child under the same limits. If that child can open an inet socket,
  call io_uring with valid arguments, ptrace its own child, or read the
  driver's environment, the driver exits and serves nothing. A host's own
  seccomp profile can also deny io_uring, so tests prove each filter rule by
  evaluating the BPF program directly.

A child shares the driver's user, so it could kill the driver. That fails only
the current request, and Cloud Run replaces the instance.

### Transfers

The driver is the only part with network access. It downloads and uploads only
URLs that start with a prefix in `RENDERER_ALLOWED_URL_PREFIXES`
(`https://storage.googleapis.com/` on GCP), ignores proxy settings, and refuses
redirects. Inputs above `RENDERER_MAX_INPUT_BYTES` are refused.

A request's `timeout_seconds` bounds all of it: the download, every child, and
the uploads. Transfers check the deadline between chunks and return `timeout`
when it passes. One blocking read or write waits at most 30 seconds, so a
stalled transfer ends inside Cloud Run's 60 seconds of request headroom.

## API client

`apps/api/services/media/`:

- `run_media_operation(workspace_id, source, operation)` takes a File
  revision the caller has already resolved for the workspace. It refuses a
  revision from another workspace or a non-video, signs one download for the
  revision and one size-bounded staging upload per output, and posts the
  request. It validates the result against the operation's schema and trusts
  an output only when the staged object exists and matches the size the
  renderer reported. On any failure it deletes the staged objects.
- `save_media_output` copies a staged output into a new File inside the
  caller's transaction. It requires platform-private storage under the
  workspace's staging prefix and the written-size limit (`MAX_FILE_SIZE_VIDEO`
  for video), then reads the object with the shared bounded reader, which
  checks the size and the SHA-256 the renderer reported. A committed
  `FileUpload` reservation owns the File's bytes until the caller commits, so
  the upload sweeper removes them if it never does. The staged object stays as
  the retry source: call `discard_staged_outputs` after commit, or leave it to
  the one-day staging lifecycle rule.
- `settings.media_renderer_available` is true when `MEDIA_RENDERER_URL` is
  set and storage is `gcs` or `local_fs`. Azure and S3 adapters are pending;
  see [Other clouds](#other-clouds).

Failures raise `MediaRendererError` with a stable code and a plain message.

| Setting | Default | Purpose |
|---|---:|---|
| `MEDIA_RENDERER_URL` | unset | Renderer base URL. Unset makes the renderer unavailable. |
| `MEDIA_RENDERER_AUTH` | `google_id_token` | `google_id_token` sends a Google ID token for Cloud Run IAM. `shared_secret` sends `MEDIA_RENDERER_SHARED_SECRET` as a bearer token, for a renderer on a private network. `none` is local only. |
| `MEDIA_RENDERER_SHARED_SECRET` | empty | At least 32 characters when `MEDIA_RENDERER_AUTH=shared_secret`. The renderer holds the same value as `RENDERER_SHARED_SECRET`. |
| `MEDIA_RENDERER_TIMEOUT_SECONDS` | `900` | Total time one operation may take, transfers included. The client waits 60 seconds more for cold start and the round trip. |
| `MEDIA_RENDERER_MAX_OUTPUT_BYTES` | `524288000` | Largest output a renderer upload may write. |
| `MEDIA_STAGING_URL_TTL_SECONDS` | `1800` | Lifetime of the renderer's signed URLs. Must be at least the timeout plus 60 seconds, so uploads can't expire mid-render. |
| `MEDIA_RENDERER_LOCAL_STORAGE_URL` | `http://host.docker.internal:8000` | Local only: the API origin as the renderer container reaches it. |

## Video probe

A workspace video revision is measured once, in the background, by the
renderer's `probe` operation. `queue_video_probe` (`services/files/`) runs
wherever a revision becomes a File's current revision (upload confirmation,
platform copies, restores, `create_file_with_revision`, and
`append_file_revision`). It marks the File `pending` and enqueues a
`video.probe` job, unless the File isn't a workspace video or
`settings.media_renderer_available` is false. It lives in Files because
`services/media` imports the Files writers that call it.

The `probe_video` job handler stores the result in the revision's
`media_metadata` (`VideoMetadata` in `services/files/domain.py`). A restore
copies the measurement from the revision it restores instead of probing again.
The File's processing status follows its current revision:

| Outcome | File | Retried |
|---|---|---|
| Measured, with a video stream, within `VIDEO_MAX_SOURCE_DURATION_SECONDS` | `ready` | No |
| No video stream, longer than the limit, unreadable, or over the renderer's limits | `error`, with a plain reason | No |
| Renderer unreachable, timed out, or another renderer failure | `error` until the next attempt | Up to 3 attempts |

The job's timeout is `MEDIA_RENDERER_TIMEOUT_SECONDS` plus 120 seconds, so it
outlasts the client's own wait. Tools read duration and size from
`media_metadata` and never probe inline.

| Setting | Default | Purpose |
|---|---:|---|
| `VIDEO_MAX_SOURCE_DURATION_SECONDS` | `14400` | Longest video a File may hold. Longer videos fail processing. |

## Gemini video input

Tools hand workspace video to Gemini with `load_workspace_video_input`
(`services/agents/runtime/tools/media_inputs.py`). It resolves the current
revision the caller can see, then picks the input by transport:

| Transport | Input | Limit |
|---|---|---|
| Vertex, GCS storage | `VideoUrl` with the revision's `gs://` URI | The model's own limits |
| Gemini API (`GOOGLE_API_KEY`) | Inline up to the tool's bound, otherwise `UploadedFile` from a Files API upload | 2 GB per file, 20 GB per project, kept 48 hours |
| Vertex, other storage, or a platform File | Inline `BinaryContent` | The tool's `inline_max_bytes` |

`VideoInputOptions` sets `fps`, a start and end offset, and media resolution;
Pydantic AI sends them as the part's `video_metadata` and `media_resolution`.
The server builds every URI from the revision's object key, and refuses a key
outside the caller's workspace before building one. A model never supplies a
URI, bucket, or object name.

On Vertex, `StorageProvider.model_input_uri` returns the URI for workspace
objects on GCS and `None` for every other provider or bucket. GCP bootstrap
grants the Vertex AI service agent
(`service-<project number>@gcp-sa-aiplatform.iam.gserviceaccount.com`)
`roles/storage.objectViewer` on the project, with a condition that limits it to
buckets named `<WORKSPACE_BUCKET_PREFIX>-…`. Gemini can therefore read any
workspace bucket in the project; the URI the server builds is the isolation
boundary.

On the Gemini API, `services/gemini_files` streams the object to the Files API
in 8 MiB chunks without holding it in memory, waits for the file to become
`ACTIVE` (up to 5 minutes), and returns its name, URI, and expiry. The caller
caches them on the revision (`file_revisions.gemini_file_*`) and reuses the
upload while it has at least an hour left. A replaced or purged revision's
upload is deleted, best effort; Google deletes anything missed after 48 hours.
Each upload records a `gemini_files_upload` audit event on the File, because
workspace bytes leave the deployment, and commits it before the model call.
Files API uploads aren't scoped to a workspace on Google's side: one API key
serves the deployment, so the cached name is only read back from the revision
the tool resolved for the caller. Two concurrent first uploads of one revision
both succeed; the later one is cached and the other expires unused.

`long_video_input_available()` is true when Google is configured and can read
past the inline bound: on the Gemini API, or on Vertex with GCS storage. Tools
that need long video combine it with `settings.media_renderer_available` in
their `availability_check`, so they're hidden rather than failing at call time.

## Long media calls

Video calls run inside the tool call, under an explicit tool `timeout`. The
run's lease heartbeat continues during the call, and
`AGENT_RUN_MAX_DURATION_SECONDS` bounds the whole continuation:

| Work | Tool timeout |
|---|---|
| A Google model call over video (generation, edits, understanding) | `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` (600 s): 300 s for the model call plus the Files API's 300 s processing wait |
| A renderer operation | `MEDIA_RENDERER_TIMEOUT_SECONDS` plus the client's 60 second allowance (`REQUEST_ALLOWANCE_SECONDS`) |

When a timeout passes, Pydantic AI cancels the call and returns a retry to the
model. Nothing is saved, because tools write their output File only after the
provider returns. Cancelling the outbound request doesn't stop Google billing a
generation that was already running.

Video tools that call the renderer or a generation model are
`code_eligible=False`. `run_code`'s 60 second budget counts time spent in
nested calls, so they would always time out there. A tool that needs several
outputs does the work concurrently inside one call instead.

A long call reports its stage with a `tool.progress` stream event, emitted
through `ctx.deps.sink` with the call's `tool_call_id` and a short Title Case
`stage` (at most 80 characters), such as `Preparing Video`. The event is live
only and isn't saved; the client keeps the latest stage on a running call and
shows it under the tool row's heading, next to the elapsed time.

The runtime never runs a tool call twice. An interrupted call gets an
interrupted return, approval continuations aren't replayed after a process
failure, and recovery evidence lists uncertain actions. A completed paid call
therefore isn't repeated on resume. A per-call idempotency record, and
reserving cleanup of the output before the call, are pending with the first
provider that writes output straight into workspace storage (Veo).

## Video in the conversation

Any completed tool result that names a video File gets a video row, unless a
more specific presenter claims the result first (`video-tool-presenter.tsx`,
registered after integration presenters). A result names a video when it has
`file_id` and a `video/*` `media_type`, either at the top level or in a list
such as `clips`. Tools in plans 249 and 250 return that shape, so they need no
presenter of their own to show their videos.

Each video plays from a signed preview URL, with the File's duration and
upright dimensions, a details button that opens the File, and a download
button. The row reads the File itself, so it shows "Preparing video" while the
probe runs and the processing error if it fails. The player keeps its first
signed URL, because a refetch would restart playback; the URL lasts 10
minutes, so a long pause can need the row reopened.

In the composer, a chat attachment shows its upload percentage, then
"Preparing video" while the probe runs, then the duration and dimensions. The
person can send once the upload is confirmed, before the probe finishes. A
sent video shows the same card as a tool result.

## Deployment

On GCP, `deploy/gcp/deploy.sh` deploys `praxis-media-renderer` as a Cloud Run
service: gen2, concurrency 1, minimum 0 and maximum 3 instances, 4 vCPU and
16 GiB by default, and a request timeout 60 seconds above
`MEDIA_RENDERER_TIMEOUT_SECONDS`. It scales to zero, so it costs nothing while
idle. The deployment has no VPC, so ingress is `all`; Cloud Run IAM is the
caller check, and only the API and worker service accounts hold
`roles/run.invoker`. The renderer's own service account has no roles. See
[the GCP deployment guide](../../deploy/gcp/README.md).

Cloud Run's file system is memory, so a 4 GiB source uses 4 GiB of the
instance before ffmpeg starts. `MAX_FILE_SIZE_SOURCE_VIDEO` sets one limit for
uploads, the worker, and renderer input; raise the instance memory with it.
`deploy.sh` rejects media settings the API would refuse at startup, and signed
URL lifetimes shorter than the renderer's request timeout.

### Other clouds

The renderer image, its request protocol, and the API client don't depend on
GCP: the renderer is an ordinary container that talks only to signed URLs under
`RENDERER_ALLOWED_URL_PREFIXES`. What each deployment supplies is storage that
can stage outputs, a way to authenticate the API to the renderer, and an expiry
rule for staging.

| Need | GCP | Azure and AWS |
|---|---|---|
| Staging uploads (`create_signed_staging_upload`) | GCS signs a size range | Pending. Azure SAS and S3 presigned `PUT` can't sign a range, so their adapters can rely on the API's stored-size check (see [Storage and files](storage-and-files.md)). |
| Caller authentication | Cloud Run IAM with `google_id_token` | `shared_secret` on private ingress (Container Apps internal ingress, or a private ECS or App Runner service). The renderer refuses operation requests without the secret. |
| Staging expiry | GCP bootstrap's one-day lifecycle rule on `platform/media-staging/` | Pending: a Blob lifecycle management policy or an S3 lifecycle rule on the same prefix. |
| Large source uploads | Signed direct upload, up to `MAX_FILE_SIZE_SOURCE_VIDEO` | S3 signs direct uploads but caps a single `PUT` at 5 GiB. Azure relays uploads through the API, so it keeps `MAX_FILE_SIZE_VIDEO` (100 MB) until it signs direct uploads. |
| Isolation self-check | Verified locally in Docker; Cloud Run gen2 is pending (G1) | Unverified. The runtime must let an unprivileged process set `no_new_privs` and install a seccomp filter, and run the renderer as its container's first process. |

The repository has no Azure or AWS deployment tooling yet. Until a deployment
has a staging adapter, `settings.media_renderer_available` is false and video stays
refused in chat.

Locally, set `MEDIA_RENDERER_URL=http://127.0.0.1:8090` and
`MEDIA_RENDERER_AUTH=none` in `apps/api/.env`, and `make dev` starts the
renderer on `127.0.0.1:8090`. See [Local development](local-development.md).
Uploading a video to **Files** runs the probe, so the File moving from
**Processing** to ready confirms the renderer works end to end. No
model-facing tool calls the renderer yet (plans 249 and 250).

## Verification

`make media-renderer-check` builds the renderer's test image and runs its tests
on Linux in Docker. They kill processes, so they refuse to run outside that
container. CI runs the same target, with the renderer's lint and a production
image build. API client tests are in `apps/api/tests/services/media/`.
