# Video tools

Read this before changing the media renderer, its API client, video
generation, or anything that decodes, cuts, or measures video. For upload limits and video in chat, see
[Storage and files](storage-and-files.md#video-uploads-and-attachments).

The agent has five video tools. Each is hidden when its dependencies are
missing, rather than failing at call time:

| Tool | Needs | Effect |
|---|---|---|
| `transcribe_video` | Renderer and a transcription provider | Saves an SRT File |
| `find_video_moments` | Renderer and Google | Read only |
| `ask_video` | Google | Read only |
| `cut_video_clips` | Renderer | Saves video Files |
| `generate_video` | A catalogue video model this deployment can call | Paid; saves a video File |
| `edit_video` | A catalogue video model that edits, this deployment can call | Paid; saves the File's next revision |

The renderer is available (`settings.media_renderer_available`) when
`MEDIA_RENDERER_URL` is set and storage is `gcs` or `local_fs`. Google means
`VIDEO_UNDERSTANDING_MODEL` is usable on either Google transport. No video
tool is code-eligible.

## Media renderer

ffmpeg parses attacker-controlled media, so it never runs in the API or worker.
It runs in the media renderer, a separate service:

- `apps/isolation-driver/driver/` is the shared driver: a stdlib-only HTTP
  server, signed URL transfers, the child launcher, the seccomp filter,
  resource limits, and the start-up self-check. It's a library, not a
  service. Each service's Dockerfile copies it from a named build context
  (`--build-context driver=apps/isolation-driver`, or
  `additional_contexts` in Compose), so every service runs the same
  isolation code. `driver_testing/` holds the fake signed-URL storage and
  pytest fixtures that service test images reuse. `make
  isolation-driver-check` runs its tests on Linux in Docker. `serve` takes
  options for other services: a larger request cap, no transfers, and a
  toolchain check after the isolation self-check. The
  [data science service](data-science-service.md) uses all three.
- `apps/media-renderer/` holds the ffmpeg operations (`media/`) and the
  image. The image builds a pinned ffmpeg from source with only the
  demuxers, decoders, encoders, and filters the operations use, plus
  `libx264`, `libopus`, AAC, `libass`, and zlib (for PNG). Network protocols are compiled out, and the build fails if
  any remain. The image also holds headless OpenCV with the YuNet face
  detection model for automatic framing, and the caption fonts in
  `media/fonts.lock` (16 Google Fonts families, each file pinned by hash),
  with DejaVu as the fallback for other scripts.

One request runs one typed operation:

| Operation | Arguments | Outputs |
|---|---|---|
| `probe` | none | none; duration, dimensions, frame rate, codecs, audio, rotation |
| `scene_cuts` | `threshold` (0.05 to 0.95), optional range, `max_cuts` | none; cut times in milliseconds |
| `cut` | `segments` (1 to 10 `[input, start_ms, end_ms]`, or `[-1, 0, duration_ms]` for a card), `width` and `height` (even, 64 to 3840), `fps` (24 to 60), `fit`, optional `reframe`, `shot_cuts` (up to 500), `keep` (up to 500 `[segment, first_frame, end_frame]`), `captions`, `transitions` (one `[style, duration_ms, audio_curve]` per join), `fade_in_ms` and `fade_out_ms` (0 to 3000), `speed_percents` (50 to 200), `freeze_end_ms` (0 to 3000), and `zooms` (`[from, to]`, 100 to 150), one per segment, `punch_ins`, `enhance_voice`, `normalize_loudness`, `music` with `music_volume` (0 to 100), `music_duck`, `music_start_ms`, `music_fade_in_ms`, and `music_fade_out_ms` (0 to 3000), `remove_black_bars`, `logo` with `logo_position`, `logo_size` (8 or more pixels), `logo_margins` (`[x, y]`), and `logo_opacity` (10 to 100), `cards` (one `[colour, image]` per card) | one H.264 and AAC MP4, with its loudness when normalised and whether any segment had black bars removed |
| `extract_audio` | optional range, `chunks` (1 to 32) | one mono 16 kHz Ogg Opus file per chunk, with its range |
| `frames` | `times_ms` (1 to 20), `max_edge_px` (64 to 1920) | one JPEG per time |

Arguments are numbers, booleans, and names from fixed lists (transition
styles, audio curves, and logo positions). The driver rejects unknown fields and wrong types,
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
- **`remove_black_bars`:** for each segment, `media/black_bars.py` decodes
  five frames spread across it, joins them, and runs `cropdetect` once. The
  picture is the widest area any frame shows, so an all-black frame adds
  nothing. Bars count only on both opposite edges, at least 2% of the edge
  each, and the narrower of the two is removed from both, so a dark edge of
  the picture itself stays. A picture under 25% of an edge is treated as a
  dark scene and kept whole. The segment is cropped before framing, and
  `reframe` measures faces inside the crop. Detection takes about 0.14 s a
  segment on 1080p footage, so it isn't cached per revision.
- **`keep`:** per segment, the output frames to keep. Audio is cut into
  frames one video frame long, so `select` and `aselect` pick the same
  indices and stay in sync.
- **Zooms:** a segment's `zooms` entry enlarges the centre of the framed
  picture from one percent to the other across the segment's frames, and
  `punch_ins` makes every other `keep` range of a segment 10% closer (up to
  150% in all), so each jump cut changes the zoom. The `perspective` filter
  applies it after framing and before `keep`, with per-frame expressions of
  the frame number and sub-pixel sampling, so a slow push-in doesn't judder.
  The zoomed area is always inside the framed picture, so a zoom never shows
  the frame's edge or uncovers more of `fit`'s blurred fill. With `reframe`,
  the zoom centres on the crop that follows the face. `crop` can't change
  size per frame, and `zoompan` steps in whole source pixels.
- **Speed and freezes:** after `keep`, a segment at another
  `speed_percents` value is retimed with `setpts` and resampled to `fps`, and
  its audio with one `atempo` filter, which keeps the pitch; both are padded
  and trimmed to the sped-up frame count. `freeze_end_ms` then holds the last
  frame with `tpad` and pads the audio with silence. Reverse playback isn't
  offered: ffmpeg's `reverse` holds the whole segment in memory.
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
- **`enhance_voice`:** cleans up each segment's sound before the join: an
  80 Hz high-pass, `afftdn` noise reduction (up to 12 dB below a -45 dB
  floor), a 3 dB presence lift at 3 kHz, and gentle compression
  (`media/audio.py`).
- **`normalize_loudness`:** brings the finished clip to -14 LUFS integrated
  and -1.5 dBTP, the level Reels, Shorts, and TikTok play at. The clip renders
  to a working file, a `loudnorm` pass measures its audio, and a second pass
  re-encodes the audio only (video copied) with the measured values in
  linear mode. `loudnorm` switches to its limiter when a linear gain would
  pass the peak ceiling. A clip below -70 LUFS, such as one from a video with
  no audio, is kept as it is and reports no loudness. The working file
  doubles the clip's space in the instance's memory until the second pass
  ends.
- **`music`:** mixes an audio input, after the videos and before any
  captions file, under the joined clip, so it plays straight through
  transitions (`media/music.py`). The track starts at `music_start_ms` and
  loops from its beginning (`-stream_loop`) until the clip ends. Its volume
  maps to gain as `(volume / 100)²`, so 50 is 12 dB under the track and the
  default 25 is 24 dB under. `music_fade_in_ms` and `music_fade_out_ms` fade
  the track alone. With `music_duck`, `sidechaincompress` keyed on the speech
  compresses the music hard over -50 dBFS and blends a fifth of it back
  unchanged, which caps the drop near 14 dB. Speech at about -20 dBFS lowers
  the music by about 13 dB; speech at -40 dBFS lowers it by about 7 dB. The
  clip's fades then apply to the mix, and loudness normalisation measures it.
  The renderer refuses music options without `music`, a track with no sound,
  and a start past the track's end. MP3 and WAV inputs use their own
  demuxers; M4A uses `mov`.
- **`logo`:** places an image input, after any music and before any
  captions file, on the joined clip (`media/logo.py`). The image fits in a
  `logo_size` pixel square with its transparency kept, at `logo_position`
  (a corner, `top_center`, `bottom_center`, or `middle_center`),
  `logo_margins` in from the edges it names (a centred axis ignores its
  margin), at `logo_opacity` percent (`colorchannelmixer`). It's
  scaled once; `overlay` repeats its one frame to the end of the clip, so
  it sits through transitions, and the clip's fades apply to it. It's under
  the captions file, so text overlays show above it; the API keeps it clear
  of captions. The renderer refuses logo options without `logo` and a logo
  that doesn't fit inside the frame.
- **Cards:** a segment `[-1, 0, duration_ms]` (500 to 15000 ms) is a title
  or end card that reads no video (`media/cards.py`). `cards` lists one
  `[colour, image]` per card in order: the colour is an integer `0xRRGGBB`,
  and `image` 1 takes the next card image input, after any logo and before
  any captions file. The card is ffmpeg's `color` source at the output size
  and frame rate, with the image scaled to cover the frame, cropped to its
  shape, and overlaid on the colour so its transparent parts show it, and
  silence from `anullsrc`. It's exactly its frames long, so it joins,
  crossfades, and fades like any segment, and music, the logo, and burned-in
  text run over it. The renderer refuses a card with a speed, a freeze, a
  zoom, or removed frames, and a `cards` list that doesn't match the card
  segments. Framing, black bar removal, and face tracking skip cards.
- **Image inputs:** `media/images.py` checks an image before anything else
  in the cut runs. The file must be at most 20 MB. `ffprobe` detects its
  format from its content with only the `image_png_pipe`,
  `image_jpeg_pipe`, and `image_webp_pipe` demuxers, which read that one
  file and never a name pattern, and the stream must be the matching `png`,
  `mjpeg`, or `webp` decoder's. Both sides must be at most 4096 pixels, and
  every decoder runs with `-max_pixels` at 4096 squared, so a header that
  claims more is refused before its frame is allocated. ffmpeg then reads
  the image with the detected demuxer named explicitly. The `image2`
  demuxer, which reads files by name and can expand patterns, isn't built.

### Isolation

Each native command runs as a child of the driver:

- **Before exec:** `RLIMIT_AS` (`RENDERER_CHILD_MEMORY_BYTES`), `RLIMIT_CPU`,
  `RLIMIT_FSIZE` (the output limit), `RLIMIT_NPROC`, and `RLIMIT_CORE=0`, then
  `no_new_privs` and the seccomp filter. The filter kills other architectures
  and x32 calls, allows only `AF_UNIX` sockets, and returns `EPERM` for
  io_uring, ptrace, and `process_vm_readv`/`writev`.
- **Environment:** only `HOME`, `TMPDIR`, `PATH`, `LANG`, and
  `MALLOC_ARENA_MAX=2`, which stops glibc's per-thread arenas from scaling
  the reserved address space, and so `RLIMIT_AS`, with the host's core count.
  The driver is non-dumpable, so a child can't read its memory or
  `/proc/<pid>/environ`.
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

`apps/api/services/media/` calls the renderer. The HTTP post, auth header,
and error mapping are shared with the data science client in
`apps/api/utils/isolated_service.py`:

- `run_media_operation(workspace_id, sources, operation, staged_inputs?)`
  takes the File revisions the caller resolved for the workspace, one per
  media input, then any files the API staged itself, such as captions
  (`stage_media_input`). Each operation lists the File categories each
  source may be (`source_categories`): a video for every input, except an
  audio File for a cut's music, an image for its logo, and either video or
  audio for a probe. It refuses the request
  if any revision is from another workspace or isn't a category its position
  takes, or any staged file is outside the workspace's staging prefix. It signs one download per input and one
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

The renderer's `probe` operation measures each workspace video and audio
revision once, in the background. `queue_video_probe` (`services/files/`) runs
wherever a revision becomes a File's current revision. Unless the File isn't a
workspace video or audio File, or the renderer is unavailable, it marks the File `pending` and
enqueues a `video.probe` job. The `probe_video` handler stores the result in
the revision's `media_metadata` (`VideoMetadata` in
`services/files/domain.py`). A restore copies the measurement from the
revision it restores.

