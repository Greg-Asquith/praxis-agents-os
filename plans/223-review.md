# Plan 223 implementation review

Review date: 23 September 2026. Baseline: `3916f0b8` plus the existing
uncommitted A3 and complete-provider-result follow-ups. This is a local review
record. Review complete. The maintainer authorised R01 and R05 for implementation;
their follow-up is recorded below. The other five findings remain open.

## Authorised implementation follow-up

R01 reuses `reserve_file_revision` before uploading retained results. Its
independent tenant transaction persists only cleanup ownership; the caller still
commits the File, reference, audit, and reservation consumption together. This
explicitly revises the earlier blanket prohibition on a second session for this
cleanup reservation. Keeping that prohibition would prevent durable recovery
after process interruption without introducing a separate storage lifecycle.
The existing upload sweeper retries failed deletion and preserves consumed
reservations after a lost commit response. No dispatch audit behaviour changes.

R05 shares the retained JSON byte limit between retrieval and storage. One budget
counts the complete normalised fan-out envelope and passes remaining capacity
to subsequent accounts and pages. Exhaustion fails the invocation without a
partial report, including nested Code Mode calls. Ordinary account errors stay
isolated and count towards the same allowance.

Verification results appear in the completion record below. R02, R03, R04,
R06, and R07 remain outside this authorised implementation.

## Scope and acceptance contract

Review the current implementation against `REVIEW.md` and
`docs/plans/complete/223-bounded-structured-tool-results.md`, including its A1,
A2, A3 and follow-up decisions. Preserve the accepted changes: hidden snapshots,
previews from the first response, complete provider retrieval, and complete-result
expansion inside the provider card. Old history, free-text truncation, write
evidence and nested Code Mode limits remain separate. The maintainer owns the
manual browser and Vervaunt replay checks and has accepted closure before them.

The review covers completeness, correctness, quality, duplication, established
patterns, complexity, failure handling, permissions, documentation and tests.
Source code remained unchanged during the review. The four P2 findings were
recommended closure fixes; the follow-up implements the two selected by the maintainer.
The three P3 findings can be deferred with an explicit maintenance decision;
they do not independently block release. Open findings do not mean the review
itself is incomplete.

## Issue register

| ID | Priority | Finding | Status | Fix dependencies |
| --- | --- | --- | --- | --- |
| R01 | P2 | Uploaded snapshot loses cleanup ownership before commit | Fixed | Reuses durable upload reservations |
| R02 | P2 | Cancellation during retention lacks a terminal audit | Open | R01 transaction ownership |
| R04 | P2 | Malformed provider rows can become partial successful reports | Open | Characterise before R06 |
| R05 | P2 | Per-account budgets exceed combined snapshot capacity | Fixed | Shared invocation budget |
| R06 | P3 | Branch-heavy execution and pagination functions | Open | Tests for R01, R02, R04, R05 first |
| R07 | P3 | Preview building copies all rows before discarding the copies | Open | Coordinate with R05 and preview part of R06 |
| R03 | P3 | Complete-result rendering parses and transforms data twice | Open | Independent; preserve shared contract |

P2 findings affect correctness, failure handling or bounded resource use. P3
findings are quality and efficiency improvements. None requires expanding the
product scope. No P0 or P1 issue was confirmed.

### Practical importance

This is not evidence that ordinary report retrieval is broken. The focused tests
pass and no normal-path data-loss or cross-workspace exposure was demonstrated.

1. **R05 has the highest practical resource risk.** Large reports across several
   selected accounts can accumulate far more data than the final snapshot accepts.
   Its priority depends on report sizes and how often multi-account fan-out runs.
2. **R01 matters on failed or cancelled saves.** It leaves private data unmanaged
   and unaccounted for. It is a retention/cleanup problem, not a demonstrated data
   disclosure. The underlying helper weakness already existed.
3. **R02 is an operational and governance gap.** It affects cancellation during
   the added save stage, not ordinary successful invocation audits.
4. **R04 is defensive correctness.** It requires malformed provider responses.
   Its production frequency is unproven, but silent omission contradicts the
   slice's explicit completeness promise.
5. **R03, R06 and R07 are lower-priority maintenance.** Duplicate work and high
   complexity are confirmed. A production slowdown or outage from them has not
   been established. They are worth addressing when touching the relevant code,
   without delaying an otherwise sound release solely for cleanup.

