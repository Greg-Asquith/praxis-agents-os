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
2026-07-06 and moved to `plans/complete/`; C05 was completed 2026-07-09 and
moved to `plans/complete/`. Plan 035 was completed 2026-07-06 and moved to
`plans/complete/`; Plan 036 and Plan 024 were completed 2026-07-07 and moved
to `plans/complete/`. Every reserved number now has a written plan. Plans 052
(Lane O homepage redesign) and 053–060 (Lane H,
harness hardening — added 2026-07-07 by a directed harness-engineering
review, grounded at `c2f08cc` with installed-package probes) extend the
roadmap past the reserved range; Lane H is defined in §4 below and adds
Gate G5. Plan 061 (integration provider packaging, decision D10) was
written and executed 2026-07-07 as a design-note plan in the 029 mold —
it produced `docs/architecture/integration-packaging.md` and amended
037/039/041/042 before any Phase 4a code exists.
Plan 014 was completed 2026-07-07: agent-run tracing is config-gated,
content capture is off by default and production-guarded, and API/worker
startup share one idempotent Logfire/OTel setup path.
Plans 062–066 (Lane Q, quality consolidation — added 2026-07-07 by a
code-quality/maintainability audit grounded at `d326b68`) run between 014
and Lane H: they make the local gate honest, add the behavioral test net,
consolidate the copy-pasted per-feature scaffolding on both sides, and
decompose `execute_run` before 053/054/056 edit it. Lane Q is defined in
§4 below. Plan 062 was completed 2026-07-07 and moved to
`docs/plans/complete/`. Plan 063 was completed 2026-07-07 and moved to
`docs/plans/complete/`. Plan 064 was completed 2026-07-07 and moved to
`docs/plans/complete/`. Plan 065 was completed 2026-07-07 and moved to
`docs/plans/complete/`. Plan 066 was completed 2026-07-07 and moved to
`docs/plans/complete/`.
Plans 067–078 were added 2026-07-07 by a best-practice review of the plan
set against current industry practice (agent harnesses, OAuth/RAG
engineering, open-source delivery), grounded at `c770a1c` with every
finding re-verified against the target plan's own text. Lane B (067–074,
pre-execution amendment plans in the 061 mold) and Lane P (078, public
launch & adoption) are defined in §4 below; 075 is a cross-cutting
threat-model design note that registers Gate G6; 076 extends Lane H; 077
is a Phase 4a structural design note in the 061 mold. Plan 073 was
completed 2026-07-09 and moved to `docs/plans/complete/`; it amends 053
with shielded cancellation finalization, tier-deduped heartbeat cancel
delivery, interrupted-tool audit disposition, and first-turn prompt
persistence requirements. Plan 054 was completed 2026-07-09 and moved to
`docs/plans/complete/`; scheduled runs now stamp explicit side-effect
grants, delegated runs inherit them, and dispatch suspends unapproved
external writes under `require_approval` while preserving explicit scheduled
write allowance.
Plan 076 was completed 2026-07-10 and moved to `docs/plans/complete/`;
free-text tool results are now bounded deterministically at dispatch,
structured results remain intact and observable, and plan 056 consumes the
shared model-calibrated token estimator.
Plan 067 was completed 2026-07-10 and moved to `docs/plans/complete/`;
its amendment makes PKCE S256 mandatory for integration authorization-code
flows, adds atomically consumed server-side pending state, and requires
HTTPS redirect URIs outside local development before plan 038 executes.
Plan 068 was completed 2026-07-10 and moved to `docs/plans/complete/`;
its amendments move integration credential encryption behind a
secrets-provider root with purpose-separated keys and a real re-encryption
sweep, mask the Google Ads developer token, and version artifact view-URL
signatures before plans 037/041/050 execute.
Plan 077 was completed 2026-07-10 and moved to `docs/plans/complete/`;
`docs/architecture/integration-events.md` now binds inbound provider receipt,
verification, deduplication, jobs processing, and the unattended-run envelope
law before plans 037/041 execute. Plan 079 is reserved as the first
implementation slice (receipt spine + Airtable webhooks); its plan document
is written by the Phase 4a executor once 041 lands.
Plan 080 was written and executed 2026-07-10 as the Phase 4a/4b handoff
readiness sweep (docs-only, the 074 mold): it refreshed the stale
post-053/054/066 runtime anchors in 040/046, registered threat-model
channels for integration-fetched content (041) and the KB annotation
helper (044) under Gate G6, made 044 ingest upload-source documents for
real now that 033 is landed, reconciled cross-plan route/contract
mismatches across 037–042 and 044–047, recorded the optional
`oauth_operations` plugin seam and the KB-write approval default, and
consolidated the Lane H follow-up notes into `FOLLOW_UPS.md`. A same-day
maintainer decision (D11) then removed the fake integration provider
outright: 037–039 ship no fake package or gating, the `oauth_operations`
seam recorded by 080 is dropped with its only consumer, and contract/
loader testing moves to a suite-local test provider with transport-mocked
provider HTTP. Phases 4a and 4b are hand-off ready.

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
| D2 | Runtime hardening plans 010–015 | **Split by leverage.** 010/012/011 landed first; 013 landed after 018 to preserve capability-load pairs; 014 (OTel) completed 2026-07-07 and gates Phase C; 015 completed 2026-07-09 as the Pydantic AI docs digest refresh. | Lane R |
| D3 | Multi-connection per provider | **Full multi-connection in v1.** Multiple simultaneous connections per provider per owner from the first integrations release: no one-active-per-provider uniqueness constraint, a required user-set label per connection, active-context resolution across N connections, and connection pickers in the v1 UI. Resolves the NOTES-vs-donor conflict in favor of the agency use case; adds scope to 037/040/042. | 037/040/042 |
| D4 | First integration providers | **Gmail (user OAuth) + Google Ads (workspace OAuth + MCC→account discovery) + Airtable (api-key + secret reference).** Google Ads over GA4: richer resource hierarchy and closer to the agency product. Its write operations spend real money — they default to `approval` in tool policy and are the first hard test of Gate G1. | 041 |
| D5 | Schema branch | All roadmap tables go in **`core`** (platform infrastructure); `app` stays reserved for verticals. (From donor roadmap §2, confirmed.) | all migrations |
| D6 | Skills before memory/KB injection | Confirmed: 018 must land before 046/048 so system-prompt assembly is designed once. | Gate G2 |
| D7 | MCP client support | Deferred until the native registry is stable and the catalog is big enough to need `defer_loading`. Not in any phase below. | — |
| D8 | Client-side password hashing | Rejected (no threat model it addresses; passwords already hashed at rest, TLS in transit). Closes the NOTES item. | — |
| D9 | OKF and Google Knowledge Catalog posture | **Own the KB; use OKF for compatibility.** Praxis owns storage, indexing, permissions, jobs, audit, retention, and agent behavior. Open Knowledge Format informs markdown/frontmatter structure, stable concept identifiers, and import/export. Google Knowledge Catalog may become an optional integration/source/sink later, not the runtime substrate. | 044–047 |
| D11 | Fake integration provider | **Removed (2026-07-10).** The shipped provider set is exactly D4 (Gmail, Google Ads, Airtable): no fake provider package, manifest entry, or local-only settings gate ships. The plugin contract and loader are exercised by a suite-local test provider registered through the loader seam in test code only, with provider HTTP mocked at the transport layer; manual QA connects real dev credentials (Airtable's API key is the cheapest). The optional `oauth_operations` plugin seam (plan 080 decision 1) is dropped with its only consumer — the engine's generic manifest-driven OAuth flow is the only token path; revisit only if a real provider cannot use it. Supersedes 037's decision 7 and the fake slices of the 061/077/080 notes; 039 ships its discovery engine with no working shipped arm until 041. | 037–039, 079 |
| D12 | Google integration OAuth isolation | **One Google Cloud project and OAuth client per service.** Gmail, Google Ads, and every future Google integration own separate client IDs/secrets and revocation boundaries; login OAuth is separate too. Multiple clients inside one project are insufficient because Google revocation invalidates the user's project-wide grants. Provider variables live beside service code in `apps/api/integrations/<key>/settings.py`, not on the global settings model; shared orchestration settings alone remain in `core/settings/integrations.py`. Reused non-empty client IDs fail at provider load. | 038/041 and every later Google provider |
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
  cancellation, DONE 2026-07-09) and 054 (principal-derived run envelopes,
  DONE 2026-07-09)
  complete before 041 ships agent-callable integration tools — a run that cannot be
  stopped, or an unattended run whose side-effect grant equals an
  interactive one, must not hold money-spending tools.
