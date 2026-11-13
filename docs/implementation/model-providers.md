# Model providers and transports

Read this before changing model resolution, credentials, Vertex routing,
or model HTTP retries. Backend paths are relative to `apps/api/`.

## Catalogue and provider clients

LLM providers live in `services/agents/models/`. The catalogue in
`registry.py` is the single source of truth for available models;
`factory.py` builds pydantic-ai models per provider. Resolve credentials
only through the `provider_api_key` seam. Never rely on implicit env
pickup. Direct providers share the retrying HTTP client
(`retrying_http_client()`), which uses HTTPX2. OpenAI image calls and direct
embedding adapters use the same transport. Vertex partner authentication and
endpoint-bound Mistral clients also use HTTPX2.

Import a provider SDK (Google, OpenAI, Anthropic, or Ollama) only inside the
code path that uses it: the factory builder, the Vertex client getter, the
embedding provider, the transcription provider, or the native tool's provider
branch. The SDKs are large,
so loading them at import time slows every cold start, and a deployment should
load only the providers it calls. The clean-process test in
`tests/contract/test_entrypoint_imports.py` fails if startup loads any of them.

### Claude Fable 5.2

The [model overview](https://platform.claude.com/docs/en/models/fable-5-2/overview),
[pricing](https://platform.claude.com/docs/en/about-claude/pricing), and
[Google Cloud model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/fable-5-2),
checked on 11 November 2026, list `claude-fable-5-2` from 9 November 2026.
Both transports use that ID. It has a 1,000,000-token context window,
128,000 maximum output tokens, and a June 2026 knowledge cutoff. It accepts
text and images, returns text, and supports streaming, tools, and structured
output. Fable 5.2 is the Anthropic **Max** default when available. Fable 5.1
and Fable 5 remain selectable.

Standard prices are $8 input, $0.20 cache read, $10 five-minute cache write,
and $40 output per million tokens, effective from 9 November 2026. One-hour
cache writes cost $16. Estimates use Claude API and Vertex `global` standard
rates. Regional premiums, one-hour cache writes, batch discounts, and fast-mode
charges remain outside the aggregated estimates. Fast mode costs $16 input
and $80 output per million tokens on the Claude API. Vertex fast-mode requests
remain pending because the installed SDK suppresses the speed setting there.

The [migration guide](https://platform.claude.com/docs/en/models/fable-5-2/migration-guide)
requires always-on adaptive thinking and rejects forced tool choice and
non-default sampling settings. Effort accepts `low`, `medium`, `high`,
`xhigh`, and `max`, with `high` as the default. Catalogue settings request
summarised thinking. Pydantic AI 2.67 covers the family settings, output
limit, forced-tool restriction, thinking-block binding, and direct fast-mode
support without a local profile override. Structured results use
native JSON schema output. Prefix-binding failures use the SDK's existing
single retry with stale-block recovery.

Google Cloud supports `global`, `us`, and `eu`; Praxis uses the configured
`ANTHROPIC_VERTEX_LOCATION`, which defaults to `global`. Enable the model in
Model Garden and add `claude-fable-5-2` to `ANTHROPIC_VERTEX_MODELS` to expose
it on Vertex. Live access remains unverified with a Praxis key or project.
Fable 5.2 requires 30-day data retention unless Anthropic expressly authorises
an exception. Structured output with customer-managed encryption keys is
unsupported. Provider-native computer use and advisor tools remain outside
Praxis's governed tool catalogue.

### GPT-6.1 Terra

The [model page](https://developers.openai.com/api/docs/models/gpt-6.1-terra),
[pricing page](https://developers.openai.com/api/docs/pricing), and
[changelog](https://developers.openai.com/api/docs/changelog), checked on
5 November 2026, list `gpt-6.1-terra` from 26 October 2026. It has a
1,050,000-token context window, 922,000 maximum input tokens, 128,000 maximum
output tokens, and a 1 June 2026 knowledge cutoff. It accepts text and images,
returns text, and supports streaming, function calls, and structured output.
Tool calls require Responses, which Praxis uses.

For prompts up to 272,000 tokens, Terra costs $1 input, $0.05 cache read,
$1.25 30-minute cache write, and $5 output per million tokens. Longer prompts
use the same multipliers as GPT-6 Sol. Usage estimates use the base rates.

Terra is an OpenAI **Standard** model listed after GPT-6 Luna, so Luna stays
the Standard default. Terra accepts `none` to `max` reasoning efforts with
`medium` as the default. Pydantic AI 2.66 profiles it like GPT-6 Sol. Live
access hasn't been checked with a Praxis key.

### Gemini 4 Hydrogen

The [Gemini API model page](https://ai.google.dev/gemini-api/docs/models/gemini-4-hydrogen),
[release notes](https://ai.google.dev/gemini-api/docs/changelog), and
[Google Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-hydrogen),
checked on 13 November 2026, list `gemini-4-hydrogen` as generally available
from 12 November 2026. Both transports use the same ID. On 13 November 2026,
the Gemini API model list with the Praxis key returned Hydrogen with a
1,048,576-token input limit and a 65,536-token output limit. Vertex access
hasn't been checked. Hydrogen is a **Standard** model listed after
`gemini-3.8-flash`, so 3.8 Flash remains Google's Standard default.

Hydrogen accepts text, images, audio, video, and PDFs, and supports function
calls and structured output. Vertex supports `global`, `us`, and `eu`;
`GOOGLE_VERTEX_LOCATION=auto` selects `eu`. Google documents `low`, `medium`,
`high` (the default), and `xhigh` thinking. It rejects `minimal` and
`thinking_budget`. Pydantic AI 2.68 doesn't profile Hydrogen and sends `xhigh`
as `HIGH`, so `provider_model_profile` adds always-on thinking and the `low`,
`medium`, and `high` levels. The UI's `minimal` preference and disabled
thinking both send `low`.

The [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-4-hydrogen)
lists standard prices of $1.50 input, $0.075 cache read, and $7.50 output per
million tokens, with no dated change. Thinking tokens count as output. Implicit
caching has no separate write charge. Long decode is pending, as it is for
Carbon and Argon.

### Gemini Decision 1

`gemini-decision-1` serves only the
[Gemini Decisions API](https://ai.google.dev/gemini-api/docs/decisions-api),
launched on 11 November 2026 on the Gemini Developer API (`v1beta`). It isn't
on Vertex and isn't a selectable agent model. Praxis uses it, through Pydantic
AI 2.68's `GoogleDecisionsModel`, for progress reviews (see
[agent runs](agent-runs.md)) and as Google's default classifier model (see
[native tools](native-tools.md)). The registry keeps it in a separate
Decisions-only list. It takes up to 262,144 input tokens, returns zero
output tokens, and has no context caching or Batch API support. The
[pricing page](https://ai.google.dev/gemini-api/docs/pricing#gemini-decision),
checked on 13 November 2026, lists $0.10 per million input tokens.

### Gemini 3.1 Pro retirement

The Gemini API serves Gemini 3.1 Pro only as `gemini-3.1-pro-preview`. On 13
November 2026, its model list had no `gemini-3.1-pro`, so the catalogue alias
returned 404 on the direct transport. The catalogue drops it for
`gemini-4-argon`, which is GA, has the same **Powerful** type, and costs less
for output. Migration `core_0079` moves saved agent selections and Google
workspace defaults to Argon, including inactive and deleted agents. Both
models accept `low`, `medium`, and `high` thinking, so saved settings stay
valid. Downgrading leaves Argon selections in place. Historical price rows
remain.

### Gemini 4 Carbon

The [Gemini API model page](https://ai.google.dev/gemini-api/docs/models/gemini-4-carbon),
[release notes](https://ai.google.dev/gemini-api/docs/changelog), and
[Google Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-carbon),
checked on 10 November 2026, list `gemini-4-carbon` as generally available
from that date. Both transports use the same ID. Carbon is Google's **Max**
default; Argon remains **Powerful**. Existing agent selections and native
helper defaults remain unchanged.

Carbon accepts text, images, audio, video, and PDFs, returns text, and supports
streaming, function calls, and structured output. Input, thinking, and output
share a 1,048,576-token context window. The knowledge cutoff is March 2026.
Vertex supports `global`, `us`, and `eu`; `GOOGLE_VERTEX_LOCATION=auto` selects
`eu`. Unsupported locations fail before client construction. Live access
hasn't been checked with a Praxis API key or Vertex project.

Carbon accepts `low`, `medium` (the provider default), and `high` thinking.
Pydantic AI 2.67 supplies Carbon's supported levels, and
`provider_model_profile` adds its missing always-on-thinking flag.
The UI's `minimal` preference and disabled thinking both send `low`.
Explicit `thinking_budget` and `MINIMAL` settings are unsupported. Google
ignores temperature, top-p, and top-k. Only implicit caching is supported,
with a 4,096-token minimum. See the
[Carbon migration guide](https://ai.google.dev/gemini-api/docs/whats-new-gemini-4-carbon).

Praxis uses ordinary `generateContent` and `streamGenerateContent` calls.
Google Cloud documents per-segment output limits of 65,536 streaming tokens
and 32,768 non-streaming tokens, including thinking. Long decode up to the
shared context limit remains pending verification of continuation handling,
cumulative usage, and context accounting. Provider-native computer use and
agentic video processing remain outside Praxis's governed tools.

The [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-4-carbon)
and [Google Cloud pricing](https://cloud.google.com/model-garden/pricing),
checked on 10 November 2026, list these standard prices in USD per million tokens:

| Transport | 10-30 November 2026: input / cache read / output | From 1 December 2026: input / cache read / output |
| --- | --- | --- |
| Gemini API and Vertex `global` | $2 / $0.10 / $10 | $4 / $0.20 / $20 |
| Vertex `us` and `eu` | $2.20 / $0.11 / $11 | $4.40 / $0.22 / $22 |

Thinking tokens count as output. Implicit caching has no separate write
charge. Usage estimates use Gemini API and Vertex `global` rates. Regional
premiums and Vertex promotional-credit reconciliation remain pending because
the ledger does not record transport or location. Batch, Flex, Priority, and
grounding charges remain outside standard token estimates.

### Gemini 4 Argon

The [Gemini API model page](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)
and [Google Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon),
checked on 13 October 2026, use `gemini-4-argon` for both transports. Argon is
Google's **Powerful** default. It accepts text, images, audio, video, and PDFs,
returns text, and supports streaming, function calls, and structured output.
Input, thinking, and output share a 1,048,576-token context window.

Vertex supports `global`, `us`, and `eu`. `GOOGLE_VERTEX_LOCATION=auto` selects
`eu`; explicit unsupported locations fail before client construction. Gemini
API calls use the configured API key, and Vertex calls use Application Default
Credentials and the configured project. On 13 October 2026, live smoke tests
confirmed streamed and non-streamed tool calls and structured output through
the configured Gemini API key and Vertex `eu` project. Other projects require
their own access check.

Argon accepts `low`, `medium` (the provider default), and `high` thinking.
Pydantic AI 2.66 supplies Argon's levels but not its always-on thinking, so
`provider_model_profile` adds `thinking_always_enabled`. The UI's `minimal`
preference and disabled thinking both send `low`. Explicit `thinking_budget` and `MINIMAL` settings are
unsupported. Google ignores temperature, top-p, and top-k, and rejects frequency
and presence penalties, candidate counts, explicit caches, and prefilled model
turns. See the
[Argon developer guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon).

Praxis uses ordinary `generateContent` and `streamGenerateContent` calls.
The single-request output limit includes thinking: 65,536 tokens for streaming
and 32,768 for non-streaming HTTP calls. Long decode up to 1,048,576 tokens is
pending: it requires Google Gen AI 2.30.1 or later, continuation handling, and
verification of cumulative usage and context accounting. The installed 2.25.0
SDK supports the ordinary request path. Praxis doesn't use Argon's
provider-native computer use or agentic video processing.

The [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-4-argon)
and [Google Cloud pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
checked on 13 October 2026, supersede the announcement's introductory end date.
Standard token prices are USD per million tokens:

| Transport | 13 October to 30 November 2026: input / cache read / output | From 1 December 2026: input / cache read / output |
| --- | --- | --- |
| Gemini API and Vertex `global` | $2 / $0.10 / $10 | $4 / $0.20 / $20 |
| Vertex `us` and `eu` | $2.20 / $0.11 / $11 | $4.40 / $0.22 / $22 |

Output rates include thinking tokens. Argon supports implicit caching only,
with no separate cache-write charge. Vertex provides its introductory discount
through credits against net spend. Usage estimates use Gemini API and Vertex
`global` rates for both transports. Regional premiums and billing-credit
reconciliation are pending because the ledger does not record transport or
location. Batch, Flex, Priority, and grounding charges remain outside these
standard token estimates.

### Gemini Flash retirement

The catalogue excludes `gemini-3.6-flash` and `gemini-3.7-flash`.
Google's **Standard** selection, web search, and URL fetching use
`gemini-3.8-flash`. Historical price rows remain for past usage estimates.
Migration `core_0065` moves saved agent selections and Google workspace
defaults from either retired model to 3.8. It includes inactive and deleted
agents, and agents whose provider comes from a default. Other explicit
providers and models remain unchanged. Downgrading leaves upgraded selections
in place because the original version cannot be recovered reliably.

Explicit environment overrides require a configuration update before restarting
the API and worker. The migration does not edit environment files.

### Claude Haiku 5.5

The following specifications come from the
[model overview](https://platform.claude.com/docs/en/about-claude/models/overview)
and [pricing](https://platform.claude.com/docs/en/about-claude/pricing) pages,
checked on 7 October 2026. `claude-haiku-5-5` is the API ID and the Google Cloud
ID. It has a 1,000,000-token context window, 128,000 maximum output tokens, and
a June 2026 knowledge cutoff. It accepts text and images, returns text, and
supports streaming, tools, and structured output.

Haiku 5.5 prices depend on prompt length. Token prices are USD per million
tokens, shown as input / cache read / five-minute cache write / output:

| Transport | Prompts up to 100,000 tokens | Prompts over 100,000 tokens |
| --- | --- | --- |
| Claude API, and Google Cloud `global` | $0.10 / $0.01 / $0.125 / $0.50 | $0.50 / $0.05 / $0.625 / $2.50 |
| Google Cloud `eu` multi-region | $0.11 / $0.011 / $0.1375 / $0.55 | $0.55 / $0.055 / $0.6875 / $2.75 |

The Google Cloud `eu` rates apply the 10% premium that Anthropic's pricing page
documents for regional and multi-region endpoints. Google's own Claude price
table was not readable when checked, so confirm it before quoting `eu` costs.
One-hour cache writes cost twice the input rate. Usage estimates use the Claude
API rate for prompts up to 100,000 tokens. The longer-prompt rate and the `eu`
premium are pending because the ledger records neither prompt length nor
transport.

Haiku 5.5 uses adaptive thinking with `medium` default effort and accepts
`low` through `max`. It rejects budget-based thinking and non-default sampling
settings. Disabled thinking is accepted only at `high` effort or below. Unlike
Opus 5.5 and Sonnet 5.5, it accepts forced tool choice, but a forced call skips
thinking. Thinking blocks are bound to the conversation prefix. Pydantic AI
2.66's profile covers these settings and native JSON schema output, so
structured results use `output_config.format` instead of an output tool.
Catalogue defaults
request summarised thinking. Refusals have no server-side fallback.

Haiku 5.5 is the Anthropic **Light** default and the Anthropic default for
native web search, web fetch, and classification. These helpers send the
basic `web_search_20250305` and `web_fetch_20250910` tools because the profile
override leaves dynamic filtering off. Claude Haiku 4.5 remains in the
catalogue.

### Claude Sonnet 5.5 and GPT-6.1 Sol

The following specifications come from the providers' documentation, checked
on 29 September 2026. Token prices use the same units as the table below:

| Model and API ID | Context / maximum output | Input / cache read / cache write / output | Knowledge cutoff |
| --- | --- | --- | --- |
| [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), `claude-sonnet-5-5` | 1,000,000 / 128,000 | $2 / $0.10 / $2.50 / $10 | June 2026 |
| [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), `gpt-6.1-sol` | 1,050,000 / 128,000 | $2 / $0.10 / $2.50 / $10 | 30 April 2026 |

Both accept text and images, return text, and support streaming, tools, and
structured output. Sonnet 5.5 uses the same Vertex ID as its API ID. Sonnet
5.5 cache reads cost $0.20 until Anthropic cut them to $0.10 on 7 October 2026.

Sonnet 5.5 shares Opus 5.5's request restrictions: adaptive thinking only,
no forced tool choice, and thinking blocks bound to the model and
conversation. Pydantic AI's profiles for both models carry these
restrictions and select native structured output, so a structured result
never forces a tool call that would suppress thinking.
Catalogue defaults request summarised thinking, because Sonnet 5.5 returns
text between tool calls as thinking blocks that are empty by default.

GPT-6.1 Sol accepts `low`, `medium` (default), `high`, `xhigh`, and `max`
reasoning efforts; it rejects `none` and `minimal`. Pydantic AI's 6.1 profile
keeps reasoning always on. The UI's disabled-thinking and `minimal`
preferences both send `low`.

The catalogue no longer lists GPT-5.4, GPT-5.5, GPT-5.6, Claude Opus 4.6 to
4.8, or Claude Sonnet 4.6. Their price rows remain so past usage keeps its
estimates. Agents saved with a removed model fail model resolution until an
operator selects a listed model.

### GPT-6 Sol, GPT-6 Luna, and Claude Opus 5.5

The catalogue exposes these models through the existing agent model selector.
The following specifications come from the providers' documentation, checked
on 22 September 2026. Token prices are USD per million tokens for standard
processing, before regional premiums:

| Model and API ID | Context / maximum output | Input / cache read / cache write / output | Knowledge cutoff |
| --- | --- | --- | --- |
| [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), `gpt-6-sol` | 1,050,000 / 128,000 | $2 / $0.20 / $2.50 / $10 | 20 April 2026 |
| [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), `gpt-6-luna` | 1,050,000 / 128,000 | $0.10 / $0.01 / $0.125 / $0.50 | 18 May 2026 |
| [Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), `claude-opus-5-5` | 1,000,000 / 128,000 | $4 / $0.20 / $5 / $20 | June 2026 |

All three accept text and images, return text, and support streaming, tools,
and structured output. Sol targets demanding coding and agent work; Luna
targets focused, high-volume tasks. Both accept up to 922,000 input tokens.
Their reasoning efforts are `none`, `low`, `medium` (default), `high`, `xhigh`,
and `max`. Praxis uses Responses, which supports reasoning with tools.
Chat Completions permits their function calls only with reasoning disabled.
The SDK maps the UI's `minimal` effort to `low` and removes incompatible
sampling settings while reasoning is active.

For both OpenAI models, prompts above 272,000 input tokens double input and
cache rates and multiply output rates by 1.5 for the entire request. Batch
and Flex halve standard rates; Fast doubles them. Regional processing adds
10%, and EU data residency requires Standard processing. Praxis usage estimates
use base rates; request-specific premiums and discounts are pending.

Opus 5.5 uses adaptive thinking with `medium` default effort. Its five-minute
cache writes cost $5; one-hour writes cost $8. Cache reads cost 5% of base input.
Its ID has no date suffix, including on Google Cloud. Use an enabled Model
Garden model with `ANTHROPIC_VERTEX_LOCATION=global`, `us`, or `eu` and the
configured project. Regional availability and account access require provider
verification; catalogue visibility alone does not prove access.

Pydantic AI profiles cover Sol, Luna, and Opus without local overrides,
including Opus's always-on adaptive thinking, disabled forced tool choice,
native structured output, and thinking-block recovery.

The [Opus migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide)
documents its request restrictions. The model factory reads the model profile
and rejects explicit disabled or budget-based thinking before any request. The UI's disabled-thinking preference only applies where a
provider supports it, so Opus continues thinking. Catalogue defaults request
summarised thinking so progress text remains visible. Thinking blocks retain
their signatures through tool results; after a prefix-binding rejection, the
SDK retries once with its documented stale-block recovery and emits a warning.
Explicit forced tool choice fails locally. Provider computer-use tools remain
outside Praxis's governed tool catalogue.

The provider type defaults are GPT-6.1 Sol for OpenAI **Powerful**, Luna for
OpenAI **Standard**, Opus 5.5 for Anthropic **Powerful**, and Sonnet 5.5 for
Anthropic **Standard**. OpenAI has no **Light** model. Existing saved agent
model selections remain explicit. GPT-6 Luna is also the default for unpinned agents,
conversation names, history summaries, Knowledge Base annotations, native
classification, and the OpenAI web-search fallback. Environment overrides take
precedence. Restart API and worker processes after updating local settings, or
follow the deployment runbook for a deployed environment.

### Google Vertex and Anthropic Vertex

Google Vertex model and embedding calls share a
process-owned Google client per project, location, and retry policy.
`GOOGLE_VERTEX_LOCATION=auto` uses catalogue defaults: Gemini 4 Carbon, Argon, Flash,
and Flash-Lite use `eu`, Gemini 3.1 Pro uses `global`, and embeddings retain
`global`. Explicit locations must appear in the Gemini model's supported
locations. Clients use the SDK's multi-region hostname for `eu` and `us`.
The image-only `gemini-nano-banana-2.1` model uses `global` for `auto`
and accepts explicit `global`. Its location validation lives
in the Vertex client module without adding it to ordinary agent choices.
Image availability and execution both reject unsupported locations before
client construction. A direct Google API key does not override Vertex routing.
Existing explicit `global` settings remain global; select `auto` to adopt
the catalogue defaults. `ANTHROPIC_VERTEX_AI`
selects a process-owned `AsyncAnthropicVertex` client with Application
Default Credentials and `ANTHROPIC_VERTEX_LOCATION` (default `global`). Both
use `GOOGLE_VERTEX_PROJECT`, falling back to `GCP_PROJECT_ID`. Vertex model
IDs come from the catalogue's `vertex_model`; entries without one stay
unavailable. Every API, worker, and eval process calls `close_vertex_clients`
during shutdown. That shutdown also closes and clears the shared provider
HTTP client, including processes that only use direct providers. Repeated
shutdown does not create clients; subsequent acquisition creates an open
client. `AGENT_PROMPT_CACHE_ENABLED` sets Pydantic AI's unified `cache`
setting, which caches instructions, tool definitions, and the conversation on
Claude and on GPT-5.6 and later. Gemini caches implicitly and ignores it. An
agent's own `cache` or provider cache settings take precedence. Catalogue
attribution remains unchanged across transports. Each Claude model requires Model Garden
enablement and a supported location.

### Vertex model lists

Google Cloud projects enable Claude and partner models one at a time, and a
project can be restricted to a subset. The catalogue lists every model Praxis
supports. Each deployment lists the models its Vertex project can use:

```bash
ANTHROPIC_VERTEX_AI=true
ANTHROPIC_VERTEX_MODELS='["claude-haiku-5-5"]'
VERTEX_PARTNER_MODELS_ENABLED=true
VERTEX_PARTNER_MODELS='["mistral:mistral-small-2503"]'
```

`ANTHROPIC_VERTEX_MODELS` holds Anthropic catalogue model IDs.
`VERTEX_PARTNER_MODELS` holds provider-qualified catalogue aliases. Settings
reject either switch without its list. Startup, catalogue reads, and
resolution reject unknown or retired entries. The Anthropic list applies only
while `ANTHROPIC_VERTEX_AI` is true; direct Anthropic keys expose the whole
catalogue.

`is_vertex_model_enabled` in `utils.py` applies the lists. The model picker,
workspace defaults, and sub-agent tier choices omit unlisted models. A saved
agent or settings default that names one fails resolution with a
configuration error rather than a provider request. A partner provider counts
as configured only when one of its models is listed. Native search, fetch, and
classification offer a provider only when its default helper model is
available, through `has_available_helper_model` in `resolution.py`. All
three Anthropic helpers use Haiku 5.5, so a deployment that lists only Haiku
5.5 keeps them. Anthropic web fetch remains unavailable on Vertex.

### Vertex partner models

Partner models use locked, off-loop ADC loading and refresh.
`VERTEX_PARTNER_MODELS_ENABLED` gates construction, and
`VERTEX_PARTNER_MODELS` selects the enabled models. Resolution carries
immutable transport, project, model ID, and location into the factory.
Meta Llama 4 defaults to `us-east5` and Grok 4.20 to `global`, using Chat
Completions. Both Llama models default to 8,192 output tokens because Vertex
rejects requests that omit an output limit. Meta schemas move dictionary-value
constraints into descriptions because Vertex rejects schema-valued
`additionalProperties`; local Pydantic validation retains those constraints.
Prefer European partner endpoints where supported. Meta Llama 4 and Grok
4.20 have no supported European regional endpoint.
Mistral Small defaults to `europe-west4` and uses the publisher
`rawPredict`/`streamRawPredict` API, with endpoint-bound HTTP clients and
the existing Pydantic AI chat model. Its profile sends `max_tokens`.
`VERTEX_PARTNER_MODEL_LOCATIONS` accepts a JSON object of catalogue alias to
supported region. Settings validate the shape; shared model validation
checks aliases and regions at startup, catalogue reads, and resolution.
The removed `VERTEX_PARTNER_LOCATION` setting fails with migration guidance.
Partner models retain maker/alias usage attribution and do not join native
helper provider sets. Shared Vertex shutdown closes all partner clients.

## Add or retire a model

Complete this process in the same change as the catalogue update. Provider
documentation and a catalogue entry alone do not establish live access.

### Add a model

To add a selectable model, complete these steps:

1. Verify the exact API ID, capabilities, context and output limits, thinking
   restrictions, pricing dates, and transport availability in official provider
   documentation. Record source links and the verification date in this guide.
2. In `services/agents/models/registry.py`, add the model's metadata. Catalogue
   order determines the first available model for each provider and model type.
   For Vertex, verify the transport ID, default location, supported locations,
   project access, and Model Garden enablement. Deployments opt in by adding
   the model to `ANTHROPIC_VERTEX_MODELS` or `VERTEX_PARTNER_MODELS`.
3. Check the installed SDK's model profile and request handling. Add a focused
   override only for missing behaviour, including thinking and tool restrictions.
   Preserve credential resolution, routing validation, and retry ownership.
4. In `services/ai_usage/pricing.py`, add effective-dated prices. Read the
   [AI usage reference](ai-usage.md) before changing estimates.
5. Review defaults in `core/settings/`, native helper tools, workspace settings,
   deployment examples, and local setup. Change only the intended defaults.
   Check helper eligibility separately from ordinary agent capabilities.
6. Update affected provider-boundary tests, catalogue fixtures, and owning
   documentation. If tool guidance changes, update the corresponding internal
   skill under `services/agents/runtime/internal_skills/`.
7. Run focused model resolution, factory, helper, and usage tests as applicable,
   backend lint and formatting, and affected frontend checks. Qualify live access
   separately with authorised credentials. Document unverified capabilities as
   pending.

### Retire a model

To remove a selectable model, complete these steps:

1. Verify the provider notice and choose an available replacement. Compare
   transport regions, capabilities, pricing, and saved model settings with the
   replacement. Use the addition process first if it is absent from the catalogue.
2. Search the repository for the retired API ID, catalogue alias, transport ID,
   and display name. Remove the catalogue entry and update every affected
   code-owned default, example, and active test fixture.
3. Add a `core` Alembic data migration for saved agents and workspace defaults.
   Include inactive, built-in, and deleted agents so reactivation remains usable.
   Account for inherited providers and settings that the replacement rejects.
   Review other saved configuration, such as workspace classifier overrides,
   when the retired model is eligible there.
4. Keep migration writes restricted to the retired provider/model selections.
   Use the maintenance connection across workspaces and preserve row-level
   security. Leave historical runs, messages, audit records, and usage unchanged.
5. State the downgrade behaviour explicitly. Do not map every replacement
   selection back to a retired model because some agents selected it directly.
6. Retain historical pricing rows. Update this guide, affected helper references,
   and internal skills whose flow changes. Document required environment override
   changes and the replacement mapping.
7. Verify affected rows move to the replacement and unrelated selections remain
   unchanged. Check migration repeatability and downgrade behaviour, run focused
   provider tests, and run Alembic drift checks against the migrated database.
8. Apply migrations before restarting the API and worker with the updated
   catalogue. Update explicit deployment overrides during the same rollout.

## Retry ownership

Provider HTTP retries have one owner. The shared transport bounds actual
attempts with `LLM_HTTP_RETRY_MAX_ATTEMPTS`, including the first request.
Anthropic, OpenAI, Azure, and partner SDK retries are disabled. Direct Gemini
uses one SDK attempt over that transport; Google Vertex retains its
SDK-owned retry policy. Backoff and `Retry-After` waits remain bounded by
the configured wait limits. Exhausted HTTP responses reach the SDK intact,
including their status and body; connection failures remain connection
failures. Run failures map Pydantic AI's provider error categories to safe
codes, without provider bodies or project details: `model_rate_limited`,
`model_quota_exceeded`, `model_context_window_exceeded`, `model_access_denied`,
`model_not_found`, and `model_unavailable` for overload and server errors.
Provider safety filters map to `model_content_blocked`, covering Pydantic AI's
`ContentFilterError` and OpenAI's in-stream `invalid_prompt` code, which
Pydantic AI leaves uncategorised. Only rate limits tell the user to try again
later. The shared transport pools
up to 1,000 connections, 100 kept alive, matching the provider SDKs.

The API locks Pydantic AI, slim, evals, and graph to 2.67.0, with OpenAI
3.40.0, Anthropic 2.5.0, and Google Gen AI 2.34.0. The manifest retains minimum
version ranges. The OpenAI SDK comes through Pydantic AI's `openai` extra
(`openai>=3.31.0`), which includes the Decisions API. It explicitly selects Pydantic AI's `retries` extra and
Tenacity because the transport imports their retry APIs. The `retries` extra
still depends on legacy HTTPX for upstream deprecated transports, so that
package remains a transitive runtime dependency. Application provider clients
have no legacy HTTPX exception. Framework tests can retain legacy HTTPX where
required. Monty is pinned to 1.0.0.

The [2.67 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.67.0)
adds native Fable 5.2 and Gemini 4 Carbon profiles. The Gemini 4 override
retains only always-on thinking. Native web and image helpers keep using
capability arguments, which remain supported as provider-specific native-tool
fields move to `provider_settings`. Structured output cut off at `max_tokens`
and failing validation raises `UnexpectedModelBehavior` immediately instead
of retrying the same token limit. The runtime uses its existing failure path.

The local retry wrapper remains necessary to return an exhausted response
with its unread body intact. SDKs translate that final response into their
provider error types. Do not replace it with SDK defaults or add a second
retry owner. Rerun adapter request-count tests for future SDK upgrades.

Anthropic requests without `max_tokens` ask for the model's maximum output.
When that exceeds the SDK's non-streaming limit, Pydantic AI streams the
request behind the scenes, so non-streaming helper calls to Claude 5.5
models stream on the wire. Offline tests that mock JSON message bodies set
`max_tokens` to keep the non-streaming path.

## Content-filter failures

Azure Chat Completions uses the shared OpenAI adapter. Pydantic AI 2.66 raises
`ContentFilterError` for an HTTP 400 `content_filter` response, streamed or
not. Praxis settles the run as failed with its generic safe error, without
exposing the provider body or retrying the action.

## Frontend provider labels

Agent provider labels read the catalogue transport and append "via Google Cloud"
for `google-cloud`. Keep transport labels derived from the catalogue; the
classifier provider set is unchanged.