Recommended decision: address the four P2 gaps before declaring the complete-data
and failure-handling contracts closed; track the P3 work separately if needed.

### R01: Retained objects lose cleanup ownership before database commit

- Priority: P2. Confidence: high. Effort: M. Fix risk: high.
- Origin: the new save path exposes an existing weakness in unreserved File
  creation to every oversized direct read.
- Evidence: `apps/api/services/files/save_tool_result.py:44` calls
  `create_file_with_revision` without a reservation. The storage write completes
  at `apps/api/services/files/create_file_with_revision.py:116`, before subsequent
  reference creation and the dispatch commit. `services/storage/utils.py:56`
  cleans up only when the write itself raises. `services/agents/runtime/dispatch.py:710`
  rolls back a failed commit without removing that object. Paths in this paragraph
  without an app prefix are relative to `apps/api/`.
- Impact: a failure or cancellation after upload leaves complete provider data
  in private storage without a File or revision row. Storage accounting misses
  it. `apps/api/services/jobs/handlers/sweep_deleted_files.py:69` and `:127`
  only discover deleted Files and expired upload reservations, so neither sweep
  can recover this object. Retried reports accumulate unmanaged objects.
- Correction: retain ownership of the pending object until transaction settlement.
  Distinguish a confirmed rollback from an uncertain commit before deleting data.
  Preserve the plan's prohibition on an intermediate commit or second session;
  copying `reserve_file_revision` unchanged violates that decision. If durable
  recovery requires changing this contract, resolve that design explicitly first.
- Closure: test reference-creation failure after upload, failed commit, interrupted
  upload, cancellation after upload, cleanup failure, and successful commit.
  Inspect both database rows and storage objects. The existing failure scenario
  in `apps/api/tests/scenarios/test_retained_tool_results.py:224` checks only rows.
- Interactions: implement with R02. A shared low-level correction also needs
  regression coverage for native generated File outputs. Audit correctness does
  not imply object cleanup, and object cleanup does not imply audit correctness.

### R02: Cancellation during retention has no terminal tool audit

- Priority: P2. Confidence: high. Effort: S–M. Fix risk: medium.
- Origin: introduced by the asynchronous post-handler retention stage.
- Evidence: `apps/api/services/agents/runtime/dispatch.py:568` catches cancellation
  around the handler only. Retention at `:640` catches only `OutputContractError`.
  The commit branch at `:712` records failures only for `Exception`, which excludes
  `CancelledError`.
- Impact: cancelling during storage, reference creation or retained-result commit
  leaves no terminal cancellation audit for the provider call.
- Correction: cover result processing and transaction settlement with the same
  cancellation ownership as execution. Preserve cancellation propagation, safe
  rollback, invocation identifiers and exactly one terminal audit.
- Closure: inject cancellation during storage, after successful upload and during
  commit; assert cancellation propagates and one terminal audit exists. The
  existing dispatch cancellation test cancels inside the handler only.
- Interactions: R01 owns pending object cleanup; R02 owns audit coverage. Both
  must survive the focused dispatch simplification considered under complexity.

### R03: Complete report rendering repeats full parsing and transformation

- Priority: P3. Confidence: high for duplicate work. Effort: S–M. Fix risk: low–medium.
- Origin: introduced by retained-result expansion.
- Evidence: `apps/web/src/integrations/read-presenter.tsx:100` parses for validation,
  discards the parsed value, and parses again at `:62` for display. The single-result
  path repeats this at `:152` and `:132`. Ads field discovery follows the same
  pattern in `apps/web/src/integrations/google_ads/presenters/report-fields.tsx`.
  `apps/web/src/components/tool-ui/retained-result.tsx:23` recreates its selector
  on every render.
- Impact: opening a complete report duplicates row validation, transformation and
  allocation. Subsequent renders repeat the work. This is significant work on
  the newly uncapped results; no browser freeze or timing claim has been measured.
- Correction: keep the parsed result from a stable selection or memoisation
  boundary and pass it to rendering. Preserve the raw value needed for list-count
  validation and notices. Do not weaken provider result guards.
- Closure: assert one parse for a stable complete result, retain malformed-data
  rejection and retry behaviour, and run all provider preview regressions with
  a large result fixture. Keep user/workspace cache scoping and revision-one reads.

### R04: Report parsing silently drops malformed provider data

