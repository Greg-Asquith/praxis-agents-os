# Praxis Agents OS — Unified Roadmap

Date: 2026-07-02
Baseline: `f83d210`
Status: **Authoritative ordering document.** Supersedes the sequencing in
`DONOR_PORT_ROADMAP.md` and `docs/legacy/ROADMAP_QUESTIONS_GAPS.md`. Both
remain as references: the donor roadmap (§4) holds the subsystem *designs*;
the questions/gaps doc holds the full open-question inventory.
`docs/legacy/NOTES.md` is fully absorbed by this document (retired to
`docs/legacy/`).

Each numbered item below becomes one implementation plan under `docs/plans/`
(existing template: Status block, STOP conditions, follow-ups), added to the
README table as it is written. Numbers 010–051 are all written plan docs
(021–029 added 2026-07-02: Lane O, Phase 1, Gate G3 note; 030 completed
2026-07-06 as the first Phase 3 substrate item; 031 completed 2026-07-06
as the file schema/contract substrate; 032 completed 2026-07-06 as the
file upload/lifecycle route slice; 033 completed 2026-07-06 as the
background file processing slice; 034–051 written 2026-07-06 in a full
planning pass after 029 executed — see `docs/architecture/governance.md` —
covering Phases 3–6 end to end, consistency-reviewed against the landed
030–033 substrate). Cleanup plans C01-C05 were integrated 2026-07-06 from
`plans/improvements/`; their source files keep local numbers 001-005 until
completion, while the master roadmap tracks them with `C` prefixes so they do
not collide with existing roadmap plans. C01, C02, C03, and C04 were completed
2026-07-06 and moved to `plans/complete/`. Plan 035 was completed
2026-07-06 and moved to `plans/complete/`; Plan 036 and Plan 024 were completed
2026-07-07 and moved to `plans/complete/`. Every reserved number now has a
written plan. Plans 052 (Lane O homepage redesign) and 053–060 (Lane H,
harness hardening — added 2026-07-07 by a directed harness-engineering
review, grounded at `c2f08cc` with installed-package probes) extend the
roadmap past the reserved range; Lane H is defined in §4 below and adds
Gate G5. Plan 061 (integration provider packaging, decision D10) was
written and executed 2026-07-07 as a design-note plan in the 029 mold —
it produced `docs/architecture/integration-packaging.md` and amended
037/039/041/042 before any Phase 4a code exists.

---

## 1. Targets

What "done" looks like for this generation of the platform — four pillars,
each with a concrete end state:

1. **Harness** — every agent capability flows through one typed tool
   registry with one audited dispatch choke point; approvals, policies,
   delegation envelopes, retries, token caps, and tracing are uniform across
   native tools, integration tools, and (later) MCP tools.
2. **Context** — the system prompt is assembled once, from budgeted blocks:
   agent identity, skills catalog, core memories, active integration
   context, available files. Everything else (KB, notes, documents) is
   reached by the agent through search tools, not pre-injection.
3. **Surfaces** — chat, schedules, files, knowledge, memory, and artifacts
   are all first-class product screens. Nothing an agent can do is
   invisible: memories are editable, artifacts are versioned and diffable,
   tool calls are audited and viewable.
4. **Operations** — workspace-scoped governance (role matrix), audit and
   security log visibility, quotas and cost controls, retention and
   deletion lifecycle, secret references over stored secrets.

These match current agent-harness practice (single registry + choke point,
server-injected context, agentic search over one-shot RAG, human-legible
memory, sandboxed artifact serving). The deliberate divergences — Postgres
only, no memory framework dependency, MCP deferred, knowledge graph dropped
— are justified in `DONOR_PORT_ROADMAP.md` §1/§5 and stand.

## 2. Decision Log

Decisions that shape the roadmap structure. D1–D4 were confirmed by
product interview on 2026-07-02.