- **G6 (untrusted content is framed and fixture-tested)**: no plan that
  feeds model context from a new untrusted-content source (retrieval,
  memory, summaries, integration-fetched content, file/tool text) ships
  unless `docs/architecture/threat-model.md` lists the channel and
  adversarial fixtures exercise it. Deterministic tests pin sanitization
  mechanics; behavioral resistance rides 055's graded eval layer. Binds
  041/044/046/048/049/056/059 and every later content source (044 added
  2026-07-10 by plan 080 for the ingestion annotation channel).

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
- Verify/refresh statuses of 010–020 (verified 2026-07-09: 010, 011, 012,
  013, 014, 015, 016, 017, 018, 019, and 020 are DONE; skills CRUD,
  the skill document pipeline, runtime skill disclosure, the management UI,
  skill activation chat treatment, and cache-stable history trimming now exist).
- Point the README at this document as the ordering authority.

### Lane R — Runtime Hardening (existing plans, interleave early)

| Plan | Title | Priority | When |
|------|-------|----------|------|
| 010 | Provider transport retries | P1 | DONE 2026-07-02 |
| 012 | Stream thinking live over SSE | P1 | DONE 2026-07-03 |
| 011 | Per-run token caps (UsageLimits) | P2 | DONE 2026-07-03 |
| 014 | OTel instrumentation (config-gated). **DONE 2026-07-07.** | P2 | Complete. |
| 013 | History trimming (ProcessHistory) | P2 | DONE 2026-07-06 |
| 015 | pydantic-ai docs digest refresh | P3 | DONE 2026-07-09 |

