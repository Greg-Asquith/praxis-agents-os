# Donor Port Roadmap

Selective port of five feature areas from the donor app
(`saas-template-828165...`) into Praxis Agents OS: **tool registry,
integrations, file management, knowledge base + agent memory, and agent
artifacts**. We bring over the *ideas that earned their keep*, not the
implementations. This doc is the synthesis of a deep read of the donor code,
a map of the current Praxis foundations, and current (2025–2026) industry
practice for each subsystem.

Next step: break each phase below into numbered implementation plans under
`docs/plans/` (continuing from 020), following the existing plan template
(Status block, STOP conditions, follow-ups) and updating the README table.

---

## 1. The Donor In One Paragraph (Why We Rebuild, Not Copy)

The donor's biggest structural mistake is that its agent runtime and tool
registry live in **Next.js** (TypeScript/Zod, ~200 tools), while auth,
tenancy, credentials, and audit live in FastAPI. That split forces two
secret-authenticated internal HTTP bridges, a FastAPI→Next→FastAPI round
trip per workflow tool call, schemas duplicated up to four times per tool,
and permission logic hand-mirrored in two languages. Praxis already made
the correct structural decision — the agent runtime (Pydantic AI) lives in
the backend — so the single most valuable move of this port is: **rebuild
everything tool-shaped as one Python registry in the API, and let every
subsystem below hang its agent surface off that registry.** Beyond that,
the donor is heavy with mid-refactor residue (compat shims, dead
subsystems, 21-mixin facade classes, parallel queues and retrieval stacks);
none of that comes over.

## 2. What We Build On (Current Praxis Foundations)

Already in place and load-bearing for this work:

- **Agent runtime**: Pydantic AI ≥2.1, `RuntimeDeps` dataclass
  (`services/agents/runtime/context.py`) as `deps_type` — the injection
  point for db/user/workspace/conversation/run. Native approval flow via
  `DeferredToolRequests` persisted in `AgentRun.metadata_json`. Custom SSE
  protocol (`docs/architecture/agent-runtime.md`).
- **Tool catalog seed**: `services/agents/runtime/tools/registry.py` — a
  hardcoded dict with `Agent.tool_names` allowlist + `Agent.tool_policies`
  (`auto`/`approval`) per agent, and unused `defer_loading` plumbing. This
  is the kernel the real registry grows from.
- **Storage**: provider-neutral `StorageProvider` contract
  (`services/storage/`, plans 002–003, DONE): local_fs/GCS/S3/Azure,
  signed upload → confirm pattern proven in `services/assets/`. No DB file
  records yet — deliberately left for this work.
- **Exception layer**: `core/exceptions/integration.py` already defines the
  full RFC 7807 integration error hierarchy. Build against it.
- **pgvector**: extension enabled in core migration 0001, zero consumers.
  The knowledge base is its first real use.
- **Conventions**: route-per-file, service-op-per-file, soft-delete
  `BaseModel`, append-only audit events (`AuditResourceType` needs new
  entries per feature), middleware ordering in `main.py`, workspace-scoped
  everything, two Alembic branches (`core@head`, `app@head`).
- **Completed overlap**: skills plans 016–020 are DONE. Skills are deliberately
  orthogonal to tool grants (a donor decision worth keeping). Plan 017's
  document pipeline shares machinery with file processing here; sequence
  accordingly.

**Schema decision (recommendation): everything in this roadmap is platform
infrastructure, not product domain — it goes in `core` (public schema),
not the `app` schema.** The `app` branch stays reserved for verticals
built *on* the platform.

## 3. Cross-Cutting Architecture Decisions

These are the decisions that make the five subsystems one system:

1. **One tool registry, in Python, in the backend.** A `ToolDefinition`
   contract (structured `provider` + `operation` name — never a parsed
   string), Pydantic input *and output* models, `access`/`effect`
   metadata, `supports_auto`/`supports_approval`/`default_mode`, async
   `execute(ctx, input)`. Tools call service functions in-process; the
   REST routes and the tools share the same services. Every subsystem
   below ships its agent surface as registry entries.
2. **One dispatch choke point.** A wrapper around tool execution (Pydantic
   AI `WrapperToolset.call_tool()` or equivalent in our runtime) writes an
   audit row per invocation — workspace, user, agent, run, tool name +
   provider, input digest, outcome, latency, mutation status, approval
   reference. Add `tool_name`/`tool_provider` columns to `audit_event`
   (donor pattern, proven). Native tools, integration tools, and future
   MCP tools all pass through it uniformly.
