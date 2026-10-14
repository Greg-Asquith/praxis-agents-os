# Changelog

All notable changes to Praxis Agents OS are documented in this file.

The format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the major
version is `0`, breaking API, schema, and configuration changes may ship in a
minor release. Patch releases contain backward-compatible fixes only.

## [Unreleased]

### Added

- An isolated media renderer (`apps/renderer`) runs ffmpeg for video probe,
  scene detection, cuts, audio extraction, and still frames. Each command
  runs under a seccomp filter with no network sockets and bounded memory,
  CPU, output, and time; the renderer refuses to start if that isolation
  fails. On GCP it is a private Cloud Run service that scales to zero.
- Uploaded and saved videos are measured by the media renderer. Each video
  File shows as processing until its duration, dimensions, frame rate, and
  audio are recorded, and `list_files`, `read_file`, and chat attachment
  notes describe them to the agent. A video that can't be read, has no
  video stream, or runs longer than `VIDEO_MAX_SOURCE_DURATION_SECONDS`
  (default 4 hours) fails processing with a plain reason.
- Gemini reads workspace video without the 18 MiB inline limit. On Vertex
  with GCS storage it reads the File by `gs://` URI, after bootstrap grants
  the Vertex AI service agent read access to workspace buckets only. With a
  `GOOGLE_API_KEY`, larger videos are uploaded once per revision to the
  Gemini Files API (up to 2 GB), reused until they expire, audited, and
  deleted when the File is purged. `generate_image_from_video` uses this
  path and gives up after 10 minutes instead of running until the run's own
  limit.
- `transcribe_video` transcribes the speech in a workspace video with word
  timings and saves it as an SRT File in the video's folder. Each video
  revision is transcribed once, by Chirp 3 on Vertex deployments,
  `whisper-1` with an OpenAI key, or otherwise Gemini 3.8 Flash, and the
  transcript is kept for later video tools. Long videos are split at
  silences. On GCP, bootstrap enables the Speech-to-Text API when
  `GOOGLE_VERTEX_AI=true`.
- `find_video_moments` finds the best moments in a workspace video for a
  brief, such as five 30 to 60 second clips about pricing, with start and end
  snapped to whole sentences and shot changes. Long videos are watched in
  overlapping 40 minute windows. `ask_video` answers a question about a video,
  or part of one, with timestamps. Both use Gemini 3.8 Flash
  (`VIDEO_UNDERSTANDING_MODEL`). With them available, chat and **Add to chat**
  in Files accept video, and the Files detail view shows a video's duration
  and dimensions.
- `cut_video_clips` cuts up to five clips from workspace videos and saves each
  as a new video File, up to about 35 minutes long. A clip joins ranges or
  whole videos in order, from one video or several, with cuts snapped to
  whole sentences and shot changes, in the original shape or 9:16, 1:1, 4:5,
  or 16:9, at the source frame rate. When the shape changes, the default
  `auto` framing follows the largest face and moves only at shot changes;
  `center` and `fit` (the whole frame over a blur) are the alternatives. One
  failed clip doesn't stop the others. The moments card gains **Cut N
  Clips**, which asks the agent to cut the chosen moments.
- `cut_video_clips` burns in captions from the transcript, in a `bold`,
  `clean`, or word-by-word `highlight` preset, and every part of the style can
  be changed: 16 bundled fonts, size, colours, outline, shadow, box, capitals,
  words per caption, lines, and position. Captions keep clear of Reels,
  Shorts, and TikTok buttons by default. `remove_silences` cuts pauses
  between words, and captions follow the shortened clip.
- `cut_video_clips` joins segments with any of ffmpeg's 58 `xfade`
  transitions, such as a crossfade, a dip to black, slides, and wipes, with
  an audio crossfade, set for every clip, one clip, or one join. Clips can
  fade in from black and out to black. Hard cuts stay the default.
- `cut_video_clips` burns up to five text overlays into each clip, such as a
  hook, a title card, or a call to action, styled like captions, with a
  `title` preset, alignment, and fades. An overlay shows for the whole clip,
  for times on the clip, or for times in one segment's video.
- Clips and transcripts of a video save in a folder named after that video,
  and clips cut from a clip join the original's folder. `cut_video_clips`
  takes an optional `folder` name instead.
- Conversations play video. A tool result that saves a video shows a player
  with its duration, dimensions, and File details; clip results show a grid
  with each clip's transitions, fades, and overlays, and link the folder. A
  sent video shows the same card. Long tool calls report their current stage
  with a `tool.progress` stream event, shown on the running tool row. Chat
  attachments show their upload percentage, then "Preparing video" until the
  video is measured.
- The usage ledger accepts video understanding, generation, and
  transcription usage. **AI Usage** prices transcription per audio minute
  (Gemini by tokens) and Veo 3.1 output per second by resolution, and shows
  unpriced video output as **Incomplete video outputs**.