- Priority: P2. Confidence: high. Effort: M. Fix risk: medium.
- Origin: tolerant parsers predate the follow-up; the new complete-retrieval
  guarantee relies on them without validating their omissions.
- Evidence: `apps/api/integrations/google_ads/operations/utils.py:38` skips invalid
  stream pages and non-dictionary rows. `google_ads/operations/run_report.py:35`
  then returns `truncated=False`. `google_ads/operations/list_report_fields.py:191`
  skips fields that fail validation, while `:145` counts raw entries towards its
  completeness check. Analytics counts raw rows in
  `google_analytics/operations/run_report.py:100`, then drops invalid rows in
  `google_analytics/operations/utils.py:136`. Abbreviated provider paths are
  relative to `apps/api/integrations/`.
- Impact: malformed responses can produce successful saved data that omits rows
  or fields. Read-only probes returned one complete Ads row from a stream with
  one valid row, a null row and an invalid page; one complete catalogue field
  from two raw entries; and one truncated Analytics row after counting two raw
  rows as complete. Retention cannot recover content discarded before dispatch.
- Correction: validate report response structure and accepted row/field counts
  at the report boundary. Fail the affected retrieval explicitly rather than
  representing parser loss as source truncation. Preserve legitimate empty
  responses, provider-omitted optional fields and explicit top-N requests.
- Closure: malformed rows on later pages, invalid catalogue entries, mismatched
  cells/headers, valid empty reports and omitted optional fields must have explicit
  tests. Confirm account-level failure remains visible beside other accounts.
- Interactions: add these cases before R06 extraction. `stream_rows` has unrelated
  discovery and mutation consumers; do not tighten all of them without separate
  evidence and regression tests. R05 must not hide partial retrieval as success.

### R05: Per-account retrieval limits do not bound the combined snapshot

- Priority: P2. Confidence: high for the mismatch. Effort: M. Fix risk: medium.
- Origin: removing provider row caps makes the existing fan-out accumulation
  materially more expensive.
- Evidence: `apps/api/integrations/google_ads/tools/run_report.py:56` grants each
  account a fresh full File allowance at `:65`. Analytics creates an independent
  `ReportResultBudget` in `operations/run_report.py:27`; Search Console creates
  one in `operations/query_search_analytics.py:34`.
  `apps/api/services/integrations/context/execution.py:38` retains every successful
  account result, with up to 20 targets allowed by `context/schemas.py:18`.
  `apps/api/services/files/save_tool_result.py:34` applies one limit to the final
  combined JSON only after dispatch has serialised and previewed it.
- Impact: two 60 MiB normalised account results can each pass retrieval checks
  but cannot fit the default 100 MiB snapshot. The per-account design permits
  roughly 2 GiB of source payload across 20 accounts before final processing and
  failure. Python object and serialisation overhead add to that; exact peak
  memory has not been measured. Concurrent runs multiply this exposure.
- Correction: enforce an invocation-level retrieval/accumulation budget with
  room for the final normalised envelope. Stop before accumulating a result that
  cannot be retained; report the limit explicitly without cutting rows. Share
  the File byte-limit definition instead of introducing another independent cap.
- Closure: use small configured limits to test individually valid accounts whose
  aggregate exceeds the limit, a combined report below it, one failed account,
  cancellation and nested Code Mode. Assert later accounts/pages are not fetched
  after aggregate exhaustion and that no partial result claims completeness.
- Interactions: R07 reduces unnecessary copying but cannot correct this budget
  mismatch. Preserve Code Mode's accepted separate limits and complete nested
  inputs. Do not introduce truncation or a new row cap as the fix.

### R06: Separate result settlement and provider pagination responsibilities

- Priority: P3. Confidence: high. Effort: M. Fix risk: medium–high.
- Origin: mixed. Dispatch was already complex; the slice raises its measured
  complexity from 21 to 23. BigQuery rises from 12 to 18. Analytics is now 12;
  its previous version passed a threshold of 10. The new `_preview_paths` is 11.
- Evidence: Ruff C901 reports `apps/api/services/agents/runtime/dispatch.py:428`,
  `apps/api/integrations/bigquery/operations/run_query.py:49`,
  `apps/api/integrations/google_analytics/operations/run_report.py:21`, and
  `apps/api/services/agents/runtime/structured_results.py:101`.
