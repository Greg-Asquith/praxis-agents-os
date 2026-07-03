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
README table as it is written. Numbers 010–029 are written plan docs
(021–029 added 2026-07-02: Lane O, Phase 1, Gate G3 note); 030–051 are
reserved here and written on demand as their phases approach.

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
| D2 | Runtime hardening plans 010–015 | **Split by leverage.** 010/012/011 land now; 014 (OTel) gates Phase C; 013 lands after 018 (they interact — see README dependency notes); 015 is filler. | Lane R |
| D3 | Multi-connection per provider | **Full multi-connection in v1.** Multiple simultaneous connections per provider per owner from the first integrations release: no one-active-per-provider uniqueness constraint, a required user-set label per connection, active-context resolution across N connections, and connection pickers in the v1 UI. Resolves the NOTES-vs-donor conflict in favor of the agency use case; adds scope to 037/040/042. | 037/040/042 |
| D4 | First integration providers | **Gmail (user OAuth) + Google Ads (workspace OAuth + MCC→account discovery) + Airtable (api-key + secret reference).** Google Ads over GA4: richer resource hierarchy and closer to the agency product. Its write operations spend real money — they default to `approval` in tool policy and are the first hard test of Gate G1. | 041 |
| D5 | Schema branch | All roadmap tables go in **`core`** (platform infrastructure); `app` stays reserved for verticals. (From donor roadmap §2, confirmed.) | all migrations |
| D6 | Skills before memory/KB injection | Confirmed: 018 must land before 046/048 so system-prompt assembly is designed once. | Gate G2 |
| D7 | MCP client support | Deferred until the native registry is stable and the catalog is big enough to need `defer_loading`. Not in any phase below. | — |
| D8 | Client-side password hashing | Rejected (no threat model it addresses; passwords already hashed at rest, TLS in transit). Closes the NOTES item. | — |

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
  048 (memory), 050 (artifacts).
- **G4 (no tuning without evals)**: the retrieval/memory eval harness
  (inside 045) exists before any search or memory-write-policy tuning.

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
with Phases 1–3 as capacity allows. UI plans trail their backend slice.

### Phase 0 — Baseline (P0, do first, small)

Not a numbered plan; a checklist chore:

- Mark 009 DONE in the README (delegation landed at `f83d210`; verify the
  approval-resume path for delegated runs while confirming).
- Verify/refresh statuses of 010–020 (verified 2026-07-03: 010, 011, and 012
  are DONE; 013–020 remain TODO; only the `skills` table and
  delegation pre-exist).
- Point the README at this document as the ordering authority.

### Lane R — Runtime Hardening (existing plans, interleave early)

| Plan | Title | Priority | When |
|------|-------|----------|------|
| 010 | Provider transport retries | P1 | DONE 2026-07-02 |
| 012 | Stream thinking live over SSE | P1 | DONE 2026-07-03 |
| 011 | Per-run token caps (UsageLimits) | P2 | DONE 2026-07-03 |
| 014 | OTel instrumentation (config-gated) | P2 | Before Phase 4a (Gate G1) |
| 013 | History trimming (ProcessHistory) | P2 | **After 018** — must preserve capability-load pairs |
| 015 | pydantic-ai docs digest refresh | P3 | Filler, any time |

### Lane O — Operational Surfaces (parallel with Phases 1–2, gate G1)

| Plan | Scope | Priority |
|------|-------|----------|
| 021 | Schedule REST routes: CRUD, pause/enable, run-now, run history, awaiting-approval visibility. Backend worker already exists; this is the missing product surface. **DONE 2026-07-03.** | P1 |
| 022 | Schedules management UI: list, editor (prompt/cadence/timezone), run history with statuses, approval-resume visibility. Active-context selection is added later by 040. **DONE 2026-07-03.** | P1 |
| 023 | Audit & security log read API + viewer UI: workspace-scoped audit list with action/resource/status/actor/date filters, event detail drawer, security event list; owner/admin-only. Backend write/query services already exist. **DONE 2026-07-03; viewer lives in Workspace Settings → Audit log.** | P1 |
| 024 | Workspace default & invite UX: persist active workspace to `users.default_workspace_id` on switch, accept pending invites after sign-in, copy-invite-URL/code buttons, personal-vs-team switcher behavior. | P2 |

### Phase 1 — Tool Registry (the spine; donor Phase A)