| # | Decision | Outcome | Binds at |
|---|----------|---------|----------|
| D1 | Operational surfaces vs donor phases | **Parallel lane.** Registry work starts immediately; schedules UI, audit/security viewer, workspace/invite UX run alongside and must complete before integrations ship side-effect tools (Gate G1). | 021–024 / Gate G1 |
| D2 | Runtime hardening plans 010–015 | **Split by leverage.** 010/012/011 landed first; 013 landed after 018 to preserve capability-load pairs; 014 (OTel) gates Phase C; 015 is filler. | Lane R |
| D3 | Multi-connection per provider | **Full multi-connection in v1.** Multiple simultaneous connections per provider per owner from the first integrations release: no one-active-per-provider uniqueness constraint, a required user-set label per connection, active-context resolution across N connections, and connection pickers in the v1 UI. Resolves the NOTES-vs-donor conflict in favor of the agency use case; adds scope to 037/040/042. | 037/040/042 |
| D4 | First integration providers | **Gmail (user OAuth) + Google Ads (workspace OAuth + MCC→account discovery) + Airtable (api-key + secret reference).** Google Ads over GA4: richer resource hierarchy and closer to the agency product. Its write operations spend real money — they default to `approval` in tool policy and are the first hard test of Gate G1. | 041 |
| D5 | Schema branch | All roadmap tables go in **`core`** (platform infrastructure); `app` stays reserved for verticals. (From donor roadmap §2, confirmed.) | all migrations |
| D6 | Skills before memory/KB injection | Confirmed: 018 must land before 046/048 so system-prompt assembly is designed once. | Gate G2 |
| D7 | MCP client support | Deferred until the native registry is stable and the catalog is big enough to need `defer_loading`. Not in any phase below. | — |
| D8 | Client-side password hashing | Rejected (no threat model it addresses; passwords already hashed at rest, TLS in transit). Closes the NOTES item. | — |
| D9 | OKF and Google Knowledge Catalog posture | **Own the KB; use OKF for compatibility.** Praxis owns storage, indexing, permissions, jobs, audit, retention, and agent behavior. Open Knowledge Format informs markdown/frontmatter structure, stable concept identifiers, and import/export. Google Knowledge Catalog may become an optional integration/source/sink later, not the runtime substrate. | 044–047 |
| D10 | Integration provider packaging | **Self-contained, individually-enableable provider packages on both sides; the registry and dispatch choke point stay singular.** Backend: one package per provider under `apps/api/integrations/` exporting an `IntegrationProviderPlugin`, loaded only when named in `INTEGRATIONS_ENABLED_PROVIDERS`; per-provider pyproject extras for SDK deps; machine-enforced import laws. Frontend: per-provider lazy modules under `apps/web/src/integrations/` (one chunk each), default-first server-declared tool presentation, custom rows exceptional; no pnpm workspace (rejected with revisit trigger). Design note: `docs/architecture/integration-packaging.md` (plan 061, DONE 2026-07-07); binds 037/039/041/042 via amendments. Motivated by the donor system's everything-always interconnection failure and customers wanting disjoint provider subsets. | 037–042 and every later provider |