- Impact: BigQuery now combines authorisation, billed-byte validation, execution,
  paging and completeness checks. Dispatch combines handler auditing with a
  separate result-save/commit stage; R02 illustrates the missed boundary.
  `_preview_paths` combines explicit path traversal and inferred list discovery.
- Correction: extract focused provider-specific page collectors, and make
  result settlement/cancellation ownership explicit in dispatch. Separate explicit
  path matching from automatic preview discovery if that makes each branch easier
  to inspect. Keep checks close to the actions they protect. Do not build a generic
  pagination framework or weaken authorisation merely to improve a metric.
- Closure: retain BigQuery authorisation, row-filter, billed-byte and job-routing
  tests; provider repeated-token, changed-schema, offset, explicit-limit and
  incomplete-page cases; and dispatch approval, cancellation and storage-failure
  cases. Re-run C901 at threshold 10 on changed functions and document any justified
  residual complexity rather than adding suppressions.
- Interactions: establish R01/R02/R04/R05 failure tests before restructuring.
  Apply the preview extraction with R07 so list traversal is not rewritten twice.

### R07: Preview construction deep-copies rows it immediately replaces

- Priority: P3. Confidence: high. Effort: S–M. Fix risk: medium.
- Origin: introduced by the shared preview builder.
- Evidence: `apps/api/services/agents/runtime/structured_results.py:62` calls
  `deepcopy(result)` before the search. Lines 68–72 then replace each copied
  previewable list with a slice from the original list. The copied rows are
  discarded without contributing to the preview.
- Impact: preview generation duplicates every row container synchronously even
  when only 50 rows are shown. With large complete reports, this wastes memory
  and blocks the event loop doing work proportional to all rows. No exact latency
  or out-of-memory threshold is claimed.
- Correction: construct the projected containers and metadata while slicing the
  selected lists, without recursively copying all rows that will be omitted.
  Preserve the original result and the independence of each candidate envelope.
- Closure: preserve original-input immutability, root lists, empty lists, fan-out
  identity/errors, both field lists, explicit wildcard paths and largest-fitting
  prefix tests. Add a representative large-result allocation/timing probe to the
  verification record; require its output to remain identical and bounded.
- Interactions: R05 bounds aggregate input; R07 avoids duplicating that input.
  Neither correction substitutes for the other. Keep preview discovery changes
  with R06 and leave final serialisation byte/character semantics unchanged.

## Fix order and shared regression risks

1. Add failure cases for R01/R02 and malformed-provider cases for R04. They define
   the expected boundaries before any extraction.
2. Fix R01 and R02 together. Verify both storage and audit state for each failure
   point. Do not delete an object after an uncertain commit without proving ownership.
3. Fix R04. Keep provider-specific optional-field semantics and fan-out errors.
4. Implement R05 and R07 with their resource-limit cases. Keep complete retained
   data, minimum preview coverage and Code Mode rules unchanged.
5. Apply R06 focused extractions while the relevant fixes are fresh. Each extraction
   must preserve the already-established failure and authorisation behaviour.
6. Fix R03 independently against the same preview contract, then run the combined
   backend and frontend gates. Reconcile owning docs and completion records with
   the final behaviour and exact verification outcomes.

| Shared boundary | Issues | Regression to prevent |
| --- | --- | --- |
| Snapshot upload, rollback and cancellation | R01, R02, R06 | Orphaned data, deleted committed data, missing or duplicate audits |
| Provider rows and account results | R04, R05, R06 | Silent partial success, lost account errors, broken authorisation |
| Preview projection and resource use | R05, R06, R07 | Changed prefixes/counts, mutated originals, unbounded combined memory |
| Complete browser expansion | R03, R04, R07 | Weakened guards, mismatched counts, changed cache scope or revision |
| Native and nested computation | R01, R05 | Broken generated-file persistence or incomplete Code Mode inputs |

## Requirement coverage and closure evidence

These statuses describe the implementation, not whether the review was performed.
Automated results below are this review's fresh checks unless labelled historical.