3. **Postgres is enough.** Connections, documents, chunks, memories,
   artifacts, jobs, audit — all in Postgres with pgvector ≥0.8 + tsvector.
   No Redis, no graph DB, no external queue. The donor's DB-polling worker
   pattern (`FOR UPDATE SKIP LOCKED`, content-hash idempotency, stale
   reclaim, bounded retries) is its most transferable code and matches our
   existing schedule-runner worker.
4. **One generic job queue table** (`jobs`: kind × subject × content_hash,
   priority, retries, partial-unique in-flight dedup) shared by file
   extraction, chunking, embedding, summarisation, and integration
   discovery. The donor built this (`knowledge_model_jobs`) and then
   undermined it with a second parallel queue; we build it once.
5. **One hybrid search engine**, used by both the knowledge base and agent
   memory: tsvector lexical + pgvector cosine, merged with Reciprocal Rank
   Fusion, with the donor's "pending-embedding lexical fallback" (recent
   unembedded rows still findable — solves "I just told you that"), and a
   pluggable reranker interface (none by default).
6. **Context is injected, never model-chosen.** Which external account,
   which connection, which workspace — resolved server-side per run and
   passed through `RuntimeDeps`. Tool schemas have no account parameters.
   This removes an entire class of LLM errors and confused-deputy risks.
7. **Everything the agent writes is a tool call**, so memory writes, file
   writes, and artifact creation inherit the existing approval + audit
   machinery for free. Human legibility is the design principle: editable
   memories, versioned diffable artifacts, visible approval queues.

## 4. Subsystem Designs

### 4.1 Tool Registry (the spine — build first)

