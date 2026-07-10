# Plan 080 — Phase 4a/4b Handoff Readiness Sweep

- **Status**: DONE (2026-07-10)
- **Kind**: docs-only amendment plan (the 074 mold). No code changes.
- **Targets**: 037, 038, 039, 040, 041, 042, 044, 045, 046, 047;
  `docs/architecture/threat-model.md`, `docs/architecture/governance.md`,
  `docs/architecture/integration-packaging.md`; `docs/plans/FOLLOW_UPS.md`;
  the tracking tables in `000_README.md` / `000_MASTER_ROADMAP.md`.
- **Grounding**: a three-track pre-handoff review at `bbfd769` (2026-07-10) —
  one deep pass per workstream plus a gates/tracking audit — with every
  finding re-verified against the target document's text and the live code.

## Why

Phases 4a (integrations) and 4b (knowledge base) are about to be handed to
the team. The review confirmed the gate preconditions (G1 + extension, G2,
G3, G4 registration, substrate cleanliness) genuinely hold in code, and that
every amendment block claimed by 061/067/068/074/075/077 is present in its
target. It also found a set of documentation defects that would stall or
mislead executors: two plans whose runtime anchors went stale when
053/054/066 refactored `execute_run` (their own STOP conditions would fire
on contact), two uninventoried Gate G6 untrusted-content channels, an
orphaned upload-ingestion seam left over from before 033 landed, and a tail
of cross-plan contract mismatches. All fixes are docs-level; this plan
records the decisions and applies them as `Amendment (plan 080, 2026-07-10)`
blocks in the target plans.

## Decisions taken

1. **Fake-provider token seam (037 / packaging note)**: extend
   `IntegrationProviderPlugin` with an optional `oauth_operations` attribute
   (default `None`), resolved only through the loader. The engine's generic
   manifest-driven OAuth HTTP flow is the default; the fake provider supplies
   an in-process implementation. The §4.6 import laws are unchanged —
   `services/` still reaches provider code only through the loader. This
   resolves the contradiction between 037's 061-amendment (fake moves wholly
   to `integrations/fake/`) and the plugin contract having no token seam.
   **Superseded same day by roadmap decision D11**: the fake integration
   provider was removed entirely and the `oauth_operations` seam was dropped
   with its only consumer — the generic manifest-driven flow is the only
   token path. See the `Amendment (decision D11, 2026-07-10)` blocks in
   037/038/039 and the packaging note.
2. **Route naming (038/039 authoritative over 042)**:
   `POST /integrations/connections/oauth/start`,
   `PUT /integrations/connections/{id}/resources/selection`,
   `POST /integrations/connections/{id}/discover`. 038's callback success
   redirect additionally appends `connection_id` and `status` query
   parameters, which 042's success alert consumes.
3. **Upload-source KB ingestion (044)**: plan 033 is DONE, so 044 ingests
   `source_type="upload"` for real — revision markdown read from
   `FileRevision.markdown_object_key` through the storage provider (the
   `read_file` tool precedent; `get_file_revision_content.py` was
   considered and rejected — it serves raw editable text and requires a
   request/user for audit, unusable from a job handler), conversion for
   URL/manual sources via the shared `utils/document_markdown.py` helpers. The
   "reject with pending-033 message" stance and the instruction to copy
   converter code from `services/skills/documents/utils.py` are superseded
   (a copy would violate the shared-helper rule). 046/047 build on a working
   upload path.
4. **KB job handler convention (044)**: follow the shipped precedent — thin
   handler modules in `services/jobs/handlers/` that call `services/kb`
   operations (mirrors `extract_file_markdown.py`). The "registry comment
   invitation" 044 cited does not exist.
5. **KB search limits (045/046)**: 046 drops its parallel
   `KB_SEARCH_DEFAULT_LIMIT`/`KB_SEARCH_MAX_LIMIT` settings; the tool clamps
   its `limit` argument to 045's `KB_SEARCH_TOP_K_DEFAULT`/
   `KB_SEARCH_TOP_K_MAX`. One pair of settings, per 046's own
   no-parallel-settings rule.
