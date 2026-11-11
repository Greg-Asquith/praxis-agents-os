# Changelog

All notable changes to Praxis Agents OS are documented in this file.

The format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the major
version is `0`, breaking API, schema, and configuration changes may ship in a
minor release. Patch releases contain backward-compatible fixes only.

## [Unreleased]

### Added

- Claude Fable 5.2 as the Anthropic Max model, with standard token pricing
  effective from 9 November 2026 and support for adaptive thinking and
  structured output through the Claude API and configured Vertex projects.
  Pydantic AI 2.67 supplies Fable's profile and Gemini 4 Carbon's supported
  thinking levels, reducing the local model overrides.
- Google Ads keyword research: `google_ads_research_keywords` finds keyword
  ideas from words, a page, or a whole site with Keyword Planner, or gets
  metrics for exact keywords. Each row has average monthly searches, a
  12-month trend, competition, and the top-of-page bid range in the account
  currency, and can show which existing ad group Google would put it in. The
  card has theme tabs and a trend line per row, and **Build Ad Group From N
  Selected** asks the agent to prepare the ad group for approval.
- Google Ads sitelinks and callouts with approval: `google_ads_update_assets`
  adds new or existing sitelinks and callouts to up to 100 campaigns and ad
  groups, removes them, and changes a sitelink's or callout's content in one
  approval. The card lists the campaigns and ad groups first, shows where a
  changed asset is used before it changes everywhere, and checks each
  addition with Google first. `google_ads_create_campaign` and
  `google_ads_create_ad_groups` take sitelinks and callouts too, created
  once and linked wherever they're listed.
- Google Ads structured snippets, calls, prices, and images on
  `google_ads_update_assets`: add or edit structured snippets, phone
  numbers, and price lists on campaigns and ad groups, and link uploaded
  images beside ads or as a campaign's business logo, in the same approval
  as sitelinks and callouts. The card edits each price list's items in
  place, refuses a price in another currency, and checks that each image
  fits where it shows.
- Google Ads media uploads: `google_ads_upload_media` uploads up to 20
  workspace JPEG, PNG, or GIF images and links up to 20 YouTube videos to
  the selected account as assets. The card previews each image, shows which
  ad shapes it fits, and refuses a File that changed after the card was
  shown.
- Google Ads conversion settings with approval: `google_ads_update_conversions`
  changes a conversion action's status, primary or secondary use, default
  value, counting, and click-through and view-through windows, and which
  account goals bidding uses. The card shows each action's last 30 days of
  conversions and warns when bidding will optimise for different
  conversions.
- Google Ads billing on the accounts read: `google_ads_get_accounts` returns
  who pays for each account, the spending limit in force with the amount
  left, queued limits, and changes waiting for Google's review. The card
  flags accounts whose limit is reached or running low under a **Needs
  Attention** tab.

- Google Ads keyword additions per ad group: `google_ads_create_keywords` takes
  each ad group with its own keywords, up to 1,000 across 50 ad groups, adds
  them paused by default, checks each with Google first, and refuses a keyword
  the ad group already has. The card lists the ad groups first, then the open
  ad group's keywords, and Add Keywords adds more to any ad group.
- Google Ads status changes with approval: `google_ads_update_status` turns up
  to 500 campaigns, ad groups, ads, keywords, and asset groups on or off in one
  approval, checks each with Google first, refuses anything changed since the
  card was shown, and reads each one back.
- Google Ads campaign settings with approval: `google_ads_update_campaigns`
  renames up to 50 campaigns, sets or removes their start and end dates,
  changes URL options, and turns Search Partners and Display expansion on or
  off in one approval. The card refuses dates and networks Google won't take,
  and each result reads the setting back.
- Google Ads bidding changes with approval: `google_ads_update_campaigns` also
  moves campaigns between Manual CPC, Maximise Clicks, Maximise Conversions,
  Maximise Conversion Value, Target Impression Share, and portfolio strategies,
  or changes only a target. The card shows recent conversions and ad groups
  with their own bids, counts campaigns that restart learning, and refuses
  targets the strategy doesn't take.
- Google Ads ad group settings with approval: `google_ads_update_ad_groups`
  renames up to 50 ad groups and changes their CPC bid, target CPA, target
  ROAS, URL options, and ad rotation in one approval. The card refuses a bid
  or target the campaign's bidding doesn't use, and a change whose campaign
  changed its bidding since the card was shown.