| Outcome | File | Retried |
|---|---|---|
| Measured, with a video stream (an audio stream for an audio File), within `VIDEO_MAX_SOURCE_DURATION_SECONDS` (default 4 hours) | `ready` | No |
| No video stream (no sound for an audio File), too long, unreadable, or over the renderer's limits | `error`, with a plain reason | No |
| Renderer unreachable, timed out, or another renderer failure | `processing` until the last attempt, then `error` | Up to 3 attempts |

The handler locks the File and checks that the probed revision is still its
current revision before each status write, so a probe for a replaced
revision stores its measurement but leaves the newer revision's status alone.
After the last attempt fails, including by timeout, the job's
`on_final_failure` hook marks the File `error`.

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
minutes and low beyond that. It doesn't read the transcript. The result's
`how_to_report` says the answer comes from sampled frames, so a fault it
describes at a transition or in a single frame is unconfirmed. In an owner
test a clean wipe between two white screens was described as a split-frame
tear.

| Setting | Default | Purpose |
|---|---:|---|
| `VIDEO_UNDERSTANDING_MODEL` | `gemini-3.8-flash` | Google catalogue model that watches the video. |
| `VIDEO_MOMENTS_WINDOW_SECONDS` | `2400` | Longest stretch one call watches (300 to 3600). |
| `VIDEO_SNAP_SHOT_TOLERANCE_MS` | `700` | How far a snapped cut can move to a shot change (0 to 3000). |