6. **Search-hit privacy fields (045)**: the hybrid-search SELECT and
   `KBSearchHit` include `is_private`, and `search_chunks` gains a
   SQL-level `private_only` filter — both are required by 046/047's dictated
   contracts.
7. **PKCE verifier key purpose (038)**: the stored `code_verifier` is
   encrypted under a dedicated HKDF purpose (`praxis:oauth-pkce-verifier:v1`),
   not 068's credential-token purpose — purpose separation applies to the
   verifier too.
8. **Governance §2 (KB writes)**: KB documents are Praxis-internal write
   targets (D9 — Praxis owns the KB); agent-initiated KB document writes
   default to tool-level `approval` (plan 046's write-policy choke point).
   Recorded in `governance.md` §2; 046's Step 8 annotates that bullet.
9. **Gate G6 channels**: two new rows in `threat-model.md` §2 —
   **(g) integration-fetched content** (provider API payloads such as Gmail
   bodies, Airtable records, Ads reports; owner 041) and **(h) KB ingestion
   annotation helper** (untrusted document content fed to the contextual
   annotation model; model-authored `context_line` enters the index and
   search payloads; owner 044). 041 and 044 carry binding amendments with
   fixture and deterministic-test requirements.
10. **Plan 079 authorship**: the 079 plan document (inbound event receipt
    spine + Airtable webhooks, reserved by 077) is written by the Phase 4a
    executor once 041 lands, at the facts-recheck point 077's maintenance
    notes define. Recorded in the README dependency notes.
11. **Anchor refreshes (040/046 blockers; 039/041/042/047 minor)**: the
    runtime seams moved after these plans were anchored at `0cbbb39` —
    `RuntimeDeps` is now built in `runtime/execute/setup.py` inside
    `prepare_runtime()`, `load_actor_context` lives in
    `runtime/load_context.py`, `runtime_prompt_blocks` is
    `(agent, *, include_delegation, available_files=())` returning four
    blocks, the tool contract gained `effect_scope`/`effect_scope_resolver`/
    `max_result_chars`/`presentation`, and `dispatch_tool_execution` moved.
    040's `active_context` block slots between `delegation` and
    `available_files` (the roadmap §1 block order). Vitest now exists on the
    frontend (062/063), superseding 042/047's "no frontend test framework"
    claims. Integration write tools must declare `effect_scope="external"`
    (041); the deferred `save_to_knowledge` is `effect_scope="internal"`
    with tool-level `approval` (046).

## Out of scope

- Plan 043 (embeddings provider): reviewed clean; only cosmetic line drift
  its own pre-flight absorbs. No amendment.
- Code changes of any kind. The amended plans own the implementation.
- Rewriting superseded body text in target plans — house style is appended
  amendment blocks with wins-clauses plus inline supersession markers where
  a literal reading of a command or done criterion would fail.

## Done criteria

- Every target plan carries a clearly marked `Amendment (plan 080,
  2026-07-10)` block and a pointer in its top executor blockquote.
- `threat-model.md` has channel rows (g)/(h), extended §4 fixtures, and
  updated §6 consumed-by entries; `governance.md` §2 records the KB-write
  default; `integration-packaging.md` records the optional
  `oauth_operations` plugin seam.
- 029 and 061 (long DONE) move to `plans/complete/`; FOLLOW_UPS.md absorbs
  the three roadmap-prose follow-ups (email/Slack result delivery, KB
  ingestion from integration sources, workspace LLM token budgets); the
  README/roadmap tables record plan 080 and the 079 authorship rule.

## STOP conditions

- If applying an amendment would contradict a decision a completed plan
  already recorded (061/067/068/074/075/077), stop and reconcile here first.
- If a code anchor cited in an amendment cannot be re-verified against the
  live tree, verify and correct before writing it.
