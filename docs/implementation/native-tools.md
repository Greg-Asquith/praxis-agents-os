# Provider-native helper tools

Read this before changing native web search, page questions, classification,
or image generation. Backend paths are relative to
`apps/api/services/agents/runtime/tools/`.

## Web search

Selecting Google without a model override uses `gemini-3.8-flash` for
`web_search`; selecting OpenAI uses `gpt-6-luna`. Omitting both provider and
model retains the eligible agent model.
Search results include the executed query, answer, and provider sources in the
model-visible tool return, including queries edited during approval. Tool
guidance tells the agent to resolve relative dates against the conversation
date and answer once the evidence is sufficient. This guidance does not enforce
a hard limit on repeated searches.

## Page questions

`ask_url` answers a question about one page through a helper model's native
web fetch. `fetch_url` returns a page's content and `check_urls` checks many
URLs' status and redirects, both on Praxis infrastructure with no helper
model. For these tools, the shared settings, and saving fetched pages, see
[Web tools](web-tools.md).

## Code and Office files

No helper provider runs code. Agents run code with `run_code` (Code Mode,
see [Code Mode](code-mode.md)) and work with Office files, CSV, and saved
results through the [document tools](document-tools.md).

The registered GPT-6.1 Sol, GPT-6 Sol, GPT-6 Luna, Claude Opus 5.5, and
Claude Sonnet 5.5 models can use the existing eligible helper paths. Live
capability probes for these model versions remain pending. Earlier model probe
results do not qualify these versions.

## Classification and workspace tools

The OpenAI classification default and provider fallback use `gpt-6-luna`.
The Google default is `gemini-decision-1` through the Gemini Decisions API.
With `GOOGLE_VERTEX_AI=true`, where Decisions isn't served, it is
`gemini-3.5-flash-lite` with structured output. An explicit classifier model or
environment override takes precedence. A saved `gemini-decision-1` selection on
a Vertex deployment returns a model-visible retry instead of falling back.

The following contracts apply in this area:

- Native batch classification uses the code-eligible `classify` helper-tool
  path for OpenAI, Anthropic, and Google. It always uses a configured cheap
  helper independently from the calling agent, accepts up to 500 items per
  tool call, and processes them sequentially in batches of at most 100. It
  meters one ledger row per helper invocation, frames items as untrusted data,
  and accepts only ordered labels from the caller's closed set. Public results
  pair each label with the exact server-copied input `value`; the helper never
  authors that free-text field. Keep its public item, label, instruction, and
  helper-step bounds settings-owned; the internal 100-item batch size stays a
  runtime constant. Adding helper-authored rationale or confidence output
  reopens the trust decision.
- Classification on `gemini-decision-1` sends each batch as one Decisions
  request. The escaped item prompt is the shared input, billed once. Each item
  gets one `choice` question whose options are the closed labels and whose
  instructions name only the item's index, so item text never reaches question
  instructions. Pydantic AI's `GoogleDecisionsModel` rejects answers outside
  the labels. Decisions-only models are listed separately from the agent
  catalogue (`decision_models` in the model catalogue response), so classifier
  pickers and saved classifier overrides can select them but agents cannot.
- Workspace classifiers are the first producer of generic workspace-defined
  runtime tools. Active rows are loaded for each run and synthesised as
  `classifier_{name}(items)` definitions without mutating the process-global
  registry; the ad-hoc `classify(items, labels, instructions, ...)` tool remains
  available independently. A future family adds its own table/CRUD surface and
  producer, reserves a unique prefix in `workspace_tools.py`, and contributes
  one call to the aggregation loader. Workspace-defined names are unavailable
  through the static tool-availability route, accept no per-call override of
  stored configuration, and row changes take effect when the next run loads
  definitions.

## Image generation and editing

### Media model catalogue

