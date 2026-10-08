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
2.50 has no Haiku 5.5 profile, so `provider_model_profile` in `utils.py`
supplies these settings and native JSON schema support. Catalogue defaults
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
| [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), `claude-sonnet-5-5` | 1,000,000 / 128,000 | $2 / $0.20 / $2.50 / $10 | June 2026 |
| [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), `gpt-6.1-sol` | 1,050,000 / 128,000 | $2 / $0.10 / $2.50 / $10 | 30 April 2026 |

Both accept text and images, return text, and support streaming, tools, and
structured output. Sonnet 5.5 uses the same Vertex ID as its API ID.

Sonnet 5.5 shares Opus 5.5's request restrictions: adaptive thinking only,
no forced tool choice, and thinking blocks bound to the model and
conversation. `ADAPTIVE_ONLY_ANTHROPIC_MODELS` in `utils.py` applies the
Opus profile override and local thinking validation to both models, because
the Pydantic AI 2.50 Sonnet 5.5 profile still allows forced tool choice.
Catalogue defaults request summarised thinking, because Sonnet 5.5 returns
text between tool calls as thinking blocks that are empty by default.

GPT-6.1 Sol accepts `low`, `medium` (default), `high`, `xhigh`, and `max`
reasoning efforts; it rejects `none` and `minimal`. Pydantic AI 2.50 has no
6.1 profile, so `provider_model_profile` reuses GPT-6 Sol's profile with
reasoning always on. The UI's disabled-thinking preference sends no effort,
and `minimal` maps to `low`.

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

Pydantic AI 2.50 profiles cover Sol and Luna, and cover Opus's disabled
forced tool choice and thinking-block recovery. The factory adds the remaining
Opus settings through `provider_model_profile` in `utils.py`: thinking always
enabled and native JSON schemas for structured output. Remove the override
when the upstream Opus profile covers both.

The [Opus migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide)
documents its request restrictions. Explicit disabled or budget-based thinking
fails locally. The UI's disabled-thinking preference only applies where a
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
`GOOGLE_VERTEX_LOCATION=auto` uses catalogue defaults: Gemini Flash and
Flash-Lite use `eu`, Gemini 3.1 Pro uses `global`, and embeddings retain
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
client. Anthropic prompt-cache defaults and catalogue attribution
remain unchanged across transports. Each Claude model requires Model Garden
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
failures. Run failures persist and emit the same safe `model_rate_limited`
message for HTTP 429, without provider bodies or project details.

The API locks Pydantic AI, slim, evals, and graph to 2.50.0, with OpenAI
3.19.2, Anthropic 1.8.0, and Google Gen AI 2.25.0. The manifest retains minimum
version ranges. It explicitly selects Pydantic AI's `retries` extra and
Tenacity because the transport imports their retry APIs. The 2.50 retries
module still imports legacy HTTPX for upstream deprecated transports, so that
package remains a transitive runtime dependency. Application provider clients
have no legacy HTTPX exception. Framework tests can retain legacy HTTPX where
required. Monty is pinned to 1.0.0.

The local retry wrapper remains necessary to return an exhausted response
with its unread body intact. SDKs translate that final response into their
provider error types. Do not replace it with SDK defaults or add a second
retry owner. Rerun adapter request-count tests for future SDK upgrades.

## Content-filter failures

Azure Chat Completions uses the shared OpenAI adapter. Pydantic AI 2.50.0
maps an HTTP 400 `content_filter` response to a filtered result for ordinary
requests. Its streaming path instead raises an internal `TypeError` while
handling that result. Praxis settles the run as failed with its generic safe
error, without exposing the provider body or retrying the action. A specific
streamed filter outcome remains unavailable with this SDK version.

## Frontend provider labels

Agent provider labels read the catalogue transport and append "via Google Cloud"
for `google-cloud`. Keep transport labels derived from the catalogue; the
classifier provider set is unchanged.