### Lane O — Operational Surfaces (parallel with Phases 1–2, gate G1)

| Plan | Scope | Priority |
|------|-------|----------|
| 021 | Schedule REST routes: CRUD, pause/enable, run-now, run history, awaiting-approval visibility. Backend worker already exists; this is the missing product surface. **DONE 2026-07-03.** | P1 |
| 022 | Schedules management UI: list, editor (prompt/cadence/timezone), run history with statuses, approval-resume visibility. Active-context selection is added later by 040. **DONE 2026-07-03.** | P1 |
| 023 | Audit & security log read API + viewer UI: workspace-scoped audit list with action/resource/status/actor/date filters, event detail drawer, security event list; owner/admin-only. Backend write/query services already exist. **DONE 2026-07-03; viewer lives in Workspace Settings → Audit log.** | P1 |
| 024 | Workspace default & invite UX: persist active workspace to `users.default_workspace_id` on switch, accept pending invites after sign-in, copy-invite-URL/code buttons, personal-vs-team switcher behavior. **DONE 2026-07-07.** | P2 |

### Frontend visual refinement track (auxiliary, added 2026-07-16)

The visual-only track in `docs/plans/frontend-ui/` follows the product roadmap
without changing its feature ordering. UI-001 landed the Praxis brand token
foundation on 2026-07-16: charcoal/cream surfaces, amber actions, teal links,
semantic success/warning colors, dark-mode parity, and shared button/badge
polish. The original blue-primary proposal was rejected during maintainer
visual review in favor of the established palette published at
`praxis-agents.ai`. UI-002 landed the responsive inset app canvas and sidebar
finish on 2026-07-16 without changing navigation or workspace-switcher
placement. UI-003 landed deterministic, client-derived agent identity icons on
2026-07-16 across agent pickers, desktop/mobile lists, and the configure header;
the API contract remains unchanged. UI-004 landed the refined conversation
transcript on 2026-07-16: agent-identified assistant turns, compact user bubbles,
calmer markdown/thinking states, and reader-respecting live auto-scroll. UI-005
landed the inline tool-row and approval polish on 2026-07-16: shared threaded
details, semantic status colors, calm approval cards, and consistent
Approve/Decline copy without changing deferred-decision payloads or batching.
UI-006 landed the floating conversation composer on 2026-07-16: compact
attachment and agent controls, persistent turn context, resolved model labels,
and a single send/stop action slot without changing message, upload, or
cancellation behavior. UI-007 landed the non-chat page and state polish on
2026-07-16: shared title/description headers, consistent cards and semantic
statuses, filled action-oriented empty states, direct auth copy, and compact
tables. Maintainer review removed eyebrow labels and redundant metric-card
bands across list and detail pages. UI-008 replaced Geist with the self-hosted
Inter variable family on 2026-07-16 while preserving the shared sans/heading
token seam; the production build emits Inter assets only. UI-009 and UI-010
remain sequenced in that track; completed plans live under
`docs/plans/complete/` with the `frontend-ui-` filename prefix.

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
| C05 | Small production-readiness gaps: Apache-2.0 license, settings-gated `/api/metrics`, filtered 403 response bodies, and README corrections. **DONE 2026-07-09.** | P2 | Complete. |

