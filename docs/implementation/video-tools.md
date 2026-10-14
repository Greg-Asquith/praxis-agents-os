# Video tools

Read this before changing the media renderer, its API client, or anything that
decodes, cuts, or measures video. For upload limits and video in chat, see
[Storage and files](storage-and-files.md#video-uploads-and-attachments).

The agent has four video tools. Each is hidden when its dependencies are
missing, rather than failing at call time:

| Tool | Needs | Effect |
|---|---|---|
| `transcribe_video` | Renderer and a transcription provider | Saves an SRT File |
| `find_video_moments` | Renderer and Google | Read only |
| `ask_video` | Google | Read only |
| `cut_video_clips` | Renderer | Saves video Files |

The renderer is available (`settings.media_renderer_available`) when
`MEDIA_RENDERER_URL` is set and storage is `gcs` or `local_fs`. Google means
`VIDEO_UNDERSTANDING_MODEL` is usable on either Google transport. No video
tool is code-eligible.

## Media renderer

ffmpeg parses attacker-controlled media, so it never runs in the API or worker.
It runs in the media renderer, a separate service:

- `apps/renderer/driver/` is the shared driver: a stdlib-only HTTP server,
  signed URL transfers, the child launcher, the seccomp filter, resource
  limits, and the start-up self-check. Other renderers can reuse it with
  their own image.
- `apps/renderer/media/` holds the ffmpeg operations and the image. The image
  builds a pinned ffmpeg from source with only the demuxers, decoders,
  encoders, and filters the operations use, plus `libx264`, `libopus`, AAC,
  and `libass`. Network protocols are compiled out, and the build fails if
  any remain. The image also holds headless OpenCV with the YuNet face
  detection model for automatic framing, and the caption fonts in
  `media/fonts.lock` (16 Google Fonts families, each file pinned by hash),
  with DejaVu as the fallback for other scripts.

One request runs one typed operation:

| Operation | Arguments | Outputs |
|---|---|---|
| `probe` | none | none; duration, dimensions, frame rate, codecs, audio, rotation |
| `scene_cuts` | `threshold` (0.05 to 0.95), optional range, `max_cuts` | none; cut times in milliseconds |
| `cut` | `segments` (1 to 10 `[input, start_ms, end_ms]`), `width` and `height` (even, 64 to 3840), `fps` (24 to 60), `fit`, optional `reframe`, `shot_cuts` (up to 500), `keep` (up to 500 `[segment, first_frame, end_frame]`), `captions`, `transitions` (one `[style, duration_ms, audio_curve]` per join), `fade_in_ms` and `fade_out_ms` (0 to 3000) | one H.264 and AAC MP4 |
| `extract_audio` | optional range, `chunks` (1 to 32) | one mono 16 kHz Ogg Opus file per chunk, with its range |
| `frames` | `times_ms` (1 to 20), `max_edge_px` (64 to 1920) | one JPEG per time |

Arguments are numbers, booleans, and names from fixed lists (transition
styles and audio curves). The driver rejects unknown fields and wrong types,
checks every name against its own list, and builds every ffmpeg argument
itself. A range must start before the end of the video; an end past it is
trimmed. A frame time must be strictly before the end. Every operation,
`probe` included, downloads each whole input, because container metadata can
sit anywhere in the file.

`extract_audio` splits the range into near-equal chunks. Each split moves into
the longest silence (below -35 dB for at least 0.3 s) within 10% of a chunk's
length of the even split. Chunks are re-encoded from one extraction, so each
starts exactly at its reported time. Opus is used because Chirp 3 returns
nothing for AAC.

`cut` behaves as follows:

- **Inputs:** one signed input per distinct source, numbered from 0; every
  input must be used.
- **Normalising:** each segment is turned upright, scaled to the output size
  (centre-cropped to fill, or with `fit`, the whole frame over a blurred copy
  of itself), resampled to `fps`, and given 48 kHz stereo audio (silent when
  the source has none), so mixed sources join cleanly. Each segment's video
  and audio last exactly its frame count.
- **Encoding:** `libx264` at CRF 18, capped at 8 Mbit/s, with AAC at
  128 kbit/s: about 61 MB a minute at most. Each segment's decoder uses two
  threads, so ten segments stay inside the child's memory limit.
- **`reframe`** (not with `fit`): for each segment whose shape differs from
  the output, ffmpeg samples raw frames at 2 fps, `media/faces.py` runs YuNet
  on them in its own isolated child, and `media/reframe.py` plans a crop per
  shot (split at `shot_cuts`). The crop starts on the largest face, holds
  while that face stays in its middle third, and pans for 400 ms when it
  leaves, never across a cut. A shot with no face is centred. The driver
  checks the faces' shape and writes the crop as a `crop` filter expression
  built from numbers. OpenCV never reads a media file. Choosing the active
  speaker when several people are in frame is pending.
- **`keep`:** per segment, the output frames to keep. Audio is cut into
  frames one video frame long, so `select` and `aselect` pick the same
  indices and stay in sync.
- **`captions`:** one extra input after the videos, an ASS file the API
  built. The renderer accepts only its `[Script Info]`, `[V4+ Styles]`, and
  `[Events]` sections, caps it at 4 MiB, and burns it in with the `ass`
  filter inside the isolated child.
- **`transitions`:** one entry per join, or none for hard cuts. A style is
  one of the 58 `xfade` transitions in the pinned ffmpeg (not `custom`,
  which takes an expression) or `none`; a curve is one of the 24
  `acrossfade` curves. A transition of 100 to 3000 ms overlaps the end of one
  segment with the start of the next, so the clip is shorter by each overlap,
  and can't be longer than either segment. A renderer test checks both lists
  against the pinned ffmpeg's help output.
- **Fades:** `fade_in_ms` and `fade_out_ms` fade the finished clip, captions
  included, from and to black and silence.

### Isolation

Each native command runs as a child of the driver:

- **Before exec:** `RLIMIT_AS` (`RENDERER_CHILD_MEMORY_BYTES`), `RLIMIT_CPU`,
  `RLIMIT_FSIZE` (the output limit), `RLIMIT_NPROC`, and `RLIMIT_CORE=0`, then
  `no_new_privs` and the seccomp filter. The filter kills other architectures
  and x32 calls, allows only `AF_UNIX` sockets, and returns `EPERM` for
  io_uring, ptrace, and `process_vm_readv`/`writev`.
- **Environment:** only `HOME`, `TMPDIR`, `PATH`, and `LANG`. The driver is
  non-dumpable, so a child can't read its memory or `/proc/<pid>/environ`.
- **After each request:** the driver kills the child's process group, then
  every other process under its user with `kill(-1, SIGKILL)`, which the
  kernel applies atomically against fork. It checks that none is left and
  deletes the request's directory. If a process survives, the driver exits
  and Cloud Run starts a clean instance.
- **Fail closed:** on start, the driver refuses to run if an ancestor other
  than PID 1 shares its user, because `kill(-1)` would reach it. It then runs
  a probe child under the same limits and exits if that child can open an
  inet socket, call io_uring, ptrace its own child, or read the driver's
  environment. Because a host's own seccomp profile can also deny io_uring,
  tests prove each filter rule by evaluating the BPF program directly.

A child shares the driver's user, so it could kill the driver. That fails
only the current request, and Cloud Run replaces the instance.

### Transfers

The driver is the only part with network access. It transfers only URLs that
start with a prefix in `RENDERER_ALLOWED_URL_PREFIXES`
(`https://storage.googleapis.com/` on GCP), ignores proxy settings, and
refuses redirects. A request takes 1 to 10 inputs, together at most
`RENDERER_MAX_INPUT_BYTES`, because they share the instance's in-memory disk.

A request's `timeout_seconds` bounds the download, every child, and the
uploads. Transfers check the deadline between chunks, and one blocking read
or write waits at most 30 seconds, so a stalled transfer ends inside the
60 seconds of request headroom.

## API client

`apps/api/services/media/` calls the renderer:

- `run_media_operation(workspace_id, sources, operation, staged_inputs?)`
  takes the File revisions the caller resolved for the workspace, one per
  video input, then any files the API staged itself, such as captions
  (`stage_media_input`). It refuses the request if any revision is from
  another workspace or isn't a video, or any staged file is outside the
  workspace's staging prefix. It signs one download per input and one
  size-bounded staging upload per output, validates the result against the
  operation's schema, and trusts an output only when the staged object
  exists at the reported size. On any failure it deletes the staged objects.
- `save_media_output` copies a staged output into a new File inside the
  caller's transaction, without the bytes passing through API memory. It
  commits a `FileUpload` reservation, has the provider copy the object into
  the reservation's key (`import_staged_object`, pinned to the staged ETag),
  and checks the copy's size and streamed SHA-256 against the renderer's
  report. The reservation owns the bytes until the caller commits, so the
  upload sweeper removes them if it never does. Call
  `discard_staged_outputs` after commit, or leave the staged object to the
  one-day staging lifecycle rule.

Failures raise `MediaRendererError` with a stable code and a plain message.
The client settings are as follows:

| Setting | Default | Purpose |
|---|---:|---|
| `MEDIA_RENDERER_URL` | unset | Renderer base URL. Unset makes the renderer unavailable. |
| `MEDIA_RENDERER_AUTH` | `google_id_token` | `google_id_token` for Cloud Run IAM, `shared_secret` for a renderer on a private network, or `none` (local only). |
| `MEDIA_RENDERER_SHARED_SECRET` | empty | At least 32 characters with `shared_secret`. The renderer holds the same value as `RENDERER_SHARED_SECRET`. |
| `MEDIA_RENDERER_TIMEOUT_SECONDS` | `900` | Total time one operation can take, transfers included. The client waits 60 seconds more (`REQUEST_ALLOWANCE_SECONDS`). |
| `MEDIA_RENDERER_MAX_OUTPUT_BYTES` | `2147483648` | Largest file one operation can write (2 GiB). |
| `MEDIA_STAGING_URL_TTL_SECONDS` | `1800` | Lifetime of the renderer's signed URLs; at least the timeout plus 60 seconds. |
| `MEDIA_RENDERER_LOCAL_STORAGE_URL` | `http://host.docker.internal:8000` | Local only: the API origin as the renderer container reaches it. |

## Video probe

The renderer's `probe` operation measures each workspace video revision once,
in the background. `queue_video_probe` (`services/files/`) runs wherever a
revision becomes a File's current revision. Unless the File isn't a workspace
video or the renderer is unavailable, it marks the File `pending` and
enqueues a `video.probe` job. The `probe_video` handler stores the result in
the revision's `media_metadata` (`VideoMetadata` in
`services/files/domain.py`). A restore copies the measurement from the
revision it restores.

