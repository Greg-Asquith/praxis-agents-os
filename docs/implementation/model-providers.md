# Model providers and transports

Read this before changing model resolution, credentials, Vertex routing,
or model HTTP retries. Backend paths are relative to `apps/api/`.

## Catalogue and provider clients

LLM providers live in `services/agents/models/`. The catalogue in
`registry.py` is the single source of truth for available models;
`factory.py` builds pydantic-ai models per provider. Resolve credentials
only through the `provider_api_key` seam. Never rely on implicit env
pickup. Direct providers share the retrying HTTP client
(`retrying_http_client()`).

### Google Vertex and Anthropic Vertex

Google Vertex model and embedding calls share a
process-owned Google client per project, location, and retry policy.
`GOOGLE_VERTEX_LOCATION=auto` uses catalogue defaults: Gemini Flash and
Flash-Lite use `eu`, Gemini 3.1 Pro uses `global`, and embeddings retain
`global`. Explicit locations must appear in the Gemini model's supported
locations. Clients use the SDK's multi-region hostname for `eu` and `us`.
Existing explicit `global` settings remain global; select `auto` to adopt
the catalogue defaults. `ANTHROPIC_VERTEX_AI`
selects a process-owned `AsyncAnthropicVertex` client with Application
Default Credentials and `ANTHROPIC_VERTEX_LOCATION` (default `global`). Both
use `GOOGLE_VERTEX_PROJECT`, falling back to `GCP_PROJECT_ID`. Vertex model
IDs come from the catalogue's `vertex_model`; entries without one stay
unavailable. Every API, worker, and eval process calls `close_vertex_clients`
during shutdown. Anthropic prompt-cache defaults and catalogue attribution
remain unchanged across transports. Each Claude model requires Model Garden
enablement and a supported location.
### Vertex partner models

Partner models use locked, off-loop ADC loading and refresh.
`VERTEX_PARTNER_MODELS_ENABLED` gates construction. Resolution carries
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

## Frontend provider labels

Agent provider labels read the catalogue transport and append "via Google Cloud"
for `google-cloud`. Keep transport labels derived from the catalogue; the
classifier provider set is unchanged.