| Requirement | Evidence inspected | Assessment |
| --- | --- | --- |
| Original output validation before preview | Dispatch validation order; structured-result and result-bound tests | Implemented; focused tests pass |
| Strict envelope and valid projected provider data | `StructuredResultPreview`, `validate_output`, report preview tests | Implemented; focused tests pass |
| Bounded first response and stream | Preview size search; `events.public_function_tool_result`; retained-result scenarios | Implemented; scenarios inspected, database rerun outstanding |
| Public result budget stays separate | `prepare_public_result`, retention metadata, public-budget scenario | Implemented; focused bound tests pass |
| Every returned row survives | Provider paging and shapers; complete-report tests | Incomplete on malformed payloads: R04 |
| Retrieval remains bounded and cancellable | HTTP streaming limits, budgets, fan-out and dispatch | Gaps: R02, R05, R07 |
| Private hidden storage and no folders | Save service, marker/migration, list/search/picker/context filters | Implemented; inspected scenario coverage |
| Storage transaction and save-failure retry | Save service, dispatch settlement and failure scenarios | Retry implemented; storage cleanup incomplete: R01 |
| Audit includes sizes and File ID | Tool audit writer and retained-result scenarios | Success path implemented; cancellation gap: R02 |
| Existing File accounting and retention | Usage query and deletion/upload sweep | Normal snapshots included; orphan recovery gap: R01 |
| Workspace isolation and authorised reference reads | Existing File resolver/RLS seams and cross-workspace scenario | No defect found; database rerun outstanding |
| Pinned revision via read_file/run_code | File reference creation, revision resolution and native input bridge | Implemented; scenarios inspected |
| Stable later model requests | Retained-history scenarios and unchanged history paths | Implemented; deterministic scenario coverage inspected |
| Provider descriptions and complete-data instructions | Report definitions, shared guidance, owning provider docs | Implemented, including accepted follow-ups |
| Same-card complete result and error/retry UI | Query revision selection, component, shared/provider presenters | Implemented; 57 focused frontend tests pass; R03 efficiency gap |
| Counts, aggregates, account errors, pagination and full exports | Provider parser/presenter tests and DataTable path | Implemented; preview exports intentionally contain preview rows |
| Complete nested Code Mode inputs | Parent-call exclusion and Code Mode scenario | Implemented; preserve during R05 |
| Native provider input limits | Native bridge and descriptions | OpenAI/Anthropic mounts; Google bounded text by design |
| Writes/multimodal/free text/old history excluded | Dispatch exclusions and focused tests | Accepted scope preserved |
| Documentation and threat model | Owning guides, A1/A2/A3 records, threat-model retained channel | Updated; final corrections must update relevant claims |
| Clean lint and formatting | Fresh backend Ruff and diff checks | Pass; C901 diagnostic separately finds R06 |
| Full backend and frontend acceptance gates | Historical completion records; fresh focused checks | Not rerun in full during this review; required after fixes |
| Live Vervaunt replay and browser/CSV check | Parent/A3 manual ownership decision | Unverified, explicitly owned by maintainer after closure |

## Commands for implementation closure

From `apps/api`, run the focused non-database gate:

```sh
uv run pytest -q tests/services/agents/runtime/test_structured_results.py tests/services/agents/runtime/test_result_bounds.py tests/integrations/test_report_previews.py tests/integrations/test_complete_reports.py tests/integrations/google_ads/test_report_stream.py
uv run ruff check .
uv run ruff format --check .
```

Run the changed failure tests and retained-result scenarios against an explicitly
configured, migrated test database. A plain pytest invocation can skip database
tests. Use the setup in `docs/implementation/local-development.md`; do not assume
an existing local database belongs to this project.

```sh
uv run pytest -q tests/services/agents/runtime/ tests/scenarios/test_retained_tool_results.py tests/scenarios/test_retained_report_results.py tests/scenarios/test_native_run_code.py tests/services/files/ tests/integrations/google_ads/ tests/integrations/google_analytics/ tests/integrations/google_search_console/ tests/integrations/bigquery/ tests/security/test_workspace_rls.py
```

From `apps/web`, run the focused gate while changing the presenter, then `pnpm check`:

```sh
pnpm exec vitest run tests/components/tool-ui/result-preview-query.test.ts tests/components/tool-ui/retained-result.test.ts tests/integrations/result-previews.test.ts tests/features/conversations/message-parts/parse.test.ts
pnpm check
```

Finish with root `make check` when the project's documented database is available,
or report the exact equivalent database-backed gates and any failures. Include
`git diff --check`. If a correction changes schema or streaming contracts, also
run the documented migration or stream-protocol gates. Do not claim the historical
975/2,482 test totals as results for the corrected worktree.