`generate_image`, `edit_image`, `generate_video`, and `edit_video` take an
optional `model`:
an ID from the media catalogue, `apps/api/services/media/models.toml`. Each
entry records the model's tasks, limits (aspect ratios, source images,
durations, and resolutions), routes, upstream lab,
processing location, a one-line `strengths`, and whether the vendor
indemnifies output. Each route names the provider's own model ID, per task
where it differs, and an estimated price per image or per second, optionally
by output resolution, plus, for a video model that edits, a price a second
for the input clip (`usd_per_input_second`). Adding or
retiring a model is an edit to the file. `services/media/catalogue.py` loads
and validates it once per process, so an unknown task, a missing price, a
duplicate ID or route, a video route without a price for each resolution it
lists, or a `DEFAULT_IMAGE_GENERATION_MODEL` or `DEFAULT_VIDEO_GENERATION_MODEL`
that can't do its task fails startup.

| ID | Route and provider model | Estimate | Processed |
| --- | --- | --- | --- |
| `nano-banana-2.1` | `google`: `gemini-nano-banana-2.1` | $0.034 per 1K image | Globally |
| `gpt-image-2.6` | `openai`: `gpt-image-2.6-flare`, `gpt-image-2.6-sunburst` for edits | About $0.043 per 1024 × 1024 output at medium quality | Globally |
| `gpt-image-2.5` | `openai`: `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst` for edits | About $0.013 per 1024 × 1024 output at medium quality | Globally |
| `omni-1.2-flash` | `google`: `gemini-omni-1.2-flash` | $0.07 a second at 720p, $0.10 at 1080p, $0.21 at 4K, and $0.009 a second of input clip for an edit (billed by token) | Globally |

A model is available when one of its routes is configured: Google and OpenAI
by their provider credentials, with Google on Vertex also needing a supported
location. Runway and Replicate routes are never available until plans 353 and
354 add their backends. When two configured routes serve one model, the
cheaper one is used, and equal prices go to the earlier route in
`MEDIA_ROUTE_PREFERENCE` (Google, OpenAI, Runway, Replicate). The tool schema
lists the models available at process start. A model that isn't in the
catalogue, doesn't list the task, or has no configured route is refused before
any provider call.