Remaining Phase 3 work resumes after the early cleanup hardening that gates it:

| Plan | Scope |
|------|-------|
| 034 | Agent file tools (`list_files`/`read_file`/`write_file`/`promote_scratch`) + scratch model (TTL, size cap, approval-gated promote) + `<available_files>` prompt block via the 018 assembler. **DONE 2026-07-06.** (Donor B5.) |
| 035 | Files UI: files page, detail sheet with revisions/diff, chat file cards with signed-URL open/download. **DONE 2026-07-06.** (Donor B6.) |
| 036 | Multimodal input: chat attachments ride Files; images/documents passed to the model via pydantic-ai multimodal input, gated by the file-contract policy. **DONE 2026-07-07.** (From NOTES; new — not in donor roadmap.) |

### Phase 4a — Integrations (donor Phase C; gates G1, G3; parallel with 4b)

Structural pre-decision: D10 / plan 061 (`docs/architecture/
integration-packaging.md`, DONE 2026-07-07) binds how provider code is
packaged — 037 lands the plugin contract + loader (exercised by a
suite-local test provider per D11; no fake provider ships), 041's providers
land as the first real `apps/api/integrations/<key>/`
packages, 042 lands the `src/integrations/` lazy-module seam. The
037/039/041/042 amendment blocks carry the deltas; the note wins on
structure.