### Clips

`cut_video_clips(clips, aspect_ratios?, framing?, remove_black_bars?, captions?,
caption_style?, remove_silences?, punch_ins?, transition?, audio?, music?, logo?, folder?)` renders up to five clips and saves
each as a new video File. It is an internal write, `auto` by default. Its
arguments are as follows:

- **Segments:** each clip has 1 to 10 `segments`, joined in order, from one
  or several of the workspace's own videos. A segment is a `file_id` with
  optional `start_ms` and `end_ms`; omitting both takes the whole video. An
  optional `name` names the File; otherwise it is named from the first video
  and range, such as `Talk 0.41-1.10.mp4`.
- **Cards:** a segment can be `{card: {duration_ms?, background_color?,
  background_image?, text?}, transition_in?}`, a title or end card held in
  silence. `duration_ms` is 500 to 12000 (default 3000); the card grows by
  half of each transition beside it, so it shows whole for that long and
  stays inside the renderer's 15 s. `background_color` is `#RRGGBB`
  (default black). `background_image` is one of the workspace's own image
  Files, checked like a logo, scaled to cover the frame, with its
  transparent parts showing the colour. `text` is up to three text
  overlays, bound to the card, in the middle of the frame unless their
  style sets a position, with times from the card's start; they go through
  the same ASS file and escaping as every overlay. A clip needs at least one
  video segment; its name and folder come from its first video. Each clip
  reports a card segment as `card` (length, colour, and image File), and a
  card image gets the same `video_clips` audit event as the source videos.