| Plan | Scope |
|------|-------|
| 025 | `ToolDefinition` contract + decorator registry + import-time uniqueness/invariant checks; migrate the two catalog tools; write-time validation of `Agent.tool_names`/`tool_policies`; registry read API. **DONE 2026-07-03.** (Donor A1.) |
| 026 | Dispatch choke point: wrapper around tool execution writing an audit row per invocation (`tool_name`/`tool_provider` audit columns), mutation tracker, output-contract validation, capability envelopes for non-interactive runs (schedules **and** delegated sub-agents). (Donor A2, extended to delegation.) |
| 027 | Frontend tool catalog in the agent form, driven by the registry API — replaces the hardcoded list; includes the remaining agent-form tidy-up from NOTES. (Donor A3.) |
| 028 | First registry-native tools: agent planning/TODO tool (own build, donor-informed) + pydantic-ai native/builtin tool exposure (e.g. web search) as registry entries with normal policy/audit treatment. Small; proves the registry with real entries beyond demos. |

### Phase 2 — Skills (existing plans 016–020; gate G2)

Run as written: 016 → 017 → 018 → 019 → 020. Two roadmap-level additions:

- 018 must deliver the **system-prompt assembly design** (ordered, budgeted
  blocks with an extension point) that 034/040/049 later plug into — not
  just skill disclosure.
- 017's document pipeline should anticipate Phase 3's file processing
  (shared extraction/markdown machinery); do not build a second converter
  in 033.

### Cross-cutting design note (gate G3)

| Plan | Scope |
|------|-------|
| 029 | **Governance & lifecycle design note** (a design doc plan, little code): role matrix for files/integrations/credentials/memories/artifacts/schedules and default approval requirements per tool effect; retention & deletion policy per resource (soft vs hard delete, storage cascade, audit survival, export path); quota model (storage, upload, embedding/job budgets, artifact share rate limits) with admin-visible usage counters; secret-manager operating model (mandatory provider in prod, env-var provider for dev, rotation, who may enter keys, references-only API); notification policy for job/discovery/schedule failures. Each downstream plan implements its slice and cites this note. |

### Phase 3 — Files & Jobs (shared substrate; donor Phase B)

| Plan | Scope |
|------|-------|
| 030 | Generic `jobs` table + SKIP-LOCKED worker harness (kind × subject × content_hash, priority, bounded retries, stale reclaim, partial-unique in-flight dedup). (Donor B1.) |
| 031 | `File` / immutable `FileRevision` / non-copying `FileReference` models + migrations, immutability enforcement, exactly-one-actor provenance, file-contract policy table. (Donor B2.) |
| 032 | Upload/confirm/edit/restore/delete services + routes: two-phase signed upload, content-hash dedup, optimistic concurrency, symmetric deletion + sweepers per 029 retention. (Donor B3.) |
| 033 | Background file processing (extraction → markdown) via jobs; status lifecycle; reuse 017's conversion machinery. (Donor B4.) |
| 034 | Agent file tools (`list_files`/`read_file`/`write_file`/`promote_scratch`) + scratch model (TTL, size cap, approval-gated promote) + `<available_files>` prompt block via the 018 assembler. (Donor B5.) |
| 035 | Files UI: files page, detail sheet with revisions/diff, chat file cards with signed-URL open/download. (Donor B6.) |
| 036 | Multimodal input: chat attachments ride Files; images/documents passed to the model via pydantic-ai multimodal input, gated by the file-contract policy. (From NOTES; new — not in donor roadmap.) |

### Phase 4a — Integrations (donor Phase C; gates G1, G3; parallel with 4b)

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
| 044 | `kb_documents`/`kb_chunks` models + migrations (halfvec HNSW + tsvector from day one); ingestion pipeline via jobs (structure-aware chunking, optional contextual annotation). (Donor D2.) |
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

`0 → 012 (DONE) → 011 (DONE) → 021 (DONE) → 022 (DONE) → 023 (DONE) → 025 (DONE) → 026 → 027 → 016 → 017 →
018 → 028 → 019 → 020 → 013 → 029 → 030 → 031 → 032 → 033 → 034 → 035 →
036 → 024 → 014 → {037–042 ∥ 043–047} → 048 → 049 → 050 → 051` — with 015
and the polish lane as filler.

With parallel capacity: one stream takes Lane O while another runs Phase 1
→ 2; Phases 4a/4b split naturally across streams after Phase 3.