When `model` is omitted, the tool uses `DEFAULT_IMAGE_GENERATION_MODEL`
(`nano-banana-2.1` by default) if it's available, otherwise the first available
model in catalogue order. `generate_video` and `edit_video` do the same with
`DEFAULT_VIDEO_GENERATION_MODEL` (`omni-1.2-flash`, which also edits); see
[video tools](video-tools.md#generation). Routing between models (plan 352 B) is pending.

The approval card shows **Image Model** with the model that will run, filled
in by the tool's approval display arguments when the agent named none. Each
choice reads, for example, "Nano Banana 2.1 · About $0.03 per image ·
Processed globally", and changing it changes the cost shown. Generation's
**Aspect Ratio** choices follow the selected model. Usage rows keep the
route's provider and model and add `media_model` and `lab` to their details.

The catalogue price is an estimate for the card; the video cards also show
the call's estimated cost (see [video tools](video-tools.md#generation)), and
a test keeps a 10 second 720p Omni estimate within half a cent of the billed
token price. Usage reads price the calls
themselves in `services/ai_usage/pricing.py`: GPT Image by its text and
image tokens, Nano Banana per image (see [AI usage](ai-usage.md)). Both GPT
Image versions produce raster images in Praxis.

### Providers

Native image generation uses the governed `generate_image` helper-tool path.
`NATIVE_IMAGE_GENERATION_MAX_STEPS` bounds the
Google helper run. The tool generates exactly one image, preserves provider-returned
PNG, WebP, or JPEG bytes in an audited workspace File, and defaults to
`auto`. `edit_image` uses the current revision of a workspace image with
OpenAI or Google and limits combined raw source bytes with
`NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES` (64 MiB by default) and the model's
`max_input_images` (14 for Nano Banana, 1 for GPT Image);
`generate_image_from_video` uses Google only and reads the video through the
shared video input (see [Video tools](video-tools.md#gemini-video-input)): by
`gs://` URI on Vertex with GCS storage, through a Files API upload on the
Gemini API, and otherwise inline up to `NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES`
(18 MiB by default). It times out after `VIDEO_MODEL_TOOL_TIMEOUT_SECONDS`
(see [Long media calls](video-tools.md#long-media-calls)). Both input-media
tools preserve the source file and revision ids in their result and
generated-file audit evidence.

When OpenAI supplies the image fallback, generation uses `gpt-image-2.6-flare`
and edits use `gpt-image-2.6-sunburst`. An explicit GPT Image 2.5 selection
uses its corresponding Flare or Sunburst route. Both versions call the Images
API directly. The approved prompt reaches the API
unchanged, including whitespace, without a helper model or added instructions.
Requests and usage rows name the provider's image model; file-tool results
return the catalogue ID as `model`, the route as `model_provider`, and the
provider's model as `image_model`.

OpenAI retains its three aspect ratios (`1:1`, `2:3`, and `3:2`), automatic
size when omitted, PNG output, and single edit source. The shared provider
transport owns retries; SDK retries are disabled. Known moderation blocks
produce a prompt-revision outcome; other provider errors produce safe tool
failures. Cancellation propagates. Google retains its Pydantic AI helper.
OpenAI returned both 2.6 model IDs on 19 November 2026. Paid generation and
editing remain unverified. See the [image cost calculator](https://developers.openai.com/api/docs/guides/image-generation#calculating-costs) for the output estimates.

Pydantic AI's `ImageGenerator` (OpenAI, Google, and xAI adapters; rechecked
at 2.68 on 2026-11-17, with no Runway, Replicate, or video adapter) is not
used by these tools. Its OpenAI
adapter decodes every returned base64 image before application byte or count
checks. The retained OpenAI adapter checks encoded length before decoding
and records usage before validating outputs. The direct OpenAI and Google
adapters can raise for empty, malformed, or filtered outputs without exposing
returned usage to the invocation meter. Google therefore retains its metered
Agent helper for generation and editing. Its video helper also remains:
the direct API accepts image references, but rejects `BinaryContent` video
inputs before requesting the provider. Mocked contract tests cover direct
Google and Vertex image references separately. These results do not qualify
live provider availability.

Google generation, editing, and video input use Nano Banana 2.1
(`gemini-nano-banana-2.1`) through the same provider factory as chat.
Vertex requires an explicit project
and Application Default Credentials. `GOOGLE_VERTEX_LOCATION=auto` retains
the image model's `global` default. Explicit `global` is supported.
Other locations, including `eu` and `us`, make Google image models
unavailable, and naming one is refused. No direct-API fallback occurs.
Vertex inline source images are limited to 7 MB each, in addition to the
combined workspace input limit. Convert GIF sources to PNG, JPEG, or WebP
before Vertex editing. These requirements follow the
[Google image model specification](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/nano-banana-2-1),
reviewed on 6 October 2026.

Pydantic AI 2.66 detects image models by an `image` substring, which this ID
lacks. The model factory supplies an image profile with function tools and
structured output disabled. Thinking stays enabled with Google's default
`medium` level. The helper retains the default 1K output resolution.
Live verification of Nano Banana 2.1 project access remains pending.

Google image helpers do not regenerate an image after output validation fails.
Provider errors return safe tool failures, moderation refusals request a revised
prompt, and cancellation propagates. The invocation meter retains attempted
requests and available response tokens on failure. A successful provider response
does not establish a workspace File until storage succeeds.
Malformed JSON or invalid base64 can fail inside the Google SDK before it
exposes response usage. Those invocations retain the attempted request with
unavailable token counters. The helper does not replay them to recover usage.

Offline adapter tests cover every native family by transport, including Google
Vertex credentials, regions, media, grounding, and response parsing. Anthropic
Vertex retains search and classification, while fetch remains excluded. Vertex partner models remain outside native helper provider sets.
Live qualification on the upgraded SDKs remains pending. Mocked adapter
responses do not establish project access.

## Classifier presentation and management

The following contracts apply in this area:

- Native classifier results use the dedicated compact classifier row: always
  show the server-retained classified `value` beside its closed-set assigned
  label, including replayed Code Mode children whose unrestricted arguments
  are intentionally not persisted. Also show label distribution plus
  provider/model details.
- Workspace classifiers are managed by workspace owners and admins from the
  Classifiers tab in Workspace Settings. Keep category and judging copy in
  operator language, place the helper-model override behind Advanced, and
  default it to Automatic. Classifier mutations invalidate the workspace
  classifier list and both workspace tool query families so agent settings and
  conversation presentations refresh without a reload. Saved changes apply to
  the next agent run.
