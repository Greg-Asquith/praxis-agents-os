# AI usage accounting

Read this before changing usage recording, cost estimates, or usage routes.
Backend paths are relative to `apps/api/`.

## Ledger and read boundaries

The following contracts apply in this area:

- `ai_usage_events` is runtime append-only: `praxis_app` may select and insert,
  but may not update or delete. Its exact cardinality is one row per logical
  agent-run invocation (including each approval resume), helper invocation, or
  embedding API batch; `requests` sums provider requests within that row.
  Agent usage is transactional with lifecycle settlement, including when
  another actor already recorded the terminal verdict. Helper, embedding, and
  shutdown-only usage use the separate bounded runtime-role AI usage pool.
  Usage details must remain bounded, and the ledger must not become a budget
  or admission-enforcement mechanism.
- Workspace usage reads use the ordinary tenant runtime session, retain an
  explicit workspace predicate, and price UTC-day buckets before wider folds.
  The `/usage` router is owner/admin-only. Costs are read-time estimates from
  effective-dated public rates; unknown models remain unpriced. Native image
  helpers retain known model/quality/size metadata so GPT Image 2 and Gemini
  3.1 Flash Image output estimates are added to, not substituted for, mainline
  helper-model token cost. Unavailable image-model input remains disclosed
  rather than guessed.
- Direct GPT Image 2.5 requests record one invocation under Flare or Sunburst,
  with no Luna token charge. Returned input/output totals and bounded
  text/image modality details are retained. Missing usage stays unknown;
  attempted requests still record an invocation. Image costs remain unpriced
  because generic ledger rates cannot distinguish text and image input or
  their cached subsets. These calls increment `unpriced_image_generations`,
  displayed as **Incomplete image outputs**, and returned tokens count as
  unpriced. Historical Responses helper rows retain their helper-token costs;
  historical GPT Image 2 output estimates remain unchanged. Modality-aware
  image pricing is pending.
- Platform usage reads are confined to `services/ai_usage/platform_queries.py`,
  use the sanctioned maintenance session, and set each transaction read-only
  before its first query. The `/platform-usage` router is super-admin-only;
  it exposes aggregate usage and workspace/user/model/purpose attribution but
  never workspace content. Platform-owned costs appear under **Platform** in
  the workspace breakdown. Workspace usage reads and budgets exclude them.


## Platform ingestion accounting

Usage events and monthly embedding counters carry an explicit `scope`.
Workspace ownership requires a workspace ID. Platform ownership requires no
workspace ID and maintenance-only writes. Platform events retain provider,
model, purpose, and optional acting user. They accept `kb_annotation` and
`embedding_kb_ingest`, and reject agent, run, and conversation provenance.
Query embeddings remain owned by the requesting workspace.

`embed_texts` requires a maintenance session for explicit platform scope.
Its durable recorder commits the platform ledger event and embedding counter
in one maintenance transaction, including known usage from partial failures.
The caller's rollback cannot remove those costs. Workspace recording retains
the bounded runtime metering pool and existing soft embedding-token budget.
The shared helper meter accepts platform annotation only with an explicit
maintenance session. Platform knowledge authoring and ingestion jobs remain
pending.

`PLATFORM_INGESTION_MONTHLY_CALL_BUDGET` defaults to 1,000 and accepts values
from one to 1,000,000. Before each platform embedding batch or annotation helper
invocation, a separate maintenance transaction atomically reserves one call
in `platform_ingestion_usage`. Concurrent workers share the same UTC-month
counter. Exhaustion or reservation failure stops the call before provider I/O.
Failed attempts and interrupted work retain their reservation. Empty embedding
input does not reserve a call. The counter grants no runtime access and does
not use the usage ledger for admission.

This is a call admission limit, not a dollar or token cap. Each embedding batch
retains the configured text-count and per-text character bounds. Provider
request counts, retries, and returned tokens remain separate usage measures.
Annotation callers retain their bounded chunk and model-call contracts.
Changing the setting applies to subsequent admissions. A new UTC month starts
a separate counter without deleting prior accounting.

## Invocation settlement

Image tools retain their existing invocation meters. Pydantic AI 2.42's
direct image adapters return usage only after accepting image output. Empty
OpenAI responses and empty or content-filtered Google responses can contain
usage that the adapters discard when raising. Switching to result-only
metering loses those counters. Retain the OpenAI SDK adapter and Google
Agent helper until the public direct API exposes failed-response usage.
Do not replay image requests to recover accounting or add `result.cost()`
to the ledger. Image pricing and historical price records remain unchanged.

Each execution and approval continuation receives a server-owned invocation
UUID before execution. Its agent usage event ID derives from the run ID,
invocation ID, and purpose. Repeated insertion of a matching event is a no-op.
A conflicting payload records bounded mismatch evidence and never updates
the existing ledger row. Other callers retain their generated event IDs.

Delegated invocations share the cumulative provider usage object. Each child
captures its entry baseline and freezes its final delta before awaiting
finalisation. It adds that interval once to its parent's fixed-size in-memory
aggregate. Each invocation freezes its own delta less child intervals, so
attribution does not depend on whether a child ledger transaction commits.
Normal and interrupted settlement use the same frozen payload and event ID.
Approval continuations capture a fresh baseline and identity.

Finalisation writes are bounded and best-effort. Missing child usage stays
attributed to that child even if its insert fails; the parent's model is never
charged for that interval. Exhausted persistence logs the run, invocation, provider, model, and
counters as accounting-incomplete evidence. A later insertion of the same
payload remains idempotent. Total database failure can leave ledger gaps;
the runtime does not replay external effects to reconstruct accounting.