- Google Ads ad edits with approval: `google_ads_update_ads` replaces, adds,
  removes, and pins headlines and descriptions, and changes display paths and
  final URLs, on up to 50 responsive search ads in one approval. The card
  shows each ad now and after the edit, edits one shared change once for
  every ad, and refuses an edit that would leave too few headlines or
  descriptions. Each result shows the ad back in Google's review.
- Google Ads negative keywords in one approval:
  `google_ads_update_negative_keywords` adds and removes up to 1,000 negative
  keywords across campaigns, ad groups, and negative keyword lists, starts new
  lists, and changes which campaigns use a list. The card refuses a negative
  that would block a keyword the account bids on, and can add keywords and
  targets the agent didn't propose.
- Google Ads search terms in one approval: `google_ads_optimise_search_terms`
  turns up to 1,000 search terms into negative keywords or new keywords. The
  card shows each term's clicks, cost, and conversions as Google reports them
  for the date range, and each action, match type, and target can be changed
  before approving.
- Google Ads budgets in one approval: `google_ads_update_budgets` changes up
  to 100 daily budgets, by campaign or shared budget, and moves campaigns onto
  shared budgets. The card shows each budget's spend this month from Google,
  lists every campaign a shared budget funds, sends decreases before
  increases, and refuses a change when a campaign joined or left the budget
  after the card was shown.
- Google Ads removal in one approval: `google_ads_remove_objects` permanently
  removes up to 500 campaigns, ad groups, ads, keywords, asset groups, unused
  budgets and bid strategies, labels, and negative keyword lists. The card
  counts the ads and keywords each removal takes with it, and refuses a
  budget or bid strategy a campaign still uses.
- Google Ads keyword changes in one approval: `google_ads_update_keywords`
  changes the max CPC, URLs, and match type of up to 500 keywords. A new match
  type pauses the keyword and adds the same text with the new match type in
  one all-or-nothing request, instead of two approvals. The card refuses a
  bid the campaign's strategy ignores and a match type the ad group already
  has.
- Google Ads ad creation: `google_ads_create_ads` creates up to 50 responsive
  search ads across existing ad groups in one all-or-nothing request, with a
  search result preview and character counts on the card.
- Google Ads ad group creation: `google_ads_create_ad_groups` creates up to 20
  ad groups in a Search campaign with their keywords, negative keywords, and
  ads in one all-or-nothing request. Keywords can be pasted, and the card
  refuses bids the campaign's bidding doesn't use.
- Google Ads Search campaign creation: `google_ads_create_campaign` builds a
  complete Search campaign, with its budget, bidding, networks, locations,
  dates, negative keywords, and up to 20 ad groups with keywords and ads, in
  one all-or-nothing request. The card shows about a month's spend, and the
  create cards can add ad groups.
- Google Ads create cards check edits with Google before approval. **Check
  Changes** shows Google's answer on the card, with no agent turn, and approval
  of an unchecked edit is refused.
- Google Ads targeting: `google_ads_search_targeting` finds locations and
  languages by name, and `google_ads_update_targeting` adds, removes, and
  excludes locations, distances around a point, and languages across up to 20
  campaigns in one approval, with bid adjustments. It refuses to leave a campaign
  with no location. Search campaigns can't add languages, because Google doesn't
  support it. It also sets device bid adjustments and exclusions and a
  campaign's whole weekly ad schedule, which changes whole or not at all.
- Google Ads audiences and demographics: `google_ads_search_targeting` finds the
  account's lists and Google's in-market, affinity, custom, and combined
  audiences by name, and `google_ads_update_targeting` adds and removes
  audiences with bid adjustments, sets Observation or Targeting, and excludes or
  adjusts ages, genders, parental status, and household income, on campaigns or
  ad groups, in one approval. Audience mode keeps every other targeting
  restriction as it is.
- `cut_video_clips` can zoom in on every other jump cut that removing pauses
  makes, which hides the jump, and push in slowly across a segment, up to
  150%. Zooms stay inside the framed picture and follow the face when framing
  is automatic. The clip card shows each zoom and **Punch-In Zooms**.
- `cut_video_clips` can play a segment faster or in slow motion, from 0.5x
  to 2x with voices at their natural pitch, and hold a segment's last frame
  for up to 3 seconds. Captions, text overlays, and transitions follow the new
  timing. The clip card shows each speed change and freeze frame.
- `cut_video_clips` can mix a track the person provided under every clip, or
  one clip, quietly by default and lowered by about 12 dB while someone
  talks. Workspace Files now accept MP3, M4A, and WAV audio, bounded by
  `MAX_FILE_SIZE_AUDIO`, which the renderer probes like video. Chat takes
  audio attachments where it takes video, and the Files page plays them. The
  clip card shows **Music Under Speech** and a note that the person is
  responsible for the music's rights.