Per-subsystem open decisions that do *not* change ordering (embedding
default, contextual-annotation default, scratch TTL, memory approval
defaults, artifact share timing, schedule permissions, audit retention…)
stay in `docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Open Product Decisions and are
resolved inside the plan that implements them. Every such plan must open
with a "Decisions taken" block.

## 3. Gates

Hard checkpoints — cheap to state now, expensive to discover later:

- **G0 (baseline)**: plan README reconciled with code (009 delegation is
  DONE; statuses verified) before any 021+ plan is written.
- **G1 (side effects need eyes)**: 021–023 (schedules + audit/security
  surfaces) and 014 (OTel) complete before 041 (first real providers)
  ships agent-callable integration tools.
- **G2 (prompt assembly once)**: 018 (runtime skill disclosure) complete
  before 046 (KB agent tools) and 048 (memory), so skills / memories /
  active context / files blocks compose in one designed system prompt
  assembler rather than accreting.
- **G3 (governance before new resource types)**: 029 (governance &
  lifecycle design note) complete before 037 (integrations), 043 (KB),
  048 (memory), 050 (artifacts). Design note exists:
  `docs/architecture/governance.md` (029 DONE 2026-07-06).
- **G4 (no tuning without evals)**: the retrieval/memory eval harness
  (inside 045) exists before any search or memory-write-policy tuning.
- **G5 (no harness changes without scenarios)**: the agent-behavior
  scenario suite (055) is green before 048 memory-write-policy tuning,
  before 057 changes delegation concurrency, and before default
  prompt-assembly or model changes ship. G4 grades what retrieval
  returns; G5 pins what the harness does. Each Lane H plan adds its
  scenarios as part of its done criteria.
- **G1 extension (stoppable + enveloped before spend)**: 053 (cooperative
  cancellation) and 054 (principal-derived run envelopes) complete before
  041 ships agent-callable integration tools — a run that cannot be
  stopped, or an unattended run whose side-effect grant equals an
  interactive one, must not hold money-spending tools.

## 4. The Roadmap

Dependency spine (unchanged from the donor roadmap, validated against the
codebase by the gaps review):

```
0 baseline ─┬─ Lane R (hardening) ──────────────┐
            ├─ Lane O (ops surfaces) ── G1 ──┐  │
            └─ Phase 1 registry ── Phase 2 skills ── Phase 3 files/jobs
                                                        ├─ Phase 4a integrations (G1, G3)
                                                        ├─ Phase 4b knowledge base (G3, G4)
                                                        ├─ Phase 5 memory (G2, G3)
                                                        └─ Phase 6 artifacts (G3)