- **Snapping:** `snap` (default true) applies `find_video_moments`' snapping
  without its length bounds. A move of a second or more comes back as a
  warning. The first snap on a video transcribes it and measures its shots; a
  video with no audio, or no transcription provider, snaps to shots only.
- **Shape:** `aspect_ratios` lists one to three shapes (default
  `["original"]`): `original` (the first video's upright shape), `9:16`,
  `1:1`, `4:5`, or `16:9`, at 1080 pixels on the short side, at the first
  video's frame rate rounded into 24 to 60. `framing` is `auto` (the
  default, renderer `reframe`), `center`, or `fit`.
- **Shapes:** each clip is planned and rendered once per shape, with the
  same transcript and shot cuts, so every shape snaps to the same cuts and
  differs only in framing and what depends on the frame size (caption and
  logo placement, black bars). A repeated shape renders once. The first
  shape keeps the clip's name; the others add the shape, such as
  `Talk 0.41-1.10 1x1.mp4` (`Original` for `original`). Every shape saves in
  the clip's folder, and the result has one entry per clip and shape, in
  clip order, each with `index` and `aspect_ratio`; `count`, `saved`, and
  `failed` count those Files. A clip can fail in one shape and save in
  another. The renderer's `cut` operation is unchanged: the API calls it
  once per shape.
- **Black bars:** `remove_black_bars` crops letterbox or pillarbox bars from
  each segment before it's framed, so the picture fills the new shape. Omitted,
  it's on for a clip when any of its videos' upright shape differs from the
  clip's by more than 1%, and off otherwise. Each clip reports
  `black_bars_removed`, which isn't kept in the clip's media metadata.
- **`remove_silences`:** off by default, and the agent is told to leave it
  off unless asked, because it makes jump cuts. It cuts every pause longer
  than 600 ms between words, leaving 150 ms beside speech. A segment with no
  words keeps every frame.