| Outcome | File | Retried |
|---|---|---|
| Measured, with a video stream, within `VIDEO_MAX_SOURCE_DURATION_SECONDS` (default 4 hours) | `ready` | No |
| No video stream, too long, unreadable, or over the renderer's limits | `error`, with a plain reason | No |
| Renderer unreachable, timed out, or another renderer failure | `error` until the next attempt | Up to 3 attempts |

The job's timeout is `MEDIA_RENDERER_TIMEOUT_SECONDS` plus 120 seconds. Tools
read duration and size from `media_metadata` and never probe inline.

## Gemini video input

Tools hand workspace video to Gemini with `load_workspace_video_input`
(`services/agents/runtime/tools/media_inputs.py`). It resolves the current
revision the caller can see, then picks the input by transport:

| Transport | Input | Limit |
|---|---|---|
| Vertex, GCS storage | `VideoUrl` with the revision's `gs://` URI | The model's own limits |
| Gemini API (`GOOGLE_API_KEY`) | Inline up to the tool's bound, otherwise a Files API upload | 2 GB per file, kept 48 hours |
| Vertex, other storage, or a platform File | Inline `BinaryContent` | The tool's `inline_max_bytes` (18 MiB for video tools) |

`VideoInputOptions` sets the frame rate, start and end offsets, and media
resolution. The server builds every URI from the revision's object key and
refuses a key outside the caller's workspace. A model never supplies a URI,
bucket, or object name.

