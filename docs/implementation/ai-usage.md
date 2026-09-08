# AI usage accounting

Read this before changing usage recording, cost estimates, or usage routes.
Backend paths are relative to `apps/api/`.

## Ledger and read boundaries

The following contracts apply in this area:

- `ai_usage_events` is runtime append-only: `praxis_app` may select and insert,
  but may not update or delete. Its exact cardinality is one row per logical
  agent-run invocation (including each approval resume), helper invocation, or
  embedding API batch; `requests` sums provider requests within that row.
  Successful/suspended agent usage is transactional with the terminal or parked
  transition. Failure/cancellation fallback and helper/embedding usage are
  best-effort durable writes through the separate bounded runtime-role AI usage
  pool, so metering cannot consume the normal pool's overflow capacity. Usage
  details must remain bounded, and the ledger must not become a budget or
  admission-enforcement mechanism.
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
