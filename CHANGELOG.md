# Changelog

All notable changes to Praxis Agents OS are documented in this file.

The format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the major
version is `0`, breaking API, schema, and configuration changes may ship in a
minor release. Patch releases contain backward-compatible fixes only.

## [Unreleased]

### Added

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
  wait for video processing. Ad creation is pending.

### Changed

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