- **Captions:** `captions` is `none` (the default), `bold`, `clean`, or
  `highlight` (the spoken word coloured and enlarged). `caption_style`
  overrides any part of the preset: font (one of the bundled families), size,
  weight, capitals, colours (`#RRGGBB`), outline, shadow, box, words per
  caption, lines, `position` (`top`, `middle`, `lower`), margin, and
  `animation`. On a vertical frame the default margins keep clear of Reels,
  Shorts, and TikTok controls.
- **Animation:** captions and overlays take `animation` in their style:
  `none`, `pop` (scales in from 80% over 200 ms), `slide_up` (rises half a
  line into place while fading in), or `fade` (fades in over 200 ms).
  Captions also take `karaoke`, which fills each word from the text colour to
  `highlight_color` as it's spoken, with ASS `\kf` timed to the next word's
  start. `bold` captions and `bold` and `title` overlays pop by default;
  `clean` and `highlight` don't move. A highlight cue animates on its first
  word only, and repeats the entrance after the spoken word, whose style
  reset would end it. Every tag is built from numbers the API computed, in
  override blocks of its own, apart from the escaped text, so the renderer
  needs no change.
- **Transitions:** a `transition` is `{style, duration_ms?, audio_curve?}`.
  The most specific wins: a segment's `transition_in`, then the clip's
  `transition`, then the call's. The duration defaults to 400 ms (500 ms for
  `fadeblack` and `fadewhite`), and the curve to `tri`. Each clip can also
  take `fade_in_ms` and `fade_out_ms` (0 to 3000). The agent is told to add
  them only when asked.
- **Speed:** a segment's `speed` (0.5 to 2, default 1) plays it faster or in
  slow motion with voices at their natural pitch, and `freeze_end_ms` (0 to
  3000) holds its last frame in silence. Pause removal happens first, at the
  source's pace. Captions, overlays, transitions, and the clip's length follow
  the new timing. Each clip's segments report `speed` and `freeze_end_ms`. The
  agent is told to use them only when asked.
- **Zooms:** a segment's `zoom` (`{from_percent, to_percent}`, 100 to 150,
  `from_percent` 100 by default) pushes in slowly across it; the agent is told
  to use it only when asked. The call's `punch_ins: "auto"` (default `off`)
  zooms in to 110% on every other jump cut that `remove_silences` makes, which
  hides the jump; the agent is told to use it when the person wants punchier
  pacing. Without jump cuts the clip warns that it has no punch-ins and
  renders without them. Each clip reports `punch_ins`, and its segments their
  `zoom`.
- **Text overlays:** each clip takes up to five `text_overlays`: `text` (1 to
  200 characters), a `preset` (`bold`, `clean`, or `title`), `style`
  overrides (caption options plus `align` and up to 4 lines), timing, and
  `fade_in_ms` and `fade_out_ms` (0 to 1000). With no times, an overlay
  shows for the whole clip. `start_ms` and `end_ms` alone are clip times;
  with `segment` (numbered from 1), they are times in that segment's video,
  mapped through the same timeline as captions. Overlays sit at the `top` by
  default, on a layer above the captions, and one at the captions' edge moves
  past the tallest cue with a warning.
- **`audio`:** `{normalize, enhance_voice}` for every clip. `normalize`
  (default true) levels each clip to -14 LUFS; the clip result reports
  `loudness_lufs`, also stored in the revision's media metadata.
  `enhance_voice` (default false) reduces background noise and makes voices
  clearer; the agent is told to use it for phone, laptop, or room recordings
  when the person asks for clearer sound.
- **`music`:** `{file_id, volume?, duck?, start_ms?, fade_in_ms?,
  fade_out_ms?}` under every clip, or a clip's own `music` to override it.
  `file_id` must be one of the workspace's own audio Files (MP3, M4A, or WAV,
  probed like a video); a video, another workspace's File, or a published
  platform File is refused. `volume` defaults to 25, quiet under speech;
  `duck` (default true) lowers it while someone talks; `start_ms` is where in
  the track to start; `fade_out_ms` defaults to 1000. A clip's `music: "none"`
  leaves the call's track out of that clip. The track has to start
  inside its length, and its fades must fit the clip. There is no music
  library and no generated music: the agent is told to add music only when
  asked, and only a track the person gave it. A call with music returns
  `music_notice`, which says the person is responsible for the music's
  rights, and each clip reports its `music`. The music File gets the same
  `video_clips` audit event as the source videos.
