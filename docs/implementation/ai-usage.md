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
- Platform usage reads are confined to `services/ai_usage/platform_queries.py`,
  use the sanctioned maintenance session, and set each transaction read-only
  before its first query. The `/platform-usage` router is super-admin-only;
  it exposes aggregate usage and workspace/user/model/purpose attribution but
  never workspace content. RLS remains unchanged.


## Invocation settlement

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