| Plan | Scope |
|------|-------|
| 037 | Core models (credentials/connections/resources/discovery_runs — **full multi-connection per D3**: no per-provider uniqueness, required connection labels, principal fingerprints for cross-connection dedup) + declarative provider manifest + credential service (encryption, locked proactive refresh, needs_reauth) + secret references per 029. **DONE 2026-07-10**; one provider allowlist, cloud secrets on GCP/Azure/AWS. (Donor C1.) |
| 038 | OAuth flows (initiate/callback with PKCE S256 + signed single-value and server-side single-use state), provider-isolated OAuth settings, non-OAuth connect, test/revoke/refresh routes. **DONE 2026-07-10.** (Donor C2.) |
| 039 | Async resource discovery via jobs, resource selection, connection status machine. (Donor C3.) |
| 040 | Active context: per-user-per-workspace selection, context groups, server-side resolution **across multiple connections per provider (D3)** + compatibility filtering + fan-out executor, `RuntimeDeps` injection + prompt block via the 018 assembler; schedule saved-context wiring (fills `AgentSchedule.active_context`, extends 022's UI). (Donor C4.) |
| 041 | First providers per D4: Gmail, Google Ads (MCC→account discovery; write/spend operations default to `approval`), Airtable — operation services + registry tools through the 026 choke point. **Gate G1 applies.** (Donor C5.) |
| 042 | Integrations UI: provider cards, connect flows (**multiple labeled connections per provider, D3**), connection pickers, resource selection, context picker in chat header. (Donor C6.) |
| 079 | Inbound event receipt spine + Airtable webhooks: verification-first shared route, bounded event log and dedup, `integrations.process_event`, unattended `event` run envelope, retention, and the first provider push path. (Plan 077 implementation reservation; the plan document is written by the Phase 4a executor once 041 lands.) |

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
| 053 | Cooperative run cancellation: cancel route + audit, `RunTaskRegistry.cancel`, heartbeat cancel-detection (works cross-process via the lease seam), `CancelledError` terminal handling, UI stop control. DONE 2026-07-09; amended by 073. | P1 | Complete |
| 054 | Run envelope enforcement: `effect_scope` (internal/external) on the tool contract, scheduled run grants stamped at mint time (`require_approval` by default, explicit `allow` for schedules expected to write), the missing `require_approval` dispatch branch, delegated inheritance recorded at mint time. **DONE 2026-07-09.** | P1 | Complete |
| 055 | Agent behavior eval harness (delivers Gate G5): deterministic scenario suite (`tests/scenarios/`, FunctionModel-scripted `execute_run` end-to-end — dispatch/audit, approvals, envelopes, delegation, prompt assembly, trimming, multimodal) + graded evals layer on the already-installed `pydantic-evals` (`evals/`, opt-in `make evals`, never CI). Content, not platform. | P1 | Parallel with Phase 4; before 048 |
| 056 | Context compaction: out-of-band watermark-keyed summaries (jobs harness; cache-stable by construction — summarize only below the 013 trim watermark), token-pressure trimming against catalog `context_window`, non-null default for the per-run token cap. | P1 | Before 048/049 |
| 057 | Parallel delegation fan-out: depth stays 1; bound (per-run semaphore), prove (usage accounting, multi-child approval collapse, cancellation propagation — all as scenarios), and prompt the concurrency pydantic-ai already executes for parallel tool calls. | P2 | After 054/055 |
| 058 | Model failover chain: catalog-defined `FallbackModel` chains, double opt-in (settings + agent), same-capability-class validation, actually-used model recorded. Supersedes the 2026-07-01 rejection — product decision taken 2026-07-07. | P3 | Filler |
| 059 | Sandboxed code execution: `run_code` registry tool via the 028 helper-model pattern + `NativeTool(CodeExecutionTool())` (Anthropic/OpenAI/Google), 036-gated file inlining, outputs bounded + scratch-captured behind `promote_scratch`. e2b/Vercel/Cloudflare deferred as future integration providers behind the same seam. | P2 | After Phase 6 |
| 060 | Durable run event log + live stream replay: append-only `agent_run_events`, TeeSink batched writes, replay-then-live bridge with LISTEN/NOTIFY cross-instance wake-up, short retention sweep. Supersedes the streaming plan's live-replay non-goal. | P3 | Last |

Not in Lane H but recorded 2026-07-07 as named follow-ups: email/Slack
delivery of scheduled-run results (extends the §6 notification policy in
`governance.md` — likely the highest-ROI unplanned product feature),
KB ingestion from integration sources (Drive/Gmail → `kb.sync_source`
jobs; the Phase 4a×4b intersection), and workspace-level LLM token
budgets (governance §4 counters exist on `agent_runs` hot columns; only
the quota surface is missing). All three are tracked as items 3–5 in
`docs/plans/FOLLOW_UPS.md` (consolidated by plan 080).

### Lane Q — Quality Consolidation (added 2026-07-07; plans 062–066)

A code-quality/maintainability audit at `d326b68` (four parallel audits:
backend debt, web debt, test coverage, DX; every planned finding re-verified
against the code). The unifying finding: both apps are built as N parallel
vertical features whose shared plumbing was copy-pasted per feature and is
drifting — and the local gate gives false greens (`make check` runs pytest
without `TEST_DATABASE_URL`, silently skipping ~57 of 84 test modules).
Lane Q runs before Lane H because 053/054/056 all edit `execute_run.py`
and every plan's verification depends on a trustworthy gate. Findings
audited but not planned are recorded in the README's rejected/deferred
section — check there before re-proposing.

| Plan | Scope | Priority | When |
|------|-------|----------|------|
| 062 | Trustworthy local gate & DX: `make api-test` provisions the test DB, CI uv caching, worker watch-reload, root `.editorconfig`, correct the two stale AGENTS.md claims (frontend tests exist; asyncio auto mode). **DONE 2026-07-07.** | P1 | Complete. |
| 063 | Behavioral test safety net: Vitest coverage for the message-parts parser, agent/schedule form models (incl. the DST-sensitive timezone round-trip), approval decisions, shared formatters; backend tests pinning the internal-token workspace-confinement branches in `core/dependencies.py` (no code mints those tokens today — keep-vs-remove is a recorded maintainer decision). **DONE 2026-07-07.** | P1 | Complete. |
| 064 | Web scaffolding consolidation: one workspace-scoped query-key factory (kills 8 copies of the `__no_workspace__` tenant-scoping sentinel), consistent mutation invalidation, shared `FormValidationEntry`/`buildFieldErrors` in `lib/forms.ts`, one home for date/time formatting, `window.alert` → `Alert`. **DONE 2026-07-07.** | P1 | Complete. |
| 065 | API scaffolding consolidation: `paginate()` + `OffsetPage` envelope, `AssetSpec`-driven avatar/icon lifecycle helpers, notifications split to one-op-per-file. **DONE 2026-07-07.** | P1 | Complete. |
| 066 | Decompose the ~286-line `execute_run` into named phase helpers behind new characterization tests (pre-start failure ordering, precondition trio, attachment prompt promotion, sink close). **DONE 2026-07-07.** Dispatch split explicitly rejected — `dispatch.py` stays the single wrap-here choke point. | P1 | Complete. |

### Lane B — Best-Practice Amendments (added 2026-07-07; plans 067–074)

A best-practice review of the written-but-unexecuted plan set against
current industry practice (OAuth 2.1/RFC 9700, credential-vault
encryption, prompt-cache engineering, memory-system literature, CSP/
sandbox semantics, structured-concurrency cancellation), every finding
verified against the target plan's own text. Each Lane B plan is a
docs-only amendment plan in the 061 mold: it appends a drafted amendment
block to its target plan(s) and must land **before its target executes** —
the code cost is absorbed into the amended plans. Deciding these now,
while zero target code exists, is free; retrofitting after execution is a
migration.

| Plan | Scope | Priority | When |
|------|-------|----------|------|
| 067 | OAuth PKCE (S256) + single-use state via a server-side pending-state row; https redirect-URI enforcement outside local. **DONE 2026-07-10.** Amends 038. | P1 | Complete. |
| 068 | Credential encryption posture: root key through the secrets-provider seam, HKDF purpose-separated subkeys (fingerprints, artifact view URLs), re-encryption sweep job so rotation actually retires keys, `SecretStr` for the Ads developer token. **DONE 2026-07-10.** Amends 037/041/050. | P1 | Complete. |
| 069 | Memory block ordering determinism: rank on stored confidence, not wall-clock-decayed `effective_confidence` — decay-crossing reorders silently bust the prompt-cache prefix 049 exists to protect; two-`now` byte-identity test. Amends 049. | P1 | Before 049 |
| 070 | Artifact CSP: drop the general-purpose CDN whitelist (jsdelivr/unpkg serve every npm package — arbitrary script one URL away, and `connect-src 'none'` does not block self-navigation exfil); v1 artifacts are self-contained, self-hosted vetted bundles are the named follow-up. Amends 050. | P1 | Before 050 |
| 071 | Memory dedup contradiction resolution: near-duplicates surface to the writing agent (save-as-new / supersede / skip) instead of silently reinforcing the stale row; threshold calibration fixture; decay half-lives marked provisional under Gate G4. Amends 048. | P1 | Before 048 |
| 072 | Sandbox egress verification: per-provider DNS/HTTP canary probe; `run_code`'s `internal`+`supports_auto` classification gated on an egress-verified provider allowlist; re-probe on SDK bumps; poisoned-file fixture. Amends 059. | P1 | Before 059 |
| 073 | Cancellation terminal hardening: shield terminal persistence against double-cancel, tier-2 dedupe of already-cancelled tasks, `cancelled` disposition on the interrupted dispatch audit row. **DONE 2026-07-09.** Amends 053. | P1 | Complete. |
| 074 | Consistency sweep: scheduled re-discovery job for permission staleness (039), `top_k`/CTE-limit cross-check (045), deliberate truncate-only `text-embedding-3-large` registry posture (043), connection-rename route reconciliation (042↔038), IP-pinned connects for DNS-rebinding TOCTOU (044). **DONE 2026-07-10.** Amends 038/039/042/043/044/045. | P1 | Complete. |

Adjacent additions from the same review, not in Lane B: 075 (**DONE
2026-07-10** — threat-model design note, registered Gate G6 and amended
046/048/049/055/056/059), 076 (**DONE
2026-07-10** — bounded tool results + calibrated token estimation), and 077
(**DONE 2026-07-10** — inbound integration events design note covering
webhooks/verification/event-triggered runs; reserves the seam in 037/041
before Phase 4a code lands and reserves 079 as the first implementation;
MCP stays deferred per D7).

### Lane P — Public Launch & Adoption (added 2026-07-07; plan 078)

The roadmap builds the platform to be good; nothing in it makes the repo
visible. Lane P owns adoption: 078 delivers the README-as-storefront
rewrite, the community health pack (SECURITY/CONTRIBUTING/CODE_OF_CONDUCT,
issue/PR templates), supply-chain automation (dependabot, CodeQL,
dependency audit, SHA-pinned actions), the first tagged release
(CHANGELOG, v0.1.0, GHCR images), and the OpenAPI reference decision.
Follow-on lane items recorded in 078's maintenance notes (docs site
seeded from `docs/architecture/`, one-command seeded demo, demo video,
published eval results once 055 lands, deployment guides) become numbered
Lane P plans when picked up. 078 has no product-code dependencies and
interleaves any time; it can build on the completed C05 license and README
baseline.

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
C03 (DONE) → C04 (DONE) → 034 (DONE) → 035 (DONE) → 036 (DONE) → 024 (DONE) → 061 (DONE) → 014 (DONE) → 062 (DONE) → 063 (DONE) → 064 (DONE) → 065 (DONE) → 066 (DONE) → 073 (DONE) → 053 (DONE) → 054 (DONE) → 076 (DONE) → C05 (DONE) →
067 (DONE) → 068 (DONE) → 074 (DONE) → 077 (DONE) → 075 (DONE) → 080 (DONE) → 037 (DONE) → 038 (DONE) → {039–042 ∥ 043–047 ∥ 055} → 079 → 056 → 071 → 048 →
069 → 049 → 057 → 070 → 050 → 051 → 072 → 059 → 060` — with 015, 052, 058,
078, and the polish lane as filler (078 is P1 filler: no dependencies,
land it early).

Lane B placement rationale: each amendment lands immediately before the
plan it binds — 073 before 053 (both done), 067/068/074/077/075 (done)
before the Phase 4a/4b fork they gate, 079 after its 037–041 substrate,
071 before 048, 069
before 049, 070 before 050, 072 before 059. 076 is done; it landed after
054 and before 056, whose pressure math consumes its calibrated estimator.

Lane Q placement rationale: 062 first because every later plan verifies
through the gate it fixes; 063 is done and precedes 064 (its tests are the
refactor's safety net); 064/065 are independent and can interleave; 066
must precede 053/054/056 because all three edit `execute_run.py` and the
decomposition hands each a named seam.

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