**Port from donor (ideas):** the `definePraxisTool` contract — one
definition yielding input+output schemas, access/effect metadata, mode
capabilities, and execution, with runtime output validation and a
**mutation tracker** (if output validation fails after a side effect, the
error carries "the external action may have completed — check before
retrying"). The three-mode policy model (`off`/`auto`/`approval`) with
per-agent `tool_policies` overriding tool `default_mode`. Progressive
disclosure (baseline tools + `list_available_tools`/`request_tool`
unlocking). Delegation-style capability envelopes for non-interactive runs
(schedules): backend-constructed grants (`allowed_tools`, principal class,
side-effect policy, idempotency key) instead of trusting session context.

**Fix from donor:** registry in the wrong process; schema quadruplication;
policy duplicated in two languages; approval state inferred by diffing
client-sent message JSON (ours is already first-class — keep it that way);
no write-time validation of agent `tool_names` (add it).

**Design:**

- `ToolDefinition` (Pydantic) + `@registry.tool(...)` decorator; provider
  packages contribute; uniqueness asserted at import; Pydantic AI `Tool`s
  generated from the same definitions (this generalizes the existing
  `RuntimeToolDefinition.to_pydantic_tool()`).
- `execute(ctx: RuntimeDeps, input)` — tools receive typed deps (db
  session, user, workspace, connection resolver, active context, audit
  recorder). No HTTP self-calls, ever.
- One permission function `is_tool_allowed(tool, principal_ctx)` used by
  discovery endpoints, agent construction, and dispatch-time checks.
- Registry is data-queryable: a read API for the frontend tool catalog and
  the agent form (replacing hardcoded lists), and write-time validation of
  `Agent.tool_names`/`tool_policies` against it.
- Dynamic availability: integration-backed tools are filtered out when the
  workspace has no active connection for that provider (composed via
  Pydantic AI dynamic/filtered toolsets).
- Later (explicitly deferred): MCP client toolsets (`MCPToolset`, prefixed
  + filtered + approval-by-default for write tools) as the long-tail
  extensibility path; progressive disclosure via the existing
  `defer_loading` plumbing once the catalog is big enough to need it.

### 4.2 Integrations & External Platform Context

**Port from donor (this is its strongest subsystem):**

- **Four-table core, nearly as-is**: `external_credentials`
  (secret-bearing row, encrypted OAuth tokens, HMAC **principal
  fingerprint** for dedup of the same external principal across
  connections), `integration_connections` (owner user XOR workspace,
  enforced by CHECK; one active connection per provider per owner via
  partial unique index; status machine `auth_pending → discovery_pending →
  needs_resource_selection → active/degraded/error/revoked`),
  `integration_resources` (generic discovered sub-entity: ad account, GA4
  property, base — with `enabled` admin selection and
  available/unavailable/removed lifecycle), `integration_discovery_runs`
  (recorded runs with counters; failed discovery keeps the credential so
  users retry without reconnecting).
- **Secret references over stored secrets** for api_key/service_account/
  system_token modes: store `{provider, name, version}` pointing into a
  secret manager (or local env var provider for dev), resolve at call
  time. Only OAuth tokens are stored, encrypted, in Postgres.
- **Declarative provider manifest** with import-time invariant checks: one
  source of truth for auth modes, owner scope, resource types, env gating,
  required form fields, capability flags.
- **Active Context**: per-user-per-workspace persisted selection of a
  single resource or a named cross-provider **context group** ("Client X"
  = Google Ads account + GA4 property + Meta account). Server-side
  resolution with compatibility filtering per tool
  (`provider_keys`/`resource_types`), fan-out execution across compatible
  resources with per-resource success/error results, and write-permission
  gating from discovered resource metadata. Status machine driven by data
  (`needs_resource_selection` computed from enabled resources).
- Hard-won details: `include_granted_scopes=false` on Google auth URLs,
  filtering persisted scopes to requested ones, `Retry-After`-aware
  retries, structured integration exception mapping (our
  `core/exceptions/integration.py` already matches).

**Fix from donor:**

- **One provider interface**: manifest entry + one class with
  `start_oauth / handle_callback / validate_* / refresh / revoke / test /
  discover_resources / build_client`. Kill the two parallel discovery
  frameworks and the copy-pasted registry imports (derive registration
  from the manifest).
- **Async discovery** as a background job (the status enum already
  supports `discovery_pending`) — never synchronously inside the OAuth
  callback redirect.
- **One credential service** owning refresh for both httpx-based and
  SDK-based clients: proactive refresh 60–180s before expiry, serialized
  per connection with `SELECT ... FOR UPDATE` (rotating refresh tokens die
  if double-refreshed), `needs_reauth` status on refresh-token failure,
  every issuance/refresh/failure audited.
- **Signed single-value OAuth state** (one encrypted blob carrying state +
  owner + workspace + redirect) instead of the donor's four-cookie flow.
- Move the client-identity logic into the manifest (no if-ladders); no
  compat shims, no legacy target dataclasses — pass `IntegrationResource`
  straight to operations.

**Runtime consumption:** active context resolved once per run and injected
via `RuntimeDeps`; a rendered context block in the system prompt tells the
model what it's operating on. Integration tools are ordinary registry
entries whose `execute` resolves connection + credentials via the
credential service. Per-account audit events on every operation.

**Provider scope for v1:** pick 2–3 providers that exercise all the shapes
— one user-scoped OAuth (e.g. Google Mail or Drive), one workspace-scoped
OAuth with resource discovery + hierarchy (Google Ads or GA4), one api_key
+ secret-reference provider (e.g. Airtable). The manifest makes the rest
incremental.

### 4.3 File Management

**Port from donor (its strongest single idea):**

- **Logical `File` + immutable `FileRevision`**: revisions are append-only
  with DB-level immutability enforcement (ORM listener), exactly-one-actor
  provenance (`created_by_user_id` XOR agent XOR system, CHECK-enforced),
  `revision_kind` (create/edit/replace/restore/import), sha256
  `content_hash`, roll-forward restore (history never rewritten),
  optimistic concurrency on edit (`expected_current_revision_id` → 409).
- **Non-copying `FileReference`**: one canonical file per workspace,
  attached to N surfaces. Generalize `target_type` beyond `conversation`
  from day one (conversation, artifact, agent, schedule run).
- **Two-phase signed upload** with confirm-time verification against
  store-reported size/content-type, and content-hash dedup at
  request-upload time (this extends the proven `services/assets` pattern).
- **The file contract as data**: one policy table (editable-text /
  ingestible-document / image / etc. with strict MIME↔extension pairs)
  shared by backend and frontend. Size limits already exist in
  `core/settings/files.py` (`MAX_FILE_SIZE_DOCUMENT/AGENT_FILE/...`).
- **Scratch space for agents**: DB-backed text scratch scoped to
  conversation XOR run, rolling TTL, size-capped, overwrite-in-place, with
  approval-gated **promote** to a canonical file. Cheap and agents love it.

**Fix from donor:** drop the `KnowledgeSource` triple-bookkeeping and
dual-ID resolution entirely (if the KB needs provenance it references
`file_revision_id` from its side). No 21-mixin facade — flat
one-operation-per-file services. **Background processing** (extraction →
markdown → enrichment → chunking/embedding) driven by the shared jobs
table with a real retry sweep and a small status enum
(`pending/processing/ready/error`) — never synchronous in the confirm
request. One storage path scheme, workspace-first and revision-addressed
(`workspaces/{workspace_id}/files/{file_id}/{revision_id}{ext}`), which
makes blob refcounting unnecessary. Symmetric deletion (soft-delete rows
AND tombstone blobs, sweeper hard-deletes both after retention) plus an
abandoned-upload expiry job; purge scratch content on expiry and delete
scratch after promotion.

**Agent surface (registry tools):** `list_files`, `read_file` (signed-url
or content modes with truncation hints), `write_file` (scratch free;
durable writes approval-gated), `promote_scratch`, `search_files` (rides
the hybrid search engine once KB chunking exists). An
`<available_files>`-style prompt block listing conversation-attached
files.

**UI:** a files page (table + detail sheet with revisions/diff), file
cards in chat with open/download via short-lived signed URLs.

### 4.4 Knowledge Base (Documents, Not Graph)

The donor verdict is unambiguous: the graph never earned its cost —
entities came from deterministic integration mappings, "traversal" was a
1-hop JOIN at a fixed score, and meanwhile the KG **never chunked**
(12k-char truncation) and **never had a vector index** (untyped columns
made HNSW impossible; every semantic query was a seq scan). What worked
was the boring plumbing. So:

**Tables (4 replace the donor's 11):**

- `kb_documents` ≈ donor `knowledge_sources` minus graph counters:
  workspace-scoped, `source_type` (upload/url/manual/conversation/
  integration), processing state machine with retry columns,
  `content_hash`, optional `file_revision_id` (uploads ride file
  management), `external_id`/`external_url`, is_private, tsvector column.
- `kb_chunks` ≈ donor `file_search_chunks` done right: chunk_index,
  content, char offsets, **typed `Vector(n)` on `halfvec` with HNSW from
  day one**, tsvector, metadata JSONB, embedding provider/model/dims
  recorded per collection so we can migrate.
- `agent_memories` (§4.5).
- shared `jobs` table (§3.4).

**Ingestion pipeline:** fetch/extract → markdown → **structure-aware
chunking** (heading-aware, ~400–800 tokens, 10–15% overlap) → optional
**contextual annotation** (Anthropic contextual-retrieval style: LLM
prepends a 50–100-token document-context line to each chunk before
embedding and lexical indexing; flag per document source, ingestion-time
cost only, the single highest-ROI retrieval upgrade) → async embed jobs →
optional per-document summary. SKIP-LOCKED workers throughout.

**Retrieval:** one hybrid engine — tsvector + cosine as two top-K CTEs
merged with RRF (never raw-score blending), pending-embedding lexical
fallback, metadata/workspace filtering in SQL (pgvector ≥0.8 with
`hnsw.iterative_scan` for filtered queries), pluggable reranker interface
(default none; bge-reranker-v2-m3 or an API as options later).

**Agentic search over one-shot RAG:** expose retrieval as tools —
`search_knowledge(query, filters)` returning chunks with document
metadata + `read_document(doc_id, range)` for follow-up — and let the
model iterate. No pre-run injection pipeline, no 10-mode regex planner.
The same endpoint serves the UI search.

**Embeddings:** pluggable provider ABC (port the donor's, trimmed):
default OpenAI `text-embedding-3-small` (or similar current small model),
with a local option (Ollama/BGE-M3) for self-hosters. 512–1024 dims via
Matryoshka truncation. Record model+dims; never mix in one collection.

**Write policy:** a slim single choke point (one file, not eleven):
provenance required, workspace scoping, the donor's hard rule that
**private-source material can never become workspace-shared**, secret
blocking, and a minimal noise gate.

### 4.5 Agent Memory

Skip Letta/Mem0/Zep as dependencies; build a thin layer on the KB
infrastructure. The winning patterns (Claude Code's CLAUDE.md, Letta's
memory blocks) are: small always-in-context core + searchable notes,
agent-initiated writes, human-visible and human-editable.

**Model:** `agent_memories`: workspace_id, `scope`
(agent/user/workspace) + scope refs, `kind` (`core` — small, capped,
always injected; `note` — searchable), `memory_type` (collapse the
donor's six to **fact / preference / episode**, optionally outcome for
schedule runs), title, content_md, embedding + tsv, importance,
confidence, `expires_at`, supersession (`superseded_by_id`, never hard
delete), provenance (conversation/run/source), created_by (agent/user).

**Write path (donor's best memory idea):** memory tools
(`save_memory`, `search_memory`, `update_memory`, `forget_memory`) where
**the backend mints provenance** — the LLM says "remember X", the service
resolves the conversation/run evidence trail. Writes are ordinary tool
calls → audit + optional approval for free, which directly mitigates
memory poisoning. A standing write-policy snippet in the system prompt.

**Ranking & lifecycle (port, it's cheap and effective):** read-time
confidence decay (per-type rates, never mutating rows), reinforcement on
access, write-time dedup (cosine ≥0.92 vs same-scope memories →
reinforce instead of insert), TTL + archival. Background consolidation
job deferred until note sprawl is real.

**Injection:** core memories rendered into the system prompt per run with
a hard character budget; notes come only through search. Port the donor's
context-formatter *pattern*: budgeted summary-plus-pointers (each line
carries the tool call that fetches detail), hard timeout returning
partial results.

**UI:** memory is a first-class surface — users can read, edit, and
delete anything an agent remembered, per scope. This is a genuine
differentiator over black-box extraction pipelines.

### 4.6 Agent Artifacts (HTML Reports etc.)

The donor's biggest gap: no lightweight artifact path — a simple HTML
report required its full Apps machinery (builder agent, manifests,
postMessage SDK, 59 route files). We build the missing middle tier and
defer interactive apps entirely.

**Model:** `artifacts` (workspace, conversation/run link, agent,
`artifact_type`: html / markdown / mermaid / csv / image-ref, title,
`current_version_id`) with versions **as `FileRevision`s** (source_type
`agent_artifact`) — reusing the immutable revision chain, actor
provenance, and storage instead of a parallel versioning system. Agent
edits and user edits both append; Canvas-style diff/restore falls out of
the revision chain.

**Serving (three-layer defense, industry-standard):**

1. Sandboxed iframe: `sandbox="allow-scripts"` **without
   `allow-same-origin`** (opaque origin — no cookies, no storage), for
   both srcdoc previews and served documents.
2. Separate origin for served artifacts: a dedicated route with
   configurable `ARTIFACT_ORIGIN`; document that production should use a
   distinct registrable domain (not a subdomain — cookie scoping and
   same-site CSRF). No cookies on that origin at all.
3. Strict CSP on the artifact response: `default-src 'none'`, inline
   script/style allowed, a small CDN whitelist, `connect-src 'none'` so a
   prompt-injected artifact can't phone home, `frame-ancestors` pinned to
   the app origin. `X-Content-Type-Options: nosniff`; non-HTML types
   served as attachment/plain. Never `dangerouslySetInnerHTML`.

**Sharing:** unguessable-token share links (≥128-bit), pinned to a
specific version by default, with `expires_at`/`revoked_at` and audit
rows. This is the platform's first anonymous-access surface — treat as
high-risk, small, and explicit.

**Agent surface:** `create_artifact` / `update_artifact` registry tools
(write-classified; approval per agent policy); artifact cards in chat
rendering the sandboxed preview inline with a version selector.

**Deferred:** the entire interactive Apps system (capability bridge,
frame-session JWTs, app builder). If it ever comes back, the donor's
security kernel (input-hash-bound approval tokens, release pinning by
revision ID, vendored pinned assets) is the reference — but server-served
documents with real CSP this time, and distinct keys per token family.

## 5. Explicitly Not Ported

- Knowledge **graph**: entities, relationships, ontology/type registries,
  entity resolution, graph expansion, path explanation, per-entity
  timelines, conversation-context junction tables.
- The Next.js tool registry, workflow tool bridge, internal-JWT
  self-calls, and everything else that exists to cross the two-process
  boundary.
- The Apps subsystem (builder conversations, manifests, postMessage SDK,
  design policies) — replaced by read-only artifacts for now.
- Workflows engine, app builder, music generation, stem splitting, e2b
  tools, ad-hoc analytics services (`analytics_context`/`ad_performance`
  are already empty husks in the donor).
- Donor dead code: provider Batch API layer, contradiction detection,
  custom LLM tools CRUD, span offset scaffolding, dual summarisation
  queues, compat shims of every kind.
- Regex-heuristic sprawl (memory classifier banks, 10-mode retrieval
  planner, noise-policy pattern libraries) — replaced by a handful of
  tunables and model judgment.

## 6. Phasing & Proposed Plan Breakdown

Dependency spine: **registry → files/jobs → (integrations ∥ KB) →
memory → artifacts**, with UI plans trailing each backend slice.
Numbering continues from 020; exact titles to be fixed when each plan is
written. Skills plans 016–018 should ideally land before the memory/KB
prompt-injection work so system-prompt assembly is designed once.

### Phase A — Tool Registry (the spine)

| Plan | Scope |
|------|-------|
| A1 | `ToolDefinition` contract + decorator registry + import-time validation; migrate the two existing catalog tools; write-time validation of `Agent.tool_names`/`tool_policies`; registry read API for the frontend |
| A2 | Dispatch choke point: audit rows per tool invocation (`tool_name`/`tool_provider` audit columns), mutation tracker, output-contract validation |
| A3 | Frontend: tool catalog surface in the agent form driven by the registry API (replaces hardcoded lists) |

### Phase B — Files & Jobs (shared substrate)

| Plan | Scope |
|------|-------|
| B1 | Generic `jobs` table + SKIP-LOCKED worker harness (kind × subject × content_hash, retries, stale reclaim) |
| B2 | `File`/`FileRevision`/`FileReference` models + migrations + immutability enforcement + file contract policy |
| B3 | Upload/confirm/edit/restore/delete services + routes (two-phase signed upload, dedup, symmetric deletion, sweepers) |
| B4 | Background file processing: extraction → markdown via jobs; status lifecycle |
| B5 | Agent file tools (list/read/write/scratch/promote) + scratch model + prompt block |
| B6 | Files UI: files page, detail sheet with revisions/diff, chat file cards |

### Phase C — Integrations

| Plan | Scope |
|------|-------|
| C1 | Core models (credentials/connections/resources/discovery_runs) + provider manifest + credential service (encryption, fingerprinting, locked proactive refresh) + secret references |
| C2 | OAuth flows (initiate/callback with signed state), non-OAuth connect, test/revoke/refresh routes |
| C3 | Async resource discovery via jobs + resource selection + connection status machine |
| C4 | Active context: selections, context groups, server-side resolution + fan-out executor, `RuntimeDeps` injection + prompt block |
| C5 | First providers (one user-OAuth, one workspace-OAuth with discovery, one api-key) + their operation services and registry tools |
| C6 | Integrations UI: provider cards, connect flows, resource selection, context picker in chat header |

### Phase D — Knowledge Base

| Plan | Scope |
|------|-------|
| D1 | Embeddings provider service (ABC + OpenAI + local option) |
| D2 | `kb_documents`/`kb_chunks` models + migrations (halfvec HNSW + tsvector); ingestion pipeline (chunking + optional contextual annotation) via jobs |
| D3 | Hybrid search engine (RRF, pending-embedding fallback, filters, reranker interface) + search/read routes |
| D4 | Agent tools (`search_knowledge`, `read_document`) + write policy gate + document sources (upload via Files, URL, manual) |
| D5 | KB UI: documents table, ingestion status, search |

### Phase E — Agent Memory

| Plan | Scope |
|------|-------|
| E1 | `agent_memories` model + write service (backend-minted provenance, dedup-reinforce, decay, supersession) + memory tools |
| E2 | Core-memory prompt injection (budgeted formatter) + memory UI (view/edit/delete per scope) |

### Phase F — Artifacts

| Plan | Scope |
|------|-------|
| F1 | `artifacts` model over FileRevisions + create/update tools + serving route with sandbox/CSP/origin controls |
| F2 | Chat artifact cards (sandboxed preview, versions/diff) + share links with revocation + audit |

## 7. Open Decisions (Resolve During Plan Writing)

1. **First integration providers** — proposal: Google Mail (user OAuth),
   Google Ads or GA4 (workspace OAuth + discovery), Airtable (api_key +
   secret reference). Needs a product call.
2. **Embedding default** — OpenAI small vs local-first. Recommendation:
   OpenAI default, Ollama/BGE-M3 documented for self-hosters; provider
   ABC makes it cheap to defer.
3. **Contextual annotation default** — on or off per source type
   (costs one LLM pass per document at ingest). Recommendation: off for
   scratch/conversation sources, on for uploaded documents and URLs.
4. **Artifact origin in local dev** — separate port vs srcdoc-only.
   Recommendation: srcdoc + opaque-origin sandbox locally; separate
   origin required only when share links ship.
5. **Reranker** — interface now, implementation never until relevance
   complaints are real.
6. **MCP client support** — explicitly out of scope for all phases above;
   revisit once the native registry is stable.