On Vertex, `StorageProvider.model_input_uri` returns a URI only for
workspace objects on GCS. GCP bootstrap grants the Vertex AI service agent
`roles/storage.objectViewer`, conditioned on bucket names starting with
`WORKSPACE_BUCKET_PREFIX`, so Gemini can read any workspace bucket in the
project; the URI the server builds is the isolation boundary.

On the Gemini API, `services/gemini_files` streams the object to the Files
API in 8 MiB chunks, waits up to 5 minutes for it to become `ACTIVE`, and
returns its name, URI, and expiry. The caller caches them on the revision
(`file_revisions.gemini_file_*`) and reuses the upload while it has at least
an hour left. A replaced or purged revision's upload is deleted, best effort;
Google deletes anything missed after 48 hours. One API key serves the
deployment, so the cached name is read back only from the revision the tool
resolved for the caller. Each upload records a `gemini_files_upload` audit
event on the File, committed before the model call. Two concurrent first
uploads of one revision both succeed; the later one is cached.

## Transcripts and shot cuts

A video revision's transcript and shot cuts are derived on first need and
kept with the revision, set once like `media_metadata`:

- `get_video_transcript` extracts the audio with `extract_audio`, transcribes
  the chunks concurrently (4 at a time, 16 for Gemini), moves each chunk's
  words onto the video's timeline, clamped to the chunk, and stores the
  result as JSON under the File's key prefix
  (`file_revisions.transcript_object_key`). Sentences end at `.`, `?`, or
  `!`, a change of speaker, or a 2-second pause. A stored transcript is
  reused whatever provider or language a later call asks for, so a revision
  is transcribed and billed once. Two concurrent first transcriptions both
  reach the provider, and the later save fails.