- Clips from `cut_video_clips` are levelled to -14 LUFS, the loudness Reels,
  Shorts, and TikTok play at, unless `audio.normalize` is off. With
  `audio.enhance_voice`, the agent can also reduce background noise and make
  voices clearer. The clip card shows **Sound Levelled** and **Voice Cleaned
  Up** when they apply.
- Agents can forecast a time series with `forecast_series`, which runs
  Mistral's Timestral 123M on CPU in the isolated data science service
  (`apps/data-science`). It returns each period's median and likely range, a
  backtest from several points near the end of the history, and UK, EU, US, or
  AU public holidays as built-in covariates, and works from `run_code`. Each
  forecast carries a reliability rating with plain warnings: when it tests no
  better than a simple average, when counts are too small to predict well, and
  when the history is too short to show seasonal patterns. It leaves out
  covariates that make its test less accurate. It is hidden unless
  `DATA_SCIENCE_URL` is set; the deploy sets it on GCP. Conversations show
  each forecast as a card with the history, the forecast and its likely
  range, holiday markers, and covariate strips, with a switch to compare the
  forecast without covariates. A built-in Forecasting skill guides agents
  through gathering history, adding holidays and planned events, and
  explaining the range and accuracy.
- Charts from `build_chart` and forecast cards download as SVG as well as PNG.
- An isolated media renderer (`apps/media-renderer`) runs ffmpeg for video probe,
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
- Meta Ads asset listing: the Pages, Instagram accounts, images, videos,
  recent posts, pixels, apps, and custom and lookalike audiences each ad
  account can advertise with, as references the creation tools can use, and
  Meta's suggested EU advertiser names for the operator to confirm. Post
  text reaches the agent as untrusted content.
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
- Meta Ads ads from existing posts: ad creation can run a published
  Facebook or Instagram post unchanged in existing ad sets. The card shows
  the post as Meta returns it and refuses an Instagram post Meta won't
  boost. The setup asks for `instagram_basic`.
- Meta Ads ad copies: copy up to 50 existing ads into other ad sets of the
  same account in one approval, each paused or active and optionally
  renamed. A lost reply is settled by finding the copy by name, never by
  copying again.
- Meta Ads targeting: `meta_ads_search_targeting` finds places, interests,
  behaviours, demographics, and languages by name, and
  `meta_ads_estimate_audience` returns Meta's estimated audience for a
  targeting draft.
- Meta Ads campaign and ad set creation with approval:
  `meta_ads_create_campaign` and `meta_ads_create_ad_set` create one paused
  campaign or ad set from a plain objective or goal, with budget, bidding,
  schedule, special ad categories, targeting, placements, and EU payer and
  beneficiary names. Rules Meta would refuse are checked before approval,
  Meta checks each object in a dry run, and a lost reply is settled by name.
- Meta Ads one-approval launches: `meta_ads_launch_campaign` builds a new
  campaign, up to 10 ad sets, and up to 50 ads in one approval. Everything is
  created paused and checked by Meta first; with Go Live, the ad sets and
  then the campaign are turned on once everything is built and confirmed. A
  failure leaves the campaign paused, and the result shows what was built so
  the step tools can finish it. A launch doesn't start while the ad account
  has used 75% or more of Meta's hourly request allowance.
- Meta Ads campaign edits: `meta_ads_update_campaigns` renames up to 50
  campaigns, sets or removes their spending limits, moves them between
  highest volume, bid cap, and cost per result goal with a bid for every ad
  set, and turns off ad set budget sharing, in one approval. The card shows
  each new setting with its value now and the campaign's spend so far, Meta
  checks every change first, and each result shows the values and bids Meta
  reads back.
- Meta Ads ad set edits: `meta_ads_update_ad_sets` changes the name, start
  and end dates, bid strategy, bid or cost goal, minimum return on ad spend,
  spend limits, EU payer and beneficiary, goal, conversion event or custom
  conversion, Page, app, attribution setting, frequency cap, and ad
  scheduling of up to 50 ad sets in one approval. Ad scheduling shows the
  week's hours on the card. The card shows each new setting with its value
  now, and notes when a change restarts learning, replaces ad-level bids, or
  changes a lifetime budget's daily pace. Meta checks every change first, an
  ad set that changed after approval isn't sent, and each result shows the
  values Meta reads back.
  Ad set creation now accepts daily spend limits only under a campaign daily
  budget.
- Meta Ads ad edits: `meta_ads_update_ads` renames up to 50 ads, and sets or
  removes their own start and end times in sales and app promotion
  campaigns, in one approval. Times stay inside the ad set's schedule. Meta
  checks every change first, an ad that changed after approval isn't sent,
  and each result shows the values Meta reads back.