- Claude Haiku 5.5 is available directly and through Google Cloud. It is the
  Anthropic **Light** default and the default Claude model for native web
  search, web fetch, and classification, priced from $0.10 input and $0.50
  output per million tokens.
- Agents read PowerPoint, Excel, and Word files with dedicated tools that
  return slides, cells, formulas, paragraphs, tables, charts, comments, and
  embedded images, in pages. `read_table` returns rows from workbook sheets,
  CSV files, and saved tool results, so Code Mode scripts can total every row
  of a large report. Office, CSV, and JSON files are parsed in the bounded
  document worker.
- Agents edit and create PowerPoint, Excel, and Word files with
  `edit_presentation`, `edit_workbook`, `edit_word_document`,
  `create_presentation`, `create_workbook`, and `create_word_document`. Edits
  save a new File revision only when every operation succeeds and the File
  hasn't changed since it was read, and they read back what they changed.
  New files start from a workspace template or a neutral default. Workbooks
  with charts, images, custom XML, or other content an edit would remove, or
  with more than 1,500,000 cells, can't be edited yet.
- An Office Documents skill teaches every agent to edit a person's file
  rather than recreate it, write formulas for derived values, check every
  figure it reports, and describe what changed. Saved reports, attachments,
  and SharePoint copies now point agents at the document tools and
  `read_table`.
- Conversation rows for the document tools show what was read, what each edit
  changed and its new version, warnings to check, and a plain summary of the
  changes in approvals, including inside Code Mode scripts.
- Meta Ads workspace connections with System User access tokens, bounded ad
  account discovery, permission-based writability, optional app-secret proof,
  and setup guidance.
- Meta Ads Insights reports with typed metrics and actions, bounded background
  fallback, account-specific throttle handling, Code Mode, and retained-result
  previews.
- Meta Ads account overview, filtered campaign, ad set and ad listings with
  budgets in account currency, and custom conversion discovery. Insights
  returns conversion names alongside unchanged metrics and IDs, including
  Code Mode and retained results.
- Meta Ads change history for up to 31 days per request, with object filters,
  bounded before and after values, and retained-result previews.
- Meta Ads status and budget changes with approval: turn campaigns, ad sets,
  and ads on or off, and change campaign and ad set budget amounts, with
  read-back evidence.
- Meta Ads asset listing: the Pages, Instagram accounts, images, and videos
  each ad account can advertise with, as references ad creation can use.
- Meta Ads media upload: up to 20 workspace images or videos per approval,
  pinned to the reviewed File versions, with chunked video upload, lost
  replies settled by finding the upload rather than resending it, and a
  wait for video processing.
- Meta Ads ad creation: up to 50 image, video, and carousel ads across up to
  10 existing ad sets in one approval, with optional 9:16 versions for
  Stories and Reels, workspace images uploaded with the ads, and each ad
  created paused or active. Every Meta advanced setting and AI enhancement
  is sent off unless the operator turns it on. Meta checks every ad before any is created, and
  each result reports Meta's review, any change Meta turned on anyway, and
  a preview link. The approval card lists the ads and opens one at a
  time, with a preview for Feed and for Stories and Reels beside its text,
  checks shown under the field they're about, and inline editing of text,
  links, buttons, status, and carousel card order. Option pickers now show
  provider values such as `LEARN_MORE` as "Learn More". Ad listings include Meta's
  review reasons.
- Meta Ads library images and video thumbnails show on the ad creation card.
  The API reads them from Meta's hosts and returns a re-encoded JPEG through
  the conversation preview route, so the browser never loads Meta's image
  hosts.
- Approval editors for nested tool arguments: a `structured` field is edited
  only by its provider's own approval card, and the server checks the whole
  edit against the tool's input model.

### Changed

- Local and Azure Files uploads stream to storage instead of buffering in API
  memory.
- Files uploads show a floating panel with the file name, a progress bar,
  bytes sent, and a Cancel button, shared by the upload button and drag and
  drop. The panel confirms when uploads finish and keeps errors until
  dismissed.
- Each deployment lists the Claude and partner models its Google Cloud
  project can use, in `ANTHROPIC_VERTEX_MODELS` and `VERTEX_PARTNER_MODELS`.
  `ANTHROPIC_VERTEX_AI=true` and `VERTEX_PARTNER_MODELS_ENABLED=true` now
  require their list. Models that aren't listed are hidden from the model
  picker and rejected at run time. Add the lists to existing environment
  files before deploying.
- Google image generation, editing, and video-to-image tools use Nano Banana
  2.1, with updated 1K image-output estimates. Vertex image actions use the
  supported global endpoint and reject explicit regional locations.

