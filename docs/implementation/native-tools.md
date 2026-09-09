# Provider-native helper tools

Read this before changing native URL fetching, code execution, document
outputs, classification, or image generation. Backend paths are relative to
`apps/api/services/agents/runtime/tools/`. See the
[governance and isolation policy](../architecture/governance.md) for provider
isolation evidence and the re-probe policy.

## URL fetching

Native URL fetching uses the governed `fetch_url` helper-tool path for
direct Anthropic and Google only. Anthropic's Vertex transport does not
support native web fetch. `NATIVE_WEB_FETCH_MAX_STEPS` bounds helper model
requests, `NATIVE_WEB_FETCH_MAX_CONTENT_TOKENS` is passed to the provider,
and comma-separated `NATIVE_WEB_FETCH_BLOCKED_DOMAINS` is enforced before
dispatch as well as passed natively. Google is unavailable while that
denylist is configured because URL Context cannot enforce domain filtering.
Keep the full URL editable and visible under the default approval policy;
never enable the local fetch fallback.

## Code execution and document outputs

Provider-native `run_code` is a separate helper-model tool for heavy
computation, create-from-text document generation, and declared append-only
edits of existing workspace documents. It is an internal
write, defaults to approval, never nests with `run_workflow`, and is offered
only for configured OpenAI, direct Anthropic, or Google providers. Anthropic
on Vertex is excluded because the file bridge requires the Files API.
Anthropic and
OpenAI receive bounded current-revision bytes through the provider file
bridge; Google receives bounded framed text or AnyDoc-derived Markdown.
Generated text artifacts and governed Files persist directly. Retained File
outputs land in one lazily created folder per conversation unless the tool
names a folder explicitly; artifact-only runs create no folder. New Files
receive a conversation reference, while declared edits retain the source
file's existing folder and references. The dated provider-isolation
probe record and re-probe policy live in `docs/architecture/governance.md`,
not in the runtime module.
Inner sandbox executions are audited even when the helper run fails
(calls without a return part audit as incomplete failures), provider
downloads stream into a buffer bounded by `NATIVE_RUN_CODE_MAX_OUTPUT_FILES`
and `NATIVE_RUN_CODE_MAX_OUTPUT_BYTES`, provider-named outputs win hash
dedup over synthetic inline names, and `NATIVE_RUN_CODE_TIMEOUT_SECONDS`
bounds the whole invocation.
Keep registry/orchestration in `native/run_code.py`, workspace-input transport
and provider-file lifecycle in `native/run_code_file_bridge.py`, and bounded
capture plus durable output persistence in `native/run_code_outputs.py`.
Anthropic/OpenAI inputs upload once per invocation under deterministic,
collision-free sandbox aliases (duplicate or normalised-colliding names get a
` (n)` suffix; the edit instruction names the exact alias) and delete
best-effort in `finally`; provider ids and deletion outcomes persist only in
one file-scoped audit event per upload, deliberately outside the tool-call
roll-up so a failed deletion is never masked by the terminal tool event.
Exclude mounted inputs
from OpenAI container outputs by provider id before budgeting and by source
hash as a defensive fallback. Declared edits append an agent-attributed
revision only when capture yields exactly one output compatible with the
source file format; the scripting model chooses its descriptive filename.
Multiple compatible outputs fail closed as ambiguous. Retain the resolved
input revision as the optimistic-concurrency boundary. Google stays on the
bounded framed text/AnyDoc-Markdown read-only path. Contain helper `ModelAPIError`
and direct Anthropic/OpenAI SDK `APIError` failures (the file bridge calls the
SDKs outside Pydantic AI's wrapper) as safe tool failures after native-call
auditing, provider-file cleanup, and usage recording so a provider outage
cannot fail the parent agent run.

## Classification and workspace tools

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

Native image generation uses the governed `generate_image` helper-tool path
for Google and OpenAI only. `NATIVE_IMAGE_GENERATION_MAX_STEPS` bounds the
Google helper run. The tool generates exactly one image, preserves provider-returned
PNG, WebP, or JPEG bytes in an audited workspace File, and defaults to
approval. `edit_image` uses the current revision of a workspace image with
OpenAI or Google and limits combined raw source bytes with
`NATIVE_IMAGE_EDITING_MAX_INPUT_BYTES` (64 MiB by default);
`generate_image_from_video` uses Google only and rejects inline videos larger
than `NATIVE_VIDEO_TO_IMAGE_MAX_INPUT_BYTES` (18 MiB by default). Both
input-media tools preserve the source file and revision ids in their result
and generated-file audit evidence.

OpenAI calls the Images API directly: `gpt-image-2.5-flare` for generation
and `gpt-image-2.5-sunburst` for editing. The approved prompt reaches the API
unchanged, including whitespace, without a helper model or added instructions.
The optional `model` argument must match the action's image model; helper IDs
such as `gpt-5.6-luna` are rejected with guidance to omit the override.
Requests, file-tool results, and usage rows name the actual image model.

OpenAI retains its three aspect ratios (`1:1`, `2:3`, and `3:2`), automatic
size when omitted, PNG output, and single edit source. The shared provider
transport owns retries; SDK retries are disabled. Known moderation blocks
produce a prompt-revision outcome; other provider errors produce safe tool
failures. Cancellation propagates. Google retains its Pydantic AI helper.
Paid live verification of the direct 2.5 calls remains pending before release.

Pydantic AI 2.42's `ImageGenerator` is not used by these tools. Its OpenAI
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

Image approvals show an editable **Image Provider** picker, including when
the agent omits the provider. The picker lists configured providers.
Generation's **Aspect Ratio** choices follow the selected provider. Without
an explicit provider, the list contains only ratios supported by every
configured provider. Changing provider preserves a supported ratio and
replaces an unsupported ratio with the first available choice. An explicit
model selection also follows the provider. Editing has no aspect-ratio
argument.

## Code output and file navigation

Provider-native `run_code` remains distinct from Code Mode: its settled row
presents the bounded computation result and retained generated Files or
artifacts, links the shared output folder when one exists, and keeps pending
approvals on the shared declarative approval surface. The Files page keeps
folder scope in the `folder` search parameter; folder-scoped paging, sorting,
file detail deep links, uploads, and single/bulk moves must preserve that
scope. Table selection is local to the current folder and page and clears
after a successful move.

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