- Meta Ads targeting edits: `meta_ads_update_targeting` changes who up to 20
  ad sets reach in one approval, as additions and removals of locations,
  excluded locations, audiences, and detailed targeting, and new ages,
  genders, languages, or Advantage+ audience. The card shows each ad set's
  targeting in the same rows as the Create Ad Set card, with Meta's
  estimated audience before and after. The operator can add, exclude, or
  remove any place or audience through search, and drop or edit every other
  proposed change. Settings Praxis doesn't model, such as pin
  locations, stay as they are, and a change that would touch them is
  refused. An ad set that newly reaches the EU needs its payer and
  beneficiary. Meta checks every change first, an ad set whose targeting
  changed after approval isn't sent, and each result shows the targeting
  Meta reads back. The same tool changes placements, as automatic, chosen
  positions and devices, or platforms and positions to remove, such as
  dropping Audience Network, and sets the Facebook and Audience Network
  inventory filters. A filter looser than the ad account's is refused. The
  card shows where each ad set's ads show before and after, and the
  operator can change the proposed placements with the Create Ad Set
  controls.
- Meta Ads budget increases: `meta_ads_schedule_budget_increases` raises a
  campaign or ad set daily budget during up to 10 high-demand periods, such
  as a Black Friday weekend, in one approval. Each increase is an amount or
  a percentage of today's daily budget. The card shows the periods already
  scheduled and the highest daily budget, and every period's times and
  increase can be edited. Meta's period rules are checked before approval,
  and each result shows the periods Meta reads back.
- Meta Ads library images and video thumbnails show on the ad creation card.
  The API reads them from Meta's hosts and returns a re-encoded JPEG through
  the conversation preview route, so the browser never loads Meta's image
  hosts.
- Approval editors for nested tool arguments: a `structured` field is edited
  only by its provider's own approval card, and the server checks the whole
  edit against the tool's input model.

### Changed

- Google Ads Update Negative Keywords and Optimise Search Terms cards list
  their parents first. Update Negative Keywords lists its campaigns, ad
  groups, and lists with the count to add and to remove, and Optimise Search
  Terms lists the ad groups the terms matched in with their cost. A click
  shows only that parent's changes, and Cancel acts on all of them.
- Google Ads Update Budgets and Remove Items cards list their campaigns first.
  A shared budget's row names the campaigns it funds, and shared budgets,
  labels, and lists being removed sit under Not in a Campaign. A click on a
  campaign shows only its changes, and Cancel acts on all of them.
- Google Ads Update Targeting and Update Status cards list their campaigns
  first, each with its change count and Cancel for all of its changes. A
  click on a campaign shows only its changes, and on Update Targeting an edit
  or new location then reaches only that campaign.
- Meta Ads tool cards are redesigned for readability. Approval cards group
  every setting in one-line rows that open one at a time, and the operator
  can edit almost every proposed setting before approving: campaign
  objective, budget type, bidding, and special ad categories; ad set goal,
  assets, targeting (including adding locations and interests by search),
  and placements; each ad's ad sets; budget amounts and which budgets
  change; and each copy's target ad set. Campaigns, ad sets, ads, and copies
  are still created paused by default, and the card can choose Active
  instead. Results sit flat in the tool card, with tables showing a few
  default columns and the rest under Columns, and warnings use a readable
  amber.
- BigQuery queries can read views in an active dataset even when the view
  reads tables in other datasets. The tool checks the tables and views the
  SQL names before any BigQuery request, so naming another dataset's table is
  still refused.
- Integration writes can record provider IDs as audit checkpoints between
  their pending and final records. Meta Ads video uploads record the video ID
  from Meta's `start` reply before sending any bytes, so an upload interrupted
  by a stopped worker appears in run recovery with that ID.
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

- `google_ads_update_campaign_status`, replaced by `google_ads_update_status`.
- `google_ads_create_keywords`'s `ad_groups` and `keywords` arguments, which added
  every keyword to every ad group, with per-keyword status, bid adjustments,
  and URL options. Each ad group has its own `keywords`, and one `status`
  covers the request.
- `google_ads_update_campaign_budget_amounts`,
  `google_ads_assign_campaign_budgets`, and `google_ads_create_campaign_budget`,
  replaced by `google_ads_update_budgets`.
- `google_ads_update_device_bid_modifiers`, replaced by the `devices` setting
  of `google_ads_update_targeting`.