- **`logo`:** `{file_id, position?, size_percent?, opacity?, margin_percent?,
  safe_zone?}`
  on every clip, or a clip's own `logo` to override it; a clip's
  `logo: "none"` leaves it out. `file_id` must be one of the workspace's own
  image Files (PNG, JPEG, or WebP) of at most 20 MB; a video, an audio File,
  another workspace's File, or a published platform File is refused.
  `position` is `top_left`, `top_center`, `top_right` (the default),
  `middle_center`, `bottom_left`, `bottom_center`, or `bottom_right`;
  `size_percent` (5 to 30, default 15) is the logo's longer side as a share
  of the frame's short edge; `opacity` is 10 to 100 (default 100);
  `margin_percent` (0 to 10, default 2) is extra space as a share of the
  short edge. With `safe_zone` (default true), the logo sits inside the same
  safe area as captions: on a vertical clip, 8% of the width in on the
  left, 16% on the right, 12% of the height from the top, and 24% from the
  foot; on other shapes, 6% of the width and 8% of the height. With
  `safe_zone: false`, only the margin keeps it from the edge; the agent is
  told to turn it off only when the person wants the logo close to the edge
  or the video isn't for Reels, Shorts, or TikTok. A centred logo is
  centred on the frame. With captions on its edge, it moves past their
  tallest block with the warning "The logo moved above the captions." (or
  below), safe zone or not; a `middle_center` logo with `middle` captions is
  refused with a reason. It's drawn under all burned-in text, not
  between captions and overlays, because it never overlaps the captions. The
  agent is told to add a logo only when asked, and only an image the person
  gave it. Each clip reports its `logo` (File, position, size, opacity, and
  safe zone),
  and the image File gets the same `video_clips` audit event as the source
  videos.
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

Exact word times matter for some options. `highlight`, `karaoke`, and
`remove_silences` are refused when a video's transcript came from Gemini. A video without
audio is left uncaptioned, and a clip with no speech reports it.

Each side of a transition extends by half its duration into the surrounding
footage, so the blend sits over the cut and doesn't eat snapped words. A
sped-up side extends twice as far into its video at 2x, and a freeze before
a transition counts towards its half. A transition can take at most half of
a segment's length at its speed. At a
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
once. The result reports every clip in every shape with its status,
ranges, warnings, and any failure reason, and the call fails only when
nothing is saved. Each call
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

### Generation

`generate_video` (`runtime/tools/video/generate_video.py`) makes one clip of
3 to 15 seconds, with sound, from a prompt. It asks for approval by default,
because every call is paid; an owner can switch it to automatic. Its
arguments are the prompt (up to 4,000 characters), `aspect_ratio` (`9:16`,
the default, or `16:9`), `duration_seconds` (default 8), `resolution`
(`720p`, the default, `1080p`, or `4k`), an optional catalogue `model`, and
an optional File `name` and `folder`. The approval card shows the model that
will run, with its price range a second and processing location, and every
setting is editable. Image and video references and `extend_video` are
pending (plan 250 C3).

The model comes from the media catalogue (`services/media/models.toml`, see
[native tools](native-tools.md#media-model-catalogue)): `DEFAULT_VIDEO_GENERATION_MODEL`
(`omni-1.2-flash`) when the agent names none. Each model's limits (shapes,
durations, resolutions) are checked before any call, and a route may price a
second by resolution (`usd_per_second_by_resolution`).

Backends implement `VideoBackend` (`services/media/generation.py`), chosen by
the catalogue route. `generate_video` and `edit_video` share the steps around
the paid request (`runtime/tools/video/generation.py`). A call runs in two
steps, so the provider's ID is recorded between them:

1. The tool commits a `media_generations` row (`requested`) keyed by run and
   tool call, then `start` (or `start_edit`) sends the one paid request.
2. The tool commits the provider's ID on the row (`running`), then `wait`
   polls until the clip is ready, for up to 900 seconds.
3. The clip is saved as a File in the conversation's folder (or the named
   one), the row becomes `saved` with the revision, and usage is metered.

A call that finds its own row `saved` returns that File, and one that finds
it `running` waits on the same provider ID, so a paid request is never sent
twice for one tool call. A row left at `requested` means the worker stopped
before Google answered; the call fails rather than pay again. A failed or
timed-out wait marks the row `failed` and meters one request with unknown
tokens, because Google may bill it. The table has forced row-level security
by workspace.

