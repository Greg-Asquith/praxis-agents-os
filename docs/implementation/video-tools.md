# Video tools

Read this before changing the media renderer, its API client, or anything that
decodes, cuts, or measures video. The model-facing video tools are
`transcribe_video`, `find_video_moments`, and `ask_video`; a tool that cuts
clips is pending. For upload limits and video in chat,
see [Storage and files](storage-and-files.md#video-uploads-and-attachments).

## Media renderer

ffmpeg parses attacker-controlled media, so it never runs in the API or worker.
It runs in the media renderer, a separate service:

- `apps/renderer/driver/` is the shared driver: a stdlib-only HTTP server,
  signed URL transfers, the child launcher, the seccomp filter, resource
  limits, and the start-up self-check. A future document renderer reuses it
  with its own image.
- `apps/renderer/media/` holds the ffmpeg operations and the image. The image
  builds a pinned ffmpeg from source with only the demuxers, decoders,
  encoders, and filters the operations use, plus `libx264`, `libopus`, AAC,
  and `libass`.
  Network protocols are compiled out, and the build fails if any remain. The
  image also holds OpenCV (headless) and the YuNet face detection model,
  pinned by hash, for automatic framing.

One request runs one typed operation:

| Operation | Arguments | Outputs |
|---|---|---|
| `probe` | none | none; duration, dimensions, frame rate, codecs, audio, rotation |
| `scene_cuts` | `threshold` (0.05 to 0.95), optional range, `max_cuts` | none; cut times in milliseconds |
| `cut` | `segments` (1 to 10 `[input, start_ms, end_ms]`), `width` and `height` (even, 64 to 3840), `fps` (24 to 60), `fit`, optional `reframe` and `shot_cuts` (up to 500 `[input, time_ms]`) | one H.264 and AAC MP4 joining the segments in order |
| `extract_audio` | optional range, `chunks` (1 to 32) | one mono 16 kHz Ogg Opus file (32 kbit/s) per chunk, plus each chunk's range on the source timeline |
| `frames` | `times_ms` (1 to 20), `max_edge_px` (64 to 1920) | one JPEG per time |

Arguments are numbers and booleans only. The driver rejects unknown fields and any value of
the wrong type, and builds every ffmpeg argument itself. A range must start
before the end of the video; an end past it is trimmed to the end. A frame time
must be strictly before the end.

`extract_audio` splits the range into `chunks` near-equal parts. Each split
moves into the longest silence (quieter than -35 dB for at least 0.3 s) within
10% of a part's length of the even split, or stays at the even split when
there's none. Chunks are re-encoded from one extraction, so each starts
exactly at its reported time.

`cut` takes one signed input per distinct source; segment `input` numbers
them from 0, and every input must be used. Each segment is scaled to the
output size (centre-cropped to fill, or with `fit`, the whole frame over a
blurred, filled copy of itself), resampled to `fps`, and given 48 kHz stereo
audio, silent for a source without audio, so sources of different sizes,
frame rates, and audio layouts join cleanly. Rotated phone video is turned
upright first. Output is `libx264` at CRF 18, capped at 8 Mbit/s, with AAC at
128 kbit/s: about 61 MB a minute at most. Each segment's decoder uses two
threads, so ten segments stay inside the child's memory limit.

With `reframe` (not with `fit`), each segment whose shape differs from the
output is cropped to follow the speaker:

1. ffmpeg samples the segment at 2 fps, 640 pixels on the long side, as raw
   BGR frames.
2. `media/faces.py` runs YuNet on those frames in its own isolated child and
   prints the faces as JSON. OpenCV reads only raw pixels, never a media
   file, and the driver checks the shape of what it prints.
3. `media/reframe.py` plans the crop per shot, with shots split at the
   segment's `shot_cuts`. The crop starts on the largest face, holds still
   while that face stays in its middle third, and pans for 400 ms when it
   leaves. A pan stops at the next cut and the crop jumps there, so it never
   pans across one. A shot with no face is centred. Frames within 100 ms of a
   cut are ignored, because they may belong to either shot.
4. The crop's position becomes an ffmpeg expression of time on the `crop`
   filter, built by the driver from numbers.

Active-speaker choice when several people are in frame is pending; the
largest face wins.

Every operation, `probe` included, downloads each whole input. Container
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
redirects. A request takes 1 to 10 inputs; inputs above
`RENDERER_MAX_INPUT_BYTES` together are refused, because they share the
instance's in-memory disk.

A request's `timeout_seconds` bounds all of it: the download, every child, and
the uploads. Transfers check the deadline between chunks and return `timeout`
when it passes. One blocking read or write waits at most 30 seconds, so a
stalled transfer ends inside Cloud Run's 60 seconds of request headroom.

## API client

`apps/api/services/media/`:

- `run_media_operation(workspace_id, sources, operation)` takes the File
  revisions the caller has already resolved for the workspace, one per
  operation input. It refuses the whole request if any revision is from
  another workspace or isn't a video, signs one download per revision and one
  size-bounded staging upload per output, and posts the request. It validates the result against the operation's schema and trusts
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

## Transcripts and shot cuts

A video revision's transcript and shot cuts are derived once, on first need,
and kept with the revision. They aren't Files, so a read can create them.

- `get_video_transcript` (`services/media/`) returns the stored transcript, or
  extracts the audio with `extract_audio`, transcribes each chunk (four at a
  time, 16 for Gemini), moves each chunk's words onto the video's timeline, and stores the
  result as JSON under the File's key prefix
  (`file_revisions.transcript_object_key`). A word is clamped to its own
  chunk, so word times never run backwards. Sentences end at `.`, `?`, or
  `!`, a change of speaker, or a pause of 2 seconds. A stored transcript is
  reused whatever provider or language a later call asks for, so a revision
  is transcribed and billed once. Two concurrent first transcriptions of one
  revision both reach the provider, and the later save fails.
- `get_video_shot_cuts` stores the renderer's `scene_cuts` times on the
  revision (`file_revisions.shot_cuts_ms`).

Both columns are set once, like `media_metadata`. Purging a File deletes the
transcript object with the revision's other objects, and Files usage counts
it.

The provider is the first one the deployment has, in the order measured in
plan 249 B1:

| Provider | When | Chunk limit | Notes |
|---|---|---|---|
| Chirp 3 (`chirp_3`) | Vertex (`GOOGLE_VERTEX_AI`) with GCS storage | 19 minutes | `BatchRecognize` in `VIDEO_TRANSCRIPTION_SPEECH_LOCATION` (`eu` by default) reads the staged chunk by `gs://` URI, with word timings, punctuation, and speaker labels. Speaker labels restart with each chunk. A language without a region, such as `en`, is sent as `auto`. |
| `whisper-1` | `OPENAI_API_KEY` | 60 minutes and 25 MB | Receives the chunk bytes. Punctuation comes from the response text, matched back to its words. No speaker labels. |
| Gemini 3.8 Flash | Google on either transport | 8 minutes | Receives the chunk bytes inline and answers with structured words, times in seconds, and speaker letters. Word starts were about 0.4 s out at the median and 1 s at p95, so it comes last. A chunk takes about half its length to transcribe. |

With none of them (a deployment with only Anthropic models), `transcribe_video`
is hidden. Asked for word times as JSON text rather than structured output,
Gemini drifted by up to 13 seconds within a minute of speech. Chirp 3 reads Ogg Opus and FLAC but returns nothing for AAC, which is
why `extract_audio` writes Opus.

Each transcription records a `video_transcription` usage event with the
provider's requests (and tokens, for Gemini) and the audio length in
`details.audio_seconds`. The usage summary prices Chirp 3 ($0.016) and
`whisper-1` ($0.006) per audio minute from `AUDIO_INPUT_PRICES` in
`services/ai_usage/pricing.py`, and Gemini by its tokens.

### `transcribe_video`

`transcribe_video(file_id, language?)` takes the current revision of one of
the workspace's own videos once its probe has finished. It returns the saved
transcript File, word count, language, and provider, plus the first eight
sentences with MM:SS times as an untrusted-content node. It writes the
transcript as `<video name> transcript.srt` (one SubRip cue per sentence) in
the video's folder; calling it again adds a revision to that File rather than a
copy. A new transcription records a `video_transcription` audit event on the
video File with the provider and model, and commits it before the transcript
File is written. The tool isn't code-eligible; its timeout is the renderer's
plus 900 seconds for transcription.

| Setting | Default | Purpose |
|---|---:|---|
| `VIDEO_TRANSCRIPTION_SPEECH_LOCATION` | `eu` | Speech-to-Text multi-region (`eu` or `us`) for Chirp 3. |

On GCP, bootstrap enables the Speech-to-Text API and grants the API and worker
service accounts `roles/speech.client` when `GOOGLE_VERTEX_AI=true`. Speech
reads the staged audio as its own service agent.

## Moments and questions

`find_video_moments` and `ask_video` send the video to
`VIDEO_UNDERSTANDING_MODEL` (Gemini 3.8 Flash by default) through the shared
Gemini video input, at 1 frame a second and low media resolution.
`services/media/understanding.py` runs the calls, at most three at a time,
under one `video_understanding` usage event, and answers with structured
output or text. Both tools need Google on either transport, and
`find_video_moments` also needs the renderer. Where Gemini can't read long
video (Vertex without GCS storage), a video up to 18 MB goes inline and a
larger one is refused before it is transcribed. Each call records a
`video_understanding` audit event on the video File with the model and the
range, committed before the model call.

Both take an optional `start` and `end` (`MM:SS` or `H:MM:SS`), sent as the
part's start and end offsets. With offsets, Gemini still gives times from the
start of the full video (checked live on a counter video, plan 249 B2), so
times need no shifting. `detail` raises the frame rate to 5 for fast action and
covers at most a fifth of a window (8 minutes by default), so a call's frame
count stays the same.

### `find_video_moments`

`find_video_moments(file_id, brief, count?, min_seconds?, max_seconds?, start?,
end?, detail?)` returns up to `count` (default 5, at most 10) moments, best
first. Each has validated `start_ms`, `end_ms`, `score` (0 to 100), and
`shot_count`, and the model's `title`, `hook`, `reason`, plus the transcript
excerpt, each as an untrusted-content node with File and revision provenance.

1. It loads the transcript (creating it with `transcribe_video`'s path when
   missing; a video with no audio has none) and the shot cuts.
2. Ranges longer than `VIDEO_MOMENTS_WINDOW_SECONDS` are split into the fewest
   equal windows that overlap by 60 seconds; a 4-hour video is 7 windows. Each
   window's prompt carries the brief, the length bounds, and that window's
   transcript lines with times, framed as untrusted content.
3. The model returns candidate moments with `MM:SS` times. Unreadable times
   are dropped, and each range is clamped to its window.
4. `services/media/snapping.py` snaps each range: a start inside a sentence
   moves back to the sentence start, and a start in a pause moves on to the
   next sentence; an end inside a sentence moves on to its end, and an end in
   a pause moves back to the last sentence. A moment shorter than
   `min_seconds` runs on to the first sentence end that makes it long
   enough. A moment that then falls outside `min_seconds` to `max_seconds`
   is dropped. Each cut then moves to a shot change within
   `VIDEO_SNAP_SHOT_TOLERANCE_MS`, if the range still fits the bounds.
5. Of two overlapping moments, the higher score is kept, so a moment found in
   two windows appears once.

When fewer moments survive than asked for, the result says so in `note`.
`cut_video_clips` reuses the same snapping.

### `ask_video`

`ask_video(file_id, question, start?, end?, detail?)` answers one question
with `MM:SS` references, as an untrusted-content node. One call covers at most
`VIDEO_MOMENTS_WINDOW_SECONDS` (40 minutes), at medium media resolution up to
10 minutes and low beyond that; for a longer video the agent passes `start`
and `end`. It doesn't read the transcript.

| Setting | Default | Purpose |
|---|---:|---|
| `VIDEO_UNDERSTANDING_MODEL` | `gemini-3.8-flash` | Google catalog model that watches the video. |
| `VIDEO_MOMENTS_WINDOW_SECONDS` | 2400 | Longest stretch one call watches (300 to 3600). |
| `VIDEO_SNAP_SHOT_TOLERANCE_MS` | 700 | How far a snapped cut may move to a shot change (0 to 3000). |

In the conversation, a completed `find_video_moments` call shows the source
video and its moments; selecting one plays just that range, with a
`#t=start,end` media fragment on the signed URL. A completed `ask_video`
call plays the range it watched, with the question and answer. Running and
failed calls keep the default row with its progress stage.

Chat accepts video once `find_video_moments` or `cut_video_clips` is
available, and **Add to chat** in Files offers video then too.

## Clips

`cut_video_clips(clips, aspect_ratio?, framing?)` renders up to five clips and
saves each as a new video File next to the video its first segment comes
from. It needs only the renderer. Internal write, auto by default, not
code-eligible.

- Each clip has 1 to 10 `segments`, joined in order. A segment is a
  `file_id` with optional `start_ms` and `end_ms`; omitting both takes the
  whole video. Segments can come from several of the workspace's own videos.
  Optional `name` names the File; otherwise it is named from the first video
  and range, such as `Talk 0.41-1.10.mp4`.
- `snap` (default true) moves each segment with `find_video_moments`'
  snapping, without its length bounds: whole sentences, then shot changes
  within `VIDEO_SNAP_SHOT_TOLERANCE_MS`. A move of a second or more comes back
  as a warning on that clip. The first snapping call on a video transcribes it
  and measures its shots, as `find_video_moments` does; a video with no audio,
  or no transcription provider, snaps to shots only.
- `aspect_ratio` is `original` (the first video's upright shape), `9:16`,
  `1:1`, `4:5`, or `16:9`, at 1080 pixels on the short side. The frame rate is
  the first video's, rounded, between 24 and 60. `framing` is `auto` (the
  default: crop to follow the largest face in each shot, centred where there
  is none), `center` (crop the middle), or `fit` (whole frame over a blur).
  `auto` measures each video's shots on first use, so the crop jumps only at
  a cut. Captions and silence removal are pending.
- A clip has no length cap of its own. A clip File is held to the written
  size limit for video (`MAX_FILE_SIZE_VIDEO`, 100 MB, and never more than
  `MEDIA_RENDERER_MAX_OUTPUT_BYTES`), so the longest clip is that size at the
  renderer's bitrate caps: 1 minute 43 seconds by default. A segment outside
  its video, or a clip over that length, fails the call with a reason before
  anything renders.

Clips render three at a time (the renderer's default maximum instances). One
clip failing doesn't stop the others: each saved clip is a File with the
renderer's probe stored on the revision, so it is ready at once, and the result
reports every clip with its status, ranges, warnings, and a failure reason.
When no clip is saved, the call fails. Each call records a `video_clips` audit
event on every source video.

In the conversation, a completed call says how many clips it saved, and the
shape and framing when the shape changed, and shows them as a grid of stills
with their length, name, and ranges; selecting one opens the player in a
dialog. A failed clip's tile shows its reason. The moments card
has a checkbox per moment and **Cut N Clips**, which sends the person's own
turn: "Cut these moments from `<video>` into separate clips", then each
chosen moment's times. Titles and reasons come from a model watching
untrusted video, so they never go into that message. The button is disabled
while the conversation can't take a turn. Tool rows send turns through
`ConversationActionsContext`, which the conversation route provides.

## Long media calls

Video calls run inside the tool call, under an explicit tool `timeout`. The
run's lease heartbeat continues during the call, and
`AGENT_RUN_MAX_DURATION_SECONDS` bounds the whole continuation:

| Work | Tool timeout |
|---|---|
| A Google model call over video (generation, edits, understanding) | `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` (600 s): 300 s for the model call plus the Files API's 300 s processing wait |
| A renderer operation | `MEDIA_RENDERER_TIMEOUT_SECONDS` plus the client's 60 second allowance (`REQUEST_ALLOWANCE_SECONDS`) |
| `transcribe_video` | The renderer operation's timeout plus 900 seconds for transcription |
| `find_video_moments` | `transcribe_video`'s timeout plus `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS`, because a first call transcribes too |
| `ask_video` | `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` |

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
such as `clips`. A video tool that returns that shape needs no presenter of
its own to show its videos.

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

On GCP, `deploy/gcp/deploy.sh` deploys `praxis-media-renderer` as a gen2
Cloud Run service with one request per instance. It scales to zero, and its
request timeout is 60 seconds above `MEDIA_RENDERER_TIMEOUT_SECONDS`. The
deployment has no VPC, so ingress is `all`; Cloud Run IAM is the caller check,
and only the API and worker service accounts hold `roles/run.invoker`. The
renderer's own service account has no roles. For sizing, cost, and staging
expiry, see the
[GCP deployment guide](../../deploy/gcp/README.md#media-renderer).

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
| Isolation self-check | Verified locally in Docker and on Cloud Run gen2 | Unverified. The runtime must let an unprivileged process set `no_new_privs` and install a seccomp filter, and run the renderer as its container's first process. |

The repository has no Azure or AWS deployment tooling. Until a deployment has
a staging adapter, `settings.media_renderer_available` is false and video
stays refused in chat.

Locally, set `MEDIA_RENDERER_URL=http://127.0.0.1:8090` and
`MEDIA_RENDERER_AUTH=none` in `apps/api/.env`, and `make dev` starts the
renderer on `127.0.0.1:8090`. See [Local development](local-development.md).
Uploading a video to **Files** runs the probe, so the File moving from
**Processing** to ready confirms the renderer works end to end. With an
`OPENAI_API_KEY`, `transcribe_video` then transcribes it through `whisper-1`,
because local storage can't give Chirp 3 a `gs://` URI.

## Verification

`make media-renderer-check` builds the renderer's test image and runs its tests
on Linux in Docker. They kill processes, so they refuse to run outside that
container. CI runs the same target, with the renderer's lint and a production
image build. API client tests are in `apps/api/tests/services/media/`.