- `get_video_shot_cuts` stores the renderer's `scene_cuts` times
  (`file_revisions.shot_cuts_ms`).

Purging a File deletes the transcript object, and Files usage counts it.

The provider is the first one the deployment has, in this order:

| Provider | When | Chunk limit | Notes |
|---|---|---|---|
| Chirp 3 (`chirp_3`) | Vertex (`GOOGLE_VERTEX_AI`) with GCS storage | 19 minutes | `BatchRecognize` in `VIDEO_TRANSCRIPTION_SPEECH_LOCATION` (`eu` or `us`, default `eu`) reads the staged chunk by `gs://` URI, with word timings, punctuation, and speaker labels that restart with each chunk. A language without a region, such as `en`, is sent as `auto`. |
| `whisper-1` | `OPENAI_API_KEY` | 60 minutes and 25 MB | Receives the chunk bytes. Punctuation comes from the response text. No speaker labels. |
| Gemini 3.8 Flash | Google on either transport | 8 minutes | Receives the chunk bytes and answers with structured words and speaker letters. Its word times are about a second out at p95, so it comes last. |

With none of them, `transcribe_video` is hidden. Each transcription records a
`video_transcription` usage event with the audio length; see
[AI usage](ai-usage.md) for pricing. On GCP with `GOOGLE_VERTEX_AI=true`,
bootstrap enables the Speech-to-Text API and grants the API and worker
service accounts `roles/speech.client`. Speech reads the staged audio as its
own service agent.

## Tools

### Transcription