The saved revision carries its provenance in `file_revisions.generation`
(`GenerationProvenance`: route, catalogue and provider model, the provider's
ID, the task, a SHA-256 digest of the prompt or instruction, the shape,
resolution, and length, and for an edit the revision it changed). It's set once, with the revision. Files reports `ai_generated` for a
File whose current revision has provenance, and the Files table, the File
details, and the generation row show **AI-Generated**. The result also
returns the cost from the tokens Google reported, the model's own notes on
the prompt as untrusted content, and a reminder to check the clip with
`ask_video`. While it runs, the row is a collapsed loading card with the
stage, the clip's length, shape, and resolution, and how long it usually
takes.

### Editing

`edit_video` (`runtime/tools/video/edit_video.py`) changes one workspace MP4
by instruction and saves the result as the File's next revision, so the File
stays in its folder and the person can restore the old version from Files.
It asks for approval by default; an owner can switch it to automatic. Its
arguments are the File, the `instruction` (up to 4,000 characters),
`base_revision_id`, and an optional catalogue `model` (models with the
`edit_video` task; `DEFAULT_VIDEO_GENERATION_MODEL` when the agent names
none). The approval card shows the File, the full instruction (editable),
and the model. The File isn't editable on the card, because the base
revision belongs to it.

Before any paid request, the tool checks that the File is the workspace's
own video, that `base_revision_id` is its current revision, and that it's an
MP4 (a revision keeps the File's type, and Omni returns MP4). Then it picks
how Google gets the clip:

- **Chained:** when the current revision has provenance from the same route,
  the request names that revision's provider ID as `previous_interaction_id`
  and sends no video. This is any clip made or edited in Praxis.
- **Uploaded:** otherwise the tool reads the probe's duration and refuses a
  clip longer than the model's `max_input_seconds` (10 for Omni) or larger
  than `MAX_FILE_SIZE_VIDEO`, telling the agent to cut the shot with
  `cut_video_clips` first. It audits the read (`video_edit`) and sends the
  clip inline.
- If Google no longer holds a chained interaction (HTTP 404, unbilled), the
  same tool call uploads the clip instead, under the same limits.

The save appends a revision with `expected_current_revision_id` set to the
base, so a File changed during the edit saves nothing and the record is
marked `failed`. A call that finds its own record `saved` returns that
revision. The result has the revision ID and number, the base, the cost,
the model's notes as untrusted content, and the reminder to check with
`ask_video`. The row plays the clip, says **Saved As Version N**, and shows
the instruction; while it runs it's a collapsed loading card.

#### Omni

`services/media/omni.py` calls Omni 1.2 Flash (`gemini-omni-1.2-flash` on
both transports) through google-genai's Interactions API, on Vertex at the
`global` location or on the Gemini API. Omni is available on Vertex only when
`GOOGLE_VERTEX_LOCATION` is `auto` or `global`. The request is:

```json
{"model": "gemini-omni-1.2-flash", "input": "PROMPT",
 "response_format": {"type": "video", "aspect_ratio": "9:16",
                     "resolution": "720p", "duration": "8s"},
 "generation_config": {"video_config": {"task": "text_to_video"}},
 "store": true, "background": true}
```

An edit sends `response_format: {"type": "video"}` with either
`previous_interaction_id` and the instruction as `input`, or an `input` of a
`video` part (base64 MP4) and a `text` part with
`generation_config.video_config.task: "edit"`. Google refuses
`previous_interaction_id` alongside a task. On the Gemini API, Google
doesn't edit uploaded video from the EEA, Switzerland, or the UK; that
refusal returns a message suggesting a clip generated in Praxis or Vertex.

The client sends each request with SDK retries off, because a retried create is a
second paid clip, then polls the interaction every 5 seconds. Reads that fail
are retried up to five times in a row. A wait that passes its deadline, or a
call that's cancelled, asks Google to cancel the interaction. `store: true`
keeps the interaction on Google's side so a later edit can chain from it
(the operator's decision, 2026-11-17).

The clip comes back inline as base64 in `output_video.data`. Its size is
bounded by the request: about 0.56 MB a second at 720p, 0.89 MB at 1080p,
and 2.9 MB at 4K, so a 15 second 4K clip is about 44 MB. The client refuses
a body whose decoded size would pass `MAX_FILE_SIZE_VIDEO` before decoding
it. URI delivery needs a Cloud Storage bucket Google's service agent can
write to on Vertex, so it isn't used. Usage records Google's input tokens,
and video output plus thinking tokens as output, priced at the video rate.
A refusal Google marks as safety or policy returns a retry asking for a
revised prompt; other failures fail the call. Clips carry a C2PA manifest
and Google's SynthID watermark.

### Video skill and evals

The internal skill `runtime/internal_skills/video-creation-and-editing.md`
(**Video Creation & Editing**) holds the working rules: which tool to use,
starting from an attached video, agreeing the brief, finding moments before
cutting, the defaults for reels, text on screen, the finishing options, one
call for a set, checking clips with `ask_video` without overclaiming a fault
it can't see, cost, untrusted content, and reporting. Tool descriptions carry
the hard limits and point to it. Each tool slice that changes what an agent
can do with video updates the skill in the same change, never before the
tool exists. The `video_*` cases in `apps/api/evals/datasets/agent_behavior.yaml`
check that agents find moments before cutting, cut the returned ranges in one
`cut_video_clips` call rather than from `run_code`, report a glitch
`ask_video` describes at a transition as unconfirmed, fix a generated shot
with `edit_video` rather than a new generation, and cut a long filmed clip
before editing it.

## Long media calls

Video calls run inside the tool call under an explicit tool `timeout`. The
run's lease heartbeat continues during the call, and
`AGENT_RUN_MAX_DURATION_SECONDS` bounds the whole continuation:

| Tool | Timeout |
|---|---|
| `generate_image_from_video`, `ask_video` | `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` (600 s): 300 s for the model call plus the Files API's 300 s processing wait |
| `transcribe_video` | One renderer operation (`MEDIA_RENDERER_TIMEOUT_SECONDS` plus 60 s) plus 900 s for transcription |
| `find_video_moments` | `transcribe_video`'s timeout plus `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS` |
| `cut_video_clips` | `transcribe_video`'s timeout, plus one renderer operation for shot cuts, plus one per round of three renders (up to 15: five clips in three shapes) |
| `generate_video`, `edit_video` | 1,020 s: 900 s of polling plus time to start and save |

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
completed paid call isn't repeated on resume. `generate_video` and
`edit_video` also keep their own record of each paid call (see
[Generation](#generation)).

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
- **`cut_video_clips`:** the card's details show what the call applied to
  every clip: shapes, framing, captions, pauses, **Sound** (Levelled, Voice
  Cleaned Up), **Music** (the track, its volume, and Under Speech or
  Throughout), **Logo** (the File, its position, **Safe Zone Off** when off, and its
  opacity below 100%),
  and **Punch-In Zooms**. Below them, a grid of stills with
  each clip's length, name, ranges (a card shows as **Card (3 s)** or
  **Image Card (3 s)**), **Black Bars Removed** when it had any,
  and its own fades, transitions, speeds (such as **2× Speed**), freezes
  (**Freeze Frame 1 s**), and zooms (**Zoom 100% to 120%**) in play order, then **No Music** or **Different Music**
  where its music differs from the call's, **No Logo** or **Different Logo**
  where its logo does, and overlay text and times, plus
  a link to the output folder and the music rights notice. The effects line
  wraps rather than truncating. A clip cut in several shapes has one tile
  with a toggle of its shapes (such as **9:16** and **1:1**) that switches
  the still, player, name, and warnings; a shape that failed shows in red
  with its reason. The summary reads **3 Clips in 2 Shapes**, or **5 of 6
  Videos Saved**. Selecting a clip opens a player; a failed clip shows its
  reason.
- **`cut_video_clips` approval:** the tool is automatic by default; when an
  owner sets it to ask first, the approval card shows shapes, framing,
  captions, and folder, the settings shared by every clip (sound, music,
  logo, pauses, punch-ins, and black bars when the call sets them), and a table with each clip's segments
  (a card as **Brand.png Card (3 s)**), finishing,
  and text on screen, including card text, read from the call's arguments
  (`video-clips-approval.tsx`).

In the composer, a video attachment shows its upload percentage, then
"Preparing video", then its duration and dimensions. The person can send once
the upload is confirmed. On the same deployments, chat also takes audio
Files, so a person can attach a track for `music`. The agent gets a note with
the File id, format, and duration, never the bytes, and the Files page plays
audio in its preview.

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