- `google_ads_remove_keywords`, `google_ads_remove_campaign_budgets`, and
  `google_ads_delete_labels`, replaced by `google_ads_remove_objects`.
- Keyword status and bid adjustments in `google_ads_update_keywords`. Keywords
  are paused and enabled with `google_ads_update_status`.
- The eight Google Ads negative keyword tools (add and remove for lists,
  campaigns, and ad groups, `google_ads_create_negative_keyword_list`, and
  `google_ads_link_negative_keyword_list`), replaced by
  `google_ads_update_negative_keywords`.
- Run Code, which sent workspace files to an Anthropic, OpenAI, or Google
  sandbox, is gone, with its `NATIVE_RUN_CODE_*` settings. Agents work with
  Office files, CSV, and saved results through the document tools, and do
  maths in Code Mode. No workspace file bytes leave the deployment for code
  execution. Earlier Run Code usage stays in the usage ledger.

### Fixed

- Searching for Google Ads sitelinks and callouts by their text no longer
  sends a query Google Ads rejects; each text field is searched on its own.
- Google Ads Create Ads, Create Ad Groups, and Create Campaign cards show a
  Google rejection once when two ads share the same copy, instead of
  repeating it.
- `google_ads_update_targeting` sends a campaign's location removals and adds
  together, so an add Google rejects can't leave the campaign with its old
  locations removed.
- Code Mode approvals that check a large change with the provider first, such
  as 960 negative keywords, reach the approval card and run after approval.
  They used to leave the run stuck until it timed out.
- Line breaks you type in a message show in the conversation, instead of
  joining the lines into one.
- Your own messages with long code lines stay inside the conversation
  column; the code block scrolls sideways instead of the message spilling
  under the sidebar.

### Security

- Converting an uploaded, fetched, or attached document to text can no
  longer run the API or jobs worker out of memory. Every conversion runs in
  the document worker, which has no secrets and a memory, CPU, and time
  limit, and Office files pass the zip pre-check first. Files over
  `DOCUMENT_TOOLS_MAX_SOURCE_BYTES` (50 MiB) are no longer converted.
- Markdown from fetched pages, KB documents, emails, and other members can
  no longer set class names. Only the classes code blocks, task lists, and
  footnotes need survive, so content can't style itself as an overlay on
  the Praxis UI.
- Adding a web page to the Knowledge Base can no longer stall the worker.
  Image and empty-link cleanup takes linear time and runs with the
  conversion, off the worker's event loop.
- Deleting or deactivating a user turns off every schedule that runs as
  them. Deleting a user also ends their workspace memberships and sign-in
  records. Background runs, queued schedule runs, and tool calls are refused
  for an inactive or deleted user even if their membership remains.
- Password registration refuses `SUPER_ADMIN_EMAILS` addresses, including
  with an invitation token. A super admin's account is created only by OAuth
  sign-in with a provider-verified email, so a workspace admin can no longer
  invite a listed address and register it themselves.
- The API and media renderer images move from `python:3.12.10-slim`, last
  rebuilt in May 2025, to `python:3.12.16-slim-trixie`. This picks up the
  Python 3.12.11 to 3.12.16 security fixes, including the Expat parser used
  for uploaded documents, and current Debian 13 system libraries.
- The web image moves from the unmaintained nginx 1.27 branch to 1.30.6,
  which fixes the October 2026 nginx advisories.
- Authlib 1.9.4, joserfc 1.8.0, pyasn1 0.6.5, and dnspython 2.9.2 clear the
  production dependency audit. None of the affected code paths is reachable
  from Praxis.
- Pydantic AI 2.50 keeps instructions, exceptions, and output templates out of
  agent spans when trace content is disabled (GHSA-4x9p-g9wm-8q7f). Provider
  SDKs and model pricing data update with it.
- Integration tool contracts now look inside `type` aliases, so account and
  connection fields nested behind one are rejected, and scoped references
  behind one must have a provider resolver.
- Pillow 13 fixes a heap overflow in JPEG decoding and denial-of-service bugs
  in PNG EXIF and GIF comment parsing, all reachable from Meta ad previews.
- certifi 2026.10.23 removes emSign root certificates whose intermediate keys
  were compromised, so outbound provider calls no longer trust them.
- DOMPurify 3.4.17 fixes sanitizer bypasses in the copy Mermaid uses for
  diagrams. FastMCP 3.4.11 fixes skipped component authorization. Logfire 5.3
  brings OpenTelemetry 1.45.1, which bounds `tracestate` parsing.
- Vite 8.3, Vitest 4.1.12, Hono, undici, and fast-uri updates fix development
  server and tooling advisories.

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