- Code Mode runs on Monty 1.0. Scripts can read the clock, use random values,
  and import `base64`, `copy`, `functools`, and `time`. Sleeps return at once.
  Scripts paused for approval before the upgrade cannot resume: read-only
  scripts return a failure the agent can redraft, and scripts with completed
  changes need operator recovery. Agent guidance for Code Mode now covers when
  to use a script and the configured limits.
- The Code Mode tool is now `run_code`, the agent's only code tool; it was
  `run_workflow`. There is no alias, so approvals paused on `run_workflow`
  can't resume. The conversation card is titled "Script".
- The Docker quickstart works on Docker Engine on Linux. The migrate, API, and
  worker containers run as the host user, so they can read the private secrets
  file and write local storage. `make quickstart-detached` starts the stack in
  the background, and OpenRouter keys are rejected with a clear message. The
  README covers installing Make and scripted installs that save the key
  without a prompt.
- People can upload videos up to 4 GiB to Files on Google Cloud Storage and
  Amazon S3, set by `MAX_FILE_SIZE_SOURCE_VIDEO`. Azure and local storage keep
  the 100 MB `MAX_FILE_SIZE_VIDEO` limit for uploads. Files accept WebM, and QuickTime files are stored as
  `video/quicktime` instead of `video/mov`.

### Removed

- Run Code, which sent workspace files to an Anthropic, OpenAI, or Google
  sandbox, is gone, with its `NATIVE_RUN_CODE_*` settings. Agents work with
  Office files, CSV, and saved results through the document tools, and do
  maths in Code Mode. No workspace file bytes leave the deployment for code
  execution. Earlier Run Code usage stays in the usage ledger.

### Security

- Pydantic AI 2.50 keeps instructions, exceptions, and output templates out of
  agent spans when trace content is disabled (GHSA-4x9p-g9wm-8q7f). Provider
  SDKs and model pricing data update with it.
- Integration tool contracts now look inside `type` aliases, so account and
  connection fields nested behind one are rejected, and scoped references
  behind one must have a provider resolver.

## [0.1.0] - 2026-07-28

### Added

- Password, OAuth, and TOTP authentication; secure sessions; users,
  workspaces, memberships, invitations, and role-based access.
- A Pydantic AI agent runtime with streamed conversations, typed tools,
  approval pause and resume, bounded results, cooperative cancellation,
  single-level delegation, run envelopes, and deterministic behavior
  scenarios.
- Persistent conversation history with file attachments, multimodal image
  input, token-aware trimming, and background summaries.
- Workspace skills with progressive disclosure and supporting documents.
- A knowledge base with manual, URL, and uploaded sources; background
  ingestion; hybrid keyword and semantic retrieval; citations; agent tools;
  and operator management.
- Provenance-tracked agent memories with hybrid retrieval, prompt injection,
  deduplication, version-preserving correction, archive, purge, and operator
  review.
- Agent schedules, leased execution, a generic jobs worker, and visible
  failure and approval states.
- Signed file uploads, immutable revisions, background markdown extraction,
  cloud-storage provider seams, and agent file tools.
- Immutable artifacts with approval-gated agent tools, workspace management,
  append-only edit and restore flows, sandboxed previews, and version-pinned
  anonymous share links.
- Gmail, Google Ads, Google Analytics, and Google Search Console integration
  packages with OAuth; Airtable with API-key connections; and BigQuery, Google
  Ads, and Google Analytics with service-account connections; resource discovery;
  context groups; bounded Search Console performance, sitemap, and URL inspection reads;
  approval-gated sitemap resubmission with read-after-write status; approval-aware writes;
  operator-enabled, owner-only Indexing API notifications for eligible job posting and
  livestream video pages; and guarded rich results.
- A typed, versioned tool catalog with workspace grants, one audited
  dispatch choke point, runtime policy enforcement, and per-call audit data.
- Audit and security event viewers, opt-in self-hosted observability, and
  explicit security middleware for CORS, CSRF, cookies, rate limiting,
  request bounds, and response headers.
- An opt-in live-model evaluation harness alongside deterministic,
  database-backed runtime scenarios.
- Reproducible local development, database-backed verification, CI,
  dependency auditing, CodeQL analysis, Dependabot updates, SHA-pinned GitHub
  Actions, OpenAPI artifact export, and API image publication to GHCR.
- A Docker-only quickstart with self-provisioned local configuration,
  migration-gated service startup, production-image smoke coverage, health
  probes, and automatic support for both Compose command styles.

### Changed

- Compose resource names changed from `praxis-agents-template-*` to
  `praxis-*`. Existing legacy-named local volumes are left intact and can be
  inspected or migrated manually; the new stack starts with a fresh database.

[0.1.0]: https://github.com/Greg-Asquith/praxis-agents-os/releases/tag/v0.1.0