## Verification recorded in this review

### Implementation completion

The R01/R05 follow-up was verified against a fresh local `praxis_223_test`
database on port 55432. The default port belongs to another deployment, and the
existing `praxis_test` has an incompatible migration history; neither was reset.

- File/storage regression gate: 282 passed, including 17 retained-result
  scenarios. Committed transactions cover reference failure, interrupted writes,
  cancellation, commit failure, lost commit responses, successful preservation,
  cleanup retry, and repeated cancellation while the provider write holds its lock.
- Combined runtime, report-provider, context, retained/native-code scenario,
  and workspace-isolation gate: 1,886 passed and one stale registry assertion
  failed. The assertion still expected the superseded Ads field limit of 50.
  Updated it for the existing optional uncapped contract; all 117 registry tests
  then passed. No product behaviour changed for that correction.
- New aggregate-budget tests: 14 passed. Direct and nested dispatch overflow
  scenarios: two passed. The scenarios prove no third-account request, no partial
  rows, no retained File, and an explicit audited failure.
- Full backend Ruff lint and formatting pass (2,002 files). Changed shared
  budget/storage functions pass the additional C901 threshold-10 diagnostic.
  `git diff --check` passes.
- No live provider calls, full frontend gate, or browser replay ran. This
  follow-up changes backend behaviour only. No schema change or Git commit.

The following results describe the original review, before implementation.

- Backend focused gate: 57 passed. Files: `test_structured_results.py`,
  `test_result_bounds.py`, `test_report_previews.py`, `test_complete_reports.py`,
  and `google_ads/test_report_stream.py`. These are deterministic checks and do
  not prove database transaction or live provider behaviour.
- Frontend focused gate: 57 passed across preview query, retained-result component,
  provider result previews and transcript parsing tests.
- Complexity diagnostic using Ruff C901 with threshold 10: `run_query` 18,
  Analytics `run_report` 12, `dispatch_tool_execution` 23, `_preview_paths` 11.
  This is an extra review diagnostic, not an enabled repository lint rule.
- Baseline C901 checks: dispatch 21 before A1, BigQuery 12 before the dirty
  follow-up, Analytics at or below 10 before the dirty follow-up.
- Backend full lint and format checks pass: 2,001 files already formatted.
- Read-only preview allocation probe: 100,000 small nested rows produced a 50-row,
  2,334-character preview, with 45.1 MiB peak additional traced allocation and
  0.740 seconds elapsed. Input allocation occurred before tracing. `tracemalloc`
  adds timing overhead, so this is diagnostic evidence for R07, not a production
  latency benchmark or an isolated measurement of `deepcopy` alone.
- `git diff --check` passes for the pre-existing worktree changes.
- No source edits, deployment, provider calls or Git commits.

## Confirmed boundaries and rejected candidates

- Hidden discovery filters cover Files lists and searches, entity pickers,
  processing counts and automatic prompt listings. Explicit authorised reads
  remain allowed by design.
- Storage accounting includes hidden revisions. The aggregate storage limit is
  deliberately a soft warning, so absent hard-quota enforcement is not a defect.
- Conversation revision pins feed both `read_file` and native `run_code`.
  The browser explicitly reads the original revision and scopes cached data to
  both user and workspace.
- Complete-table pagination limits visible rows, while copy and CSV export use
  all loaded rows. Preview-only exports are documented behaviour.
- The threat model documents retained-result reads and their untrusted framing.
- Existing large histories and Google native code's bounded text inputs remain
  accepted exclusions, not unfinished work in this slice.
- BigQuery duplicate result-column concern was rejected: the provider documents
  unique top-level result names. See the
  [GoogleSQL query reference](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax).
- Realtime Analytics' 250,000-row request limit and lack of offset pagination
  match the [official request contract](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runRealtimeReport).
  Its explicit source-truncation notice is an accepted limitation.

## Review limits

This is a targeted review of plan 223, its direct dependencies and follow-ups,
not a repository-wide audit. It does not certify unrelated integrations,
production deployment, live provider behaviour, actual model token usage or
dependency advisories. No dependencies changed in this slice, so a new production
dependency audit was not run. Database-backed scenarios, migrations, the full
frontend gate and manual checks were inspected through their implementation and
existing records but not freshly executed in full. These limits do not weaken
the concrete code-backed findings; they prevent a broader verification claim.