```

Phases 4a and 4b run in parallel after Phase 3. Lanes R and O interleave
with Phases 1–3 as capacity allows. Lane C runs after the completed 033
substrate and before the remaining files work it protects, with C05 before
Phase 4+ production polish. UI plans trail their backend slice.

### Phase 0 — Baseline (P0, do first, small)

Not a numbered plan; a checklist chore:

- Mark 009 DONE in the README (delegation landed at `f83d210`; verify the
  approval-resume path for delegated runs while confirming).
- Verify/refresh statuses of 010–020 (verified 2026-07-06: 014–015 remain
  TODO. 010, 011, 012, 013, 016, 017, 018, 019, and 020 are DONE; skills CRUD,
  the skill document pipeline, runtime skill disclosure, the management UI,
  skill activation chat treatment, and cache-stable history trimming now exist).
- Point the README at this document as the ordering authority.

### Lane R — Runtime Hardening (existing plans, interleave early)

| Plan | Title | Priority | When |
|------|-------|----------|------|
| 010 | Provider transport retries | P1 | DONE 2026-07-02 |
| 012 | Stream thinking live over SSE | P1 | DONE 2026-07-03 |
| 011 | Per-run token caps (UsageLimits) | P2 | DONE 2026-07-03 |
| 014 | OTel instrumentation (config-gated) | P2 | Before Phase 4a (Gate G1) |
| 013 | History trimming (ProcessHistory) | P2 | DONE 2026-07-06 |
| 015 | pydantic-ai docs digest refresh | P3 | Filler, any time |

### Lane O — Operational Surfaces (parallel with Phases 1–2, gate G1)

| Plan | Scope | Priority |
|------|-------|----------|
| 021 | Schedule REST routes: CRUD, pause/enable, run-now, run history, awaiting-approval visibility. Backend worker already exists; this is the missing product surface. **DONE 2026-07-03.** | P1 |
| 022 | Schedules management UI: list, editor (prompt/cadence/timezone), run history with statuses, approval-resume visibility. Active-context selection is added later by 040. **DONE 2026-07-03.** | P1 |
| 023 | Audit & security log read API + viewer UI: workspace-scoped audit list with action/resource/status/actor/date filters, event detail drawer, security event list; owner/admin-only. Backend write/query services already exist. **DONE 2026-07-03; viewer lives in Workspace Settings → Audit log.** | P1 |
| 024 | Workspace default & invite UX: persist active workspace to `users.default_workspace_id` on switch, accept pending invites after sign-in, copy-invite-URL/code buttons, personal-vs-team switcher behavior. **DONE 2026-07-07.** | P2 |

### Phase 1 — Tool Registry (the spine; donor Phase A)

| Plan | Scope |
|------|-------|
| 025 | `ToolDefinition` contract + decorator registry + import-time uniqueness/invariant checks; migrate the two catalog tools; write-time validation of `Agent.tool_names`/`tool_policies`; registry read API. **DONE 2026-07-03.** (Donor A1.) |
| 026 | Dispatch choke point: wrapper around tool execution writing an audit row per invocation (`tool_name`/`tool_provider` audit columns), mutation tracker, output-contract validation, capability envelopes for non-interactive runs (schedules **and** delegated sub-agents). **DONE 2026-07-03.** (Donor A2, extended to delegation.) |
| 027 | Frontend tool catalog in the agent form, driven by the registry API — replaces the hardcoded list; includes the remaining agent-form tidy-up from NOTES. **DONE 2026-07-03; the selector is searchable, provider-filtered, and preserves unavailable saved tools.** (Donor A3.) |
| 028 | First registry-native tools: agent planning/TODO tool (own build, donor-informed) + native provider-backed tool exposure (e.g. web search through a per-call selectable helper model) as registry entries with normal policy/audit treatment. **DONE 2026-07-03.** |

### Phase 2 — Skills (existing plans 016–020; gate G2)

Run as written: 016 (DONE 2026-07-03) → 017 (DONE 2026-07-03) → 018 (DONE
2026-07-03) → 019 (DONE 2026-07-03) → 020 (DONE 2026-07-03). Two roadmap-level additions:

- 018 delivered the **system-prompt assembly design** (ordered, budgeted
  blocks with an extension point) that 034/040/049 later plug into — not
  just skill disclosure.
- 017's document pipeline anticipates Phase 3's file processing with shared
  extraction/markdown helpers under `services/skills/documents/`; 033 must
  reuse that machinery rather than build a second converter.

### Cross-cutting design note (gate G3)

| Plan | Scope |
|------|-------|
| 029 | **Governance & lifecycle design note** (a design doc plan, little code): role matrix for files/integrations/credentials/memories/artifacts/schedules and default approval requirements per tool effect; retention & deletion policy per resource (soft vs hard delete, storage cascade, audit survival, export path); quota model (storage, upload, embedding/job budgets, artifact share rate limits) with admin-visible usage counters; secret-manager operating model (mandatory provider in prod, env-var provider for dev, rotation, who may enter keys, references-only API); notification policy for job/discovery/schedule failures. Each downstream plan implements its slice and cites this note. **DONE 2026-07-06.** |

### Phase 3 — Files & Jobs (shared substrate; donor Phase B)

| Plan | Scope |
|------|-------|
| 030 | Generic `jobs` table + SKIP-LOCKED worker harness (workspace-scoped kind × subject × content_hash, priority, bounded retries, stale reclaim, partial-unique in-flight dedup). **DONE 2026-07-06.** (Donor B1.) |
| 031 | `File` / immutable `FileRevision` / non-copying `FileReference` models + migrations, immutability enforcement, exactly-one-actor provenance, file-contract policy table. **DONE 2026-07-06.** (Donor B2.) |
| 032 | Upload/confirm/edit/restore/delete services + routes: two-phase signed upload, content-hash dedup, optimistic concurrency, symmetric deletion + sweepers per 029 retention. **DONE 2026-07-06.** (Donor B3.) |
| 033 | Background file processing (extraction → markdown) via jobs; status lifecycle; reuse 017's conversion machinery. **DONE 2026-07-06.** (Donor B4.) |

### Lane C — Cleanup & Quality Hardening (plans/improvements)

These tasks were added after 033 and are now part of the main execution order.
Pending cleanup plans keep their source plans in `plans/improvements/`;
completed cleanup plans move to `plans/complete/`. `C` identifiers are the
non-colliding roadmap aliases used in `docs/plans/000_README.md`.

| Plan | Scope | Priority | When |
|------|-------|----------|------|
| C01 | Stand up CI and complete the local quality gate: CI workflow, backend format/test coverage in `make check`, pytest asyncio auto mode, and Vitest coverage for the conversation stream parser/reducer. **DONE 2026-07-06.** | P1 | Complete. |
| C02 | Harden the files vertical: upload/confirm race fixes, escaped file search, streaming hash primitive, safer download default, and download audit. **DONE 2026-07-06.** | P1 | Complete. |
| C03 | Bound conversation history reads and paginate the messages API while preserving capability-load pairs for the 013/018 history and skill-disclosure contract. **DONE 2026-07-06.** | P1 | Complete. |
| C04 | Rate limiter hardening: bounded endpoint keys, retention sweep on the 030 jobs harness, and rate-limit regression tests without changing policy. **DONE 2026-07-06.** | P1 | Complete; remaining files work resumes with 034. |
| C05 | Small production-readiness gaps: maintainer-chosen license, settings-gated `/api/metrics`, filtered 403 response bodies, and README corrections. | P2 | Before public-production polish for Phase 4+; license step blocks on maintainer choice. |

Remaining Phase 3 work resumes after the early cleanup hardening that gates it:

| Plan | Scope |
|------|-------|
| 034 | Agent file tools (`list_files`/`read_file`/`write_file`/`promote_scratch`) + scratch model (TTL, size cap, approval-gated promote) + `<available_files>` prompt block via the 018 assembler. **DONE 2026-07-06.** (Donor B5.) |
| 035 | Files UI: files page, detail sheet with revisions/diff, chat file cards with signed-URL open/download. **DONE 2026-07-06.** (Donor B6.) |
| 036 | Multimodal input: chat attachments ride Files; images/documents passed to the model via pydantic-ai multimodal input, gated by the file-contract policy. **DONE 2026-07-07.** (From NOTES; new — not in donor roadmap.) |

### Phase 4a — Integrations (donor Phase C; gates G1, G3; parallel with 4b)

Structural pre-decision: D10 / plan 061 (`docs/architecture/
integration-packaging.md`, DONE 2026-07-07) binds how provider code is
packaged — 037 lands the plugin contract + loader and the fake provider as
the first package, 041's providers land as `apps/api/integrations/<key>/`
packages, 042 lands the `src/integrations/` lazy-module seam. The
037/039/041/042 amendment blocks carry the deltas; the note wins on
structure.

| Plan | Scope |
|------|-------|
| 037 | Core models (credentials/connections/resources/discovery_runs — **full multi-connection per D3**: no per-provider uniqueness, required connection labels, principal fingerprints for cross-connection dedup) + declarative provider manifest + credential service (encryption, locked proactive refresh, needs_reauth) + secret references per 029. (Donor C1.) |
| 038 | OAuth flows (initiate/callback with signed single-value state), non-OAuth connect, test/revoke/refresh routes. (Donor C2.) |
| 039 | Async resource discovery via jobs, resource selection, connection status machine. (Donor C3.) |
| 040 | Active context: per-user-per-workspace selection, context groups, server-side resolution **across multiple connections per provider (D3)** + compatibility filtering + fan-out executor, `RuntimeDeps` injection + prompt block via the 018 assembler; schedule saved-context wiring (fills `AgentSchedule.active_context`, extends 022's UI). (Donor C4.) |
| 041 | First providers per D4: Gmail, Google Ads (MCC→account discovery; write/spend operations default to `approval`), Airtable — operation services + registry tools through the 026 choke point. **Gate G1 applies.** (Donor C5.) |
| 042 | Integrations UI: provider cards, connect flows (**multiple labeled connections per provider, D3**), connection pickers, resource selection, context picker in chat header. (Donor C6.) |

### Phase 4b — Knowledge Base (donor Phase D; gates G3, G4; parallel with 4a)

| Plan | Scope |
|------|-------|
| 043 | Embeddings provider service (ABC + OpenAI default + local option; model+dims recorded per collection). (Donor D1.) |
| 044 | OKF-compatible, Praxis-owned `kb_documents`/`kb_chunks` models + migrations (stable concept identifiers/frontmatter metadata, halfvec HNSW + tsvector from day one); ingestion pipeline via jobs (structure-aware chunking, optional contextual annotation). Google Knowledge Catalog remains an optional integration target, not a dependency. (Donor D2 + D9.) |
| 045 | Hybrid search engine (RRF merge, pending-embedding lexical fallback, SQL filters, reranker interface) + search/read routes + **the eval harness**: seed docs with expected citations, hybrid-search assertions, fallback tests, prompt-injection fixture documents. (Donor D3 + gaps-doc eval requirement; Gate G4.) |
| 046 | Agent tools (`search_knowledge`, `read_document`) with retrieved content framed as untrusted data in tool results; write-policy choke point (provenance, private-never-shared rule, secret blocking); document sources (upload via Files, URL, manual). **Gate G2 applies.** (Donor D4.) |
| 047 | KB UI: documents table, ingestion status, search. (Donor D5.) |

### Phase 5 — Agent Memory (donor Phase E; gates G2, G3)

| Plan | Scope |
|------|-------|
| 048 | `agent_memories` model + write service (backend-minted provenance, dedup-reinforce, read-time decay, supersession) + memory tools through the registry (audit/approval for free) + memory eval tests (dedup/reinforcement, approval/audit) per Gate G4. (Donor E1.) |
| 049 | Core-memory prompt injection (budgeted formatter via the 018 assembler) + memory UI (view/edit/delete per scope). (Donor E2.) |

### Phase 6 — Artifacts (donor Phase F; gate G3)

| Plan | Scope |
|------|-------|
| 050 | `artifacts` model over FileRevisions + `create_artifact`/`update_artifact` registry tools + serving route with the three-layer defense (opaque-origin sandbox, `ARTIFACT_ORIGIN`, strict CSP with `connect-src 'none'`). Local dev: srcdoc + sandbox; separate origin required only when share links ship. (Donor F1.) |
| 051 | Chat artifact cards (sandboxed preview, version selector, diff/restore) + share links (≥128-bit tokens, version-pinned, expiry/revocation, audited, rate-limited per 029). (Donor F2.) |

### Lane H — Harness Hardening & Evals (added 2026-07-07; plans 053–060)

A directed review of the agent harness against current
harness-engineering practice (grounded at `c2f08cc`; pydantic-ai 2.1.0
facts probed against the installed package, recorded in each plan). Two
items are Gate G1-adjacent and interleave before Phase 4a; the rest
bracket Phases 4–6.

| Plan | Scope | Priority | When |
|------|-------|----------|------|
| 053 | Cooperative run cancellation: cancel route + audit, `RunTaskRegistry.cancel`, heartbeat cancel-detection (works cross-process via the lease seam), `CancelledError` terminal handling, UI stop control. Today `cancel_agent_run` has no route and no callers; nothing stops the executing task. | P1 | Before 041 (G1 extension) |
| 054 | Run envelope enforcement: `effect_scope` (internal/external) on the tool contract, principal-derived `side_effect_policy` (scheduled → `require_approval` for external writes by default), the missing `require_approval` dispatch branch, delegated inheritance recorded at mint time. Today every run gets the constant grant `("allow", depth 1)`. | P1 | Before 041 (G1 extension) |
| 055 | Agent behavior eval harness (delivers Gate G5): deterministic scenario suite (`tests/scenarios/`, FunctionModel-scripted `execute_run` end-to-end — dispatch/audit, approvals, envelopes, delegation, prompt assembly, trimming, multimodal) + graded evals layer on the already-installed `pydantic-evals` (`evals/`, opt-in `make evals`, never CI). Content, not platform. | P1 | Parallel with Phase 4; before 048 |
| 056 | Context compaction: out-of-band watermark-keyed summaries (jobs harness; cache-stable by construction — summarize only below the 013 trim watermark), token-pressure trimming against catalog `context_window`, non-null default for the per-run token cap. | P1 | Before 048/049 |
| 057 | Parallel delegation fan-out: depth stays 1; bound (per-run semaphore), prove (usage accounting, multi-child approval collapse, cancellation propagation — all as scenarios), and prompt the concurrency pydantic-ai already executes for parallel tool calls. | P2 | After 054/055 |
| 058 | Model failover chain: catalog-defined `FallbackModel` chains, double opt-in (settings + agent), same-capability-class validation, actually-used model recorded. Supersedes the 2026-07-01 rejection — product decision taken 2026-07-07. | P3 | Filler (with 015) |
| 059 | Sandboxed code execution: `run_code` registry tool via the 028 helper-model pattern + `NativeTool(CodeExecutionTool())` (Anthropic/OpenAI/Google), 036-gated file inlining, outputs bounded + scratch-captured behind `promote_scratch`. e2b/Vercel/Cloudflare deferred as future integration providers behind the same seam. | P2 | After Phase 6 |
| 060 | Durable run event log + live stream replay: append-only `agent_run_events`, TeeSink batched writes, replay-then-live bridge with LISTEN/NOTIFY cross-instance wake-up, short retention sweep. Supersedes the streaming plan's live-replay non-goal. | P3 | Last |

Not in Lane H but recorded 2026-07-07 as named follow-ups: email/Slack
delivery of scheduled-run results (extends the §6 notification policy in
`governance.md` — likely the highest-ROI unplanned product feature),
KB ingestion from integration sources (Drive/Gmail → `kb.sync_source`
jobs; the Phase 4a×4b intersection), and workspace-level LLM token
budgets (governance §4 counters exist on `agent_runs` hot columns; only
the quota surface is missing).

### Rolling polish lane (P3, unnumbered)

Batched into small tickets whenever convenient; never blocks a phase:
avatar/icon upload feedback, file-upload component improvements,
SummaryTile/MetricCard consolidation, title-case sweep, settings tab
border. (From NOTES; agent-form cleanup is absorbed by 027.)

## 5. NOTES.md Disposition

Every raw-notes item, so nothing is silently dropped: login hardening
(closed — D8 / already covered), OAuth state (already signed), avatar
feedback (polish lane), generic components (polish lane), schedules UI &
worker (021/022), workspace header validation (already server-side),
invites (024), title case / tab border / icon feedback (polish lane),
agent form (027), dynamic tool registry (025–027), native tools (028),
multimodal (036), context in prompt (018/034/040/049 via one assembler),
artifacts & scratchpad (050/051 + 034), TODO tool (028), audit/security UI
(023), integrations incl. secret manager / multi-connection / context
groups (037–042), KB/memory storage/ingestion/injection/tools/user
management (043–049).

## 6. Suggested Execution Order (single stream)

If work proceeds roughly serially, the default order is:

`0 → 012 (DONE) → 011 (DONE) → 021 (DONE) → 022 (DONE) → 023 (DONE) → 025 (DONE) → 026 (DONE) → 027 (DONE) → 016 (DONE) → 017 (DONE) →
018 (DONE) → 028 (DONE) → 019 (DONE) → 020 (DONE) → 013 (DONE) → 029 (DONE) → 030 (DONE) → 031 (DONE) → 032 (DONE) → 033 (DONE) → C01 (DONE) → C02 (DONE) →
C03 (DONE) → C04 (DONE) → 034 (DONE) → 035 (DONE) → 036 (DONE) → 024 (DONE) → 061 (DONE) → 014 → 053 → 054 → C05 → {037–042 ∥ 043–047 ∥ 055} → 056 → 048 →
049 → 057 → 050 → 051 → 059 → 060` — with 015, 052, 058, and the polish
lane as filler.

Lane H placement rationale: 053/054 sit between 014 and Phase 4a because
the G1 extension binds them before 041; 055 runs parallel with Phase 4
(it observes, it does not change the runtime) and must be green before
048; 056 lands after Phase 4 starts but before 048/049 claim their prompt
blocks; 057 needs 054's inheritance and 055's scenarios and pays off once
delegates hold 041/046 tools; 059 follows Phase 6; 060 is last by
operator decision.

With parallel capacity: one stream takes Lane O while another runs Phase 1
→ 2; Phases 4a/4b split naturally across streams after Phase 3; 055 is a
natural third stream during Phase 4.