`transcribe_video(file_id, language?)` takes the current revision of one of
the workspace's own videos once its probe has finished. It writes
`<video name> transcript.srt` (one SubRip cue per sentence) in the video's
[output folder](#output-folders); calling it again adds a revision to that
File. It returns the File, word count, language, provider, and the first
eight sentences with `MM:SS` times as an untrusted-content node. A new
transcription records a `video_transcription` audit event on the video File
with the provider and model, committed before the transcript File is written.

### Moments and questions

Both send the video to `VIDEO_UNDERSTANDING_MODEL` through the shared
[Gemini video input](#gemini-video-input) at 1 frame a second.
`services/media/watch_video.py` runs the calls, at most three at a time,
under one `video_understanding` usage event. Each call records a
`video_understanding` audit event on the video File with the model and the
range, committed before the model call. Where Gemini can't read long video,
a video over 18 MiB is refused before transcription or any model call.

Both take an optional `start` and `end` (`MM:SS` or `H:MM:SS`), sent as the
part's offsets. Gemini gives times from the start of the full video, so
times need no shifting. `detail` raises the frame rate to 5 for fast action
and covers at most a fifth of a window, so a call's frame count stays the
same.

`find_video_moments(file_id, brief, count?, min_seconds?, max_seconds?,
start?, end?, detail?)` returns up to `count` (default 5, at most 10)
moments, best first. Each has validated `start_ms`, `end_ms`, `score` (0 to
100), and `shot_count`, and the model's `title`, `hook`, and `reason`, plus
the transcript excerpt, each as an untrusted-content node:

1. It loads the transcript, creating it if missing (a video with no audio has
   none), and the shot cuts.
2. A range longer than `VIDEO_MOMENTS_WINDOW_SECONDS` is split into the
   fewest equal windows that overlap by 60 seconds. Each window's prompt
   carries the brief, the length bounds, and that window's transcript lines,
   framed as untrusted content.
3. Unreadable times are dropped, and each range is clamped to its window.
4. `services/media/snapping.py` snaps each range to whole sentences: a start
   inside a sentence moves back to its start, and a start in a pause moves on
   to the next sentence; ends move the opposite way. A moment shorter than
   `min_seconds` runs on to the first sentence end that makes it long enough,
   and a moment outside the bounds is dropped. Each cut then moves to a shot
   change within `VIDEO_SNAP_SHOT_TOLERANCE_MS` if the range still fits.
5. Of two overlapping moments, the higher score is kept.

When fewer moments survive than asked for, the result says so in `note`.

`ask_video(file_id, question, start?, end?, detail?)` answers one question
with `MM:SS` references, as an untrusted-content node. One call covers at
most `VIDEO_MOMENTS_WINDOW_SECONDS`, at medium media resolution up to 10
minutes and low beyond that. It doesn't read the transcript.

| Setting | Default | Purpose |
|---|---:|---|
| `VIDEO_UNDERSTANDING_MODEL` | `gemini-3.8-flash` | Google catalogue model that watches the video. |
| `VIDEO_MOMENTS_WINDOW_SECONDS` | `2400` | Longest stretch one call watches (300 to 3600). |
| `VIDEO_SNAP_SHOT_TOLERANCE_MS` | `700` | How far a snapped cut can move to a shot change (0 to 3000). |

### Clips

`cut_video_clips(clips, aspect_ratio?, framing?, captions?, caption_style?,
remove_silences?, transition?, folder?)` renders up to five clips and saves
each as a new video File. It is an internal write, `auto` by default. Its
arguments are as follows:

- **Segments:** each clip has 1 to 10 `segments`, joined in order, from one
  or several of the workspace's own videos. A segment is a `file_id` with
  optional `start_ms` and `end_ms`; omitting both takes the whole video. An
  optional `name` names the File; otherwise it is named from the first video
  and range, such as `Talk 0.41-1.10.mp4`.
- **Snapping:** `snap` (default true) applies `find_video_moments`' snapping
  without its length bounds. A move of a second or more comes back as a
  warning. The first snap on a video transcribes it and measures its shots; a
  video with no audio, or no transcription provider, snaps to shots only.
- **Shape:** `aspect_ratio` is `original` (the first video's upright shape),
  `9:16`, `1:1`, `4:5`, or `16:9`, at 1080 pixels on the short side, at the
  first video's frame rate rounded into 24 to 60. `framing` is `auto` (the
  default, renderer `reframe`), `center`, or `fit`.
- **`remove_silences`:** off by default, and the agent is told to leave it
  off unless asked, because it makes jump cuts. It cuts every pause longer
  than 600 ms between words, leaving 150 ms beside speech. A segment with no
  words keeps every frame.
- **Captions:** `captions` is `none` (the default), `bold`, `clean`, or
  `highlight` (the spoken word coloured and enlarged). `caption_style`
  overrides any part of the preset: font (one of the bundled families), size,
  weight, capitals, colours (`#RRGGBB`), outline, shadow, box, words per
  caption, lines, `position` (`top`, `middle`, `lower`), and margin. On a
  vertical frame the default margins keep clear of Reels, Shorts, and TikTok
  controls.
- **Transitions:** a `transition` is `{style, duration_ms?, audio_curve?}`.
  The most specific wins: a segment's `transition_in`, then the clip's
  `transition`, then the call's. The duration defaults to 400 ms (500 ms for
  `fadeblack` and `fadewhite`), and the curve to `tri`. Each clip can also
  take `fade_in_ms` and `fade_out_ms` (0 to 3000). The agent is told to add
  them only when asked.
- **Text overlays:** each clip takes up to five `text_overlays`: `text` (1 to
  200 characters), a `preset` (`bold`, `clean`, or `title`), `style`
  overrides (caption options plus `align` and up to 4 lines), timing, and
  `fade_in_ms` and `fade_out_ms` (0 to 1000). With no times, an overlay
  shows for the whole clip. `start_ms` and `end_ms` alone are clip times;
  with `segment` (numbered from 1), they are times in that segment's video,
  mapped through the same timeline as captions. Overlays sit at the `top` by
  default, on a layer above the captions, and one at the captions' edge moves
  past the tallest cue with a warning.
- **`folder`:** names the output folder, created in the caller's workspace if
  needed. Otherwise clips go in the first segment's video's
  [output folder](#output-folders).

The API builds the clip's ASS file (`services/media/captions.py`) on the
clip's timeline from each segment's transcript words, shifted by the
segment's offset and any pauses removed before them. Captions and overlays
share one resolver, wrapping, and escaping (`TextStyle`). Words come from
untrusted audio and overlay text from the agent, so control characters are
dropped and `\`, `{`, and `}` are replaced; no text can add an override tag
or line break. The API wraps lines to a bound derived from the frame width
and the font's measured glyph width, because libass never wraps. A cue breaks
at a sentence end, a speaker change, a 700 ms pause, or its word or line
limit.

Exact word times matter for some options. `highlight` and `remove_silences`
are refused when a video's transcript came from Gemini. A video without
audio is left uncaptioned, and a clip with no speech reports it.

Each side of a transition extends by half its duration into the surrounding
footage, so the blend sits over the cut and doesn't eat snapped words. At a
video's start or end there is nothing to extend into, so the blend takes the
segment's own edge, with a warning unless the segment is a whole video.
Captions switch to the next segment's words halfway through a blend.

The call fails with a reason before anything renders when:

- A segment lies outside its video.
- A transition is longer than half of either segment it joins (after
  removing pauses), or a fade is longer than the clip.
- An overlay's times fall outside its clip or segment, it ends before it
  starts, its fades exceed it, or its text needs more lines than allowed.
- A clip would exceed `MEDIA_RENDERER_MAX_OUTPUT_BYTES` or
  `MAX_FILE_SIZE_SOURCE_VIDEO` at the renderer's bitrate caps (about 35
  minutes by default).

Clips render three at a time. One clip failing doesn't stop the others. Each
saved clip stores the renderer's probe on its revision, so it is ready at
once. The result reports every clip with its status, ranges, warnings, and
any failure reason, and the call fails only when no clip is saved. Each call
records a `video_clips` audit event on every source video.

### Output folders

Files made from a video go in one folder per original video, named after the
video without its extension (`Talk` for `Talk.mp4`, with a numeric suffix on
a name clash) and linked by `file_folders.source_file_id`.
`ensure_source_file_folder` resolves it:

- A video inside another video's folder, such as an earlier clip, is itself
  derived, so its outputs join that folder.
- Otherwise the live folder linked to the video is reused, or created and
  audited as a `file_folder` create by the agent. A partial unique index
  keeps one live folder per video. Renaming the folder keeps the link;
  deleting it means the next output creates a new one.

## Long media calls

Video calls run inside the tool call under an explicit tool `timeout`. The
run's lease heartbeat continues during the call, and
`AGENT_RUN_MAX_DURATION_SECONDS` bounds the whole continuation:

| Tool | Timeout |
|---|---|
| `generate_image_from_video`, `ask_video` | `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` (600 s): 300 s for the model call plus the Files API's 300 s processing wait |
| `transcribe_video` | One renderer operation (`MEDIA_RENDERER_TIMEOUT_SECONDS` plus 60 s) plus 900 s for transcription |
| `find_video_moments` | `transcribe_video`'s timeout plus `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` |
| `cut_video_clips` | `transcribe_video`'s timeout, plus one renderer operation for shot cuts, plus one per round of three clips |

When a timeout passes, Pydantic AI cancels the call and returns a retry to
the model. Tools write their output File only after the provider returns, so
nothing is saved. Cancelling the request doesn't stop a provider billing work
already running.

`run_code` counts time spent in nested calls against its 60-second budget,
so video tools aren't code-eligible. A tool that needs several outputs does
the work concurrently inside one call.

A long call reports its stage with a `tool.progress` stream event, emitted
through `ctx.deps.sink` with the call's `tool_call_id` and a short Title Case
`stage` (at most 80 characters), such as `Preparing Video`. The event is live
only; the client shows the latest stage on the running tool row.

The runtime never runs a tool call twice: an interrupted call gets an
interrupted return, and recovery evidence lists uncertain actions, so a
completed paid call isn't repeated on resume.

## Video in the conversation

Any completed tool result that names a video File (`file_id` and a
`video/*` `media_type`, at the top level or in a list such as `clips`) gets a
video row, unless a more specific presenter claims it first
(`video-tool-presenter.tsx`). Each video plays from a signed preview URL with
its duration, upright dimensions, details, and download. The row reads the
File itself, so it shows "Preparing video" during the probe and the
processing error if it fails. The player keeps its first signed URL, which
lasts 10 minutes, because a refetch would restart playback.

The tool rows add the following:

- **`find_video_moments`:** the source video and its moments; selecting one
  plays that range with a `#t=start,end` fragment. **Cut N Clips** sends the
  person's own turn naming the video and the chosen moments' times, never
  the model's titles or reasons. Tool rows send turns through
  `ConversationActionsContext`, and the button is unavailable while the
  conversation can't take a turn.
- **`ask_video`:** the range it watched, with the question and answer.
- **`cut_video_clips`:** a grid of stills with each clip's length, name,
  ranges, fades and transitions in play order, and overlay text and times,
  plus a link to the output folder. Selecting a clip opens a player; a failed
  clip shows its reason.

In the composer, a video attachment shows its upload percentage, then
"Preparing video", then its duration and dimensions. The person can send once
the upload is confirmed.

## Deployment

On GCP, `deploy/gcp/deploy.sh` deploys `praxis-media-renderer` as a gen2
Cloud Run service with one request per instance, scaling to zero, behind
Cloud Run IAM. For identity, access, sizing, cost, and staging expiry, see
the [GCP deployment guide](../../deploy/gcp/README.md#media-renderer).

Cloud Run's file system is memory, so the instance must hold the inputs (up
to `MAX_FILE_SIZE_SOURCE_VIDEO`, which also bounds uploads and worker reads),
one output, and `RENDERER_CHILD_MEMORY_BYTES`. The deploy script checks this,
and rejects media settings the API would refuse at startup.

### Other clouds

The renderer image, its request protocol, and the API client don't depend on
GCP. Each deployment supplies the following:

| Need | GCP | Azure and AWS |
|---|---|---|
| Staging uploads (`create_signed_staging_upload`) | GCS signs a size range | Pending. Azure SAS and S3 presigned `PUT` can't sign a range, so their adapters can rely on the API's stored-size check. |
| Caller authentication | Cloud Run IAM with `google_id_token` | `shared_secret` on private ingress, such as Container Apps internal ingress or a private ECS or App Runner service. |
| Staging expiry | Bootstrap's one-day lifecycle rule on `platform/media-staging/` | Pending: a lifecycle rule on the same prefix. |
| Large source uploads | Signed direct upload, up to `MAX_FILE_SIZE_SOURCE_VIDEO` | S3 caps a single `PUT` at 5 GiB. Azure relays person uploads through the API, so they keep `MAX_FILE_SIZE_VIDEO`; renderer outputs aren't held to that. |
| Isolation self-check | Verified in Docker and on Cloud Run gen2 | Unverified. The runtime must let an unprivileged process set `no_new_privs` and install a seccomp filter, and run the renderer as its container's first process. |

The repository has no Azure or AWS deployment tooling. Without a staging
adapter, the renderer is unavailable and video stays refused in chat.

### Local development

Set `MEDIA_RENDERER_URL=http://127.0.0.1:8090` and `MEDIA_RENDERER_AUTH=none`
in `apps/api/.env`; `make dev` then starts the renderer. See
[Local development](local-development.md#media-renderer). Uploading a video
to **Files** runs the probe, so the File moving from **Processing** to ready
confirms the renderer works. With an `OPENAI_API_KEY`, `transcribe_video`
uses `whisper-1`, because local storage can't give Chirp 3 a `gs://` URI.

## Verification

`make media-renderer-check` builds the renderer's test image and runs its
tests on Linux in Docker. They kill processes, so they refuse to run outside
that container. CI runs the same target, with the renderer's lint and a
production image build. API client tests are in
`apps/api/tests/services/media/`.
