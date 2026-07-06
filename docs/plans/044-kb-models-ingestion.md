# Plan 044: KB models and ingestion pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Gate G3 pre-flight (run before Step 1)**: Gate G3 is satisfied —
> `docs/architecture/governance.md` exists (2026-07-06, plan 029 DONE).
> Re-verify the sections this plan implements: §3 Retention row "KB
> documents/chunks/embeddings (044) | ✓ | 30 d after doc hard-delete;
> chunks/vectors cascade immediately with doc | ✓ audit survives | export
> markdown" (governance.md:87), §1 "Create/edit KB documents (044/046)"
> EDITOR row (governance.md:43), and §6 job-failure notification law
> (governance.md:143). The note wins over this plan; flip the §3 KB cell to
> `[implemented: plan 044]` in the same PR.
>
> **Sibling-contract pre-flight**: this plan is written in parallel with
> plans 030–033 against a dictated contract. Before Step 1, verify the 030
> harness exists as contracted: `services/jobs/` with `enqueue_job` and
> `@job_handler(kind=...)`, handlers idempotent, initiator notified only
> after the final retry. If 030 has not landed, this is a hard STOP.
>
> **Drift check (run first)**:
> `git diff --stat 0cbbb39..HEAD -- apps/api/models/ apps/api/alembic/versions/core/ apps/api/core/settings/ apps/api/services/jobs/ apps/api/services/embeddings/ apps/api/services/skills/documents/ apps/api/services/conversations/naming.py apps/api/pyproject.toml docker-compose.yml`
> Changes under `services/jobs/` and `services/embeddings/` are EXPECTED
> (plans 030/043 land first); verify they match the contracted shapes named
> in "Current state". For any other in-scope file, compare the excerpts
> against live code; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (first pgvector consumer — the halfvec/HNSW DDL and the
  generated tsvector columns are hand-written migration surface; URL
  ingestion fetches user-supplied URLs from the server and must be
  SSRF-hardened)
- **Depends on**: **hard**: 030 (jobs harness — the pipeline is job
  handlers), 043 (embeddings service — `embed_texts` + usage metering),
  031 (`file_revisions` table — `kb_documents.file_revision_id` FK).
  **Soft**: 033 (upload-source ingestion consumes 033's `files.extract`
  markdown; until it lands, upload sources are rejected with a clear
  error — decision 3). Gate G3 satisfied (pre-flight above). Gate G4 note:
  no retrieval tuning happens in this plan; the eval harness lands in 045.
- **Category**: Phase 4b knowledge base (roadmap `000_MASTER_ROADMAP.md`
  §4 Phase 4b row 044; donor `DONOR_PORT_ROADMAP.md` §4.4 tables +
  ingestion / §6 row D2)
- **Planned at**: commit `0cbbb39`, 2026-07-06

## Decisions taken

**2026-07-06 OKF compatibility amendment (roadmap §2 decision D9).**
Praxis owns the KB runtime:
Postgres storage, indexing, permissions, jobs, audit, retention, and
agent behavior stay local and provider-neutral. Open Knowledge Format is
the compatibility shape for markdown/frontmatter, stable concept
identifiers, and import/export. Google Knowledge Catalog is a possible
future integration/source/sink, not a dependency of the KB substrate.
This amends the model shape below with `concept_id` and OKF metadata
fields while keeping the two-table owned storage design.

1. **Two tables, exactly as the donor design prescribes**
   (`DONOR_PORT_ROADMAP.md:280-292`): `kb_documents` (workspace-scoped,
   soft-delete `BaseModel`) and `kb_chunks` (`Base + UUIDMixin +
   TimestampMixin`, NO soft delete — chunks live and die with their
   document via `ondelete="CASCADE"`, mirroring plan 030's decision that
   operational rows don't soft-delete). Soft-deleting a doc makes its
   chunks unsearchable through the join predicate (045); hard delete
   cascades the chunk rows and their vectors immediately — implementing
   governance §3 "chunks/vectors cascade immediately with doc".
2. **The vector column is typed `HALFVEC(1024)` with HNSW from day one.**
   Probed 2026-07-06: the compose Postgres (`pgvector/pgvector:pg17`,
   docker-compose.yml:15) reports pgvector **0.8.1** (live
   `pg_available_extensions` query) — halfvec (≥0.7) and
   `hnsw.iterative_scan` (≥0.8) both supported. The `pgvector` Python
   package is NOT yet installed; this plan adds `pgvector>=0.4` to
   `pyproject.toml` (probed: 0.4.2 exposes
   `pgvector.sqlalchemy.HALFVEC`). Dimensions are pinned at **1024** —
   plan 043's default — and this table IS one collection: every embedded
   chunk is stamped with `embedding_provider`/`embedding_model`/
   `embedding_dims`, and the embed handler refuses to write a vector
   whose dims ≠ 1024 or whose model differs from already-stamped rows'
   expectations (never mix in one collection; changing model/dims means a
   new column + full re-embed, recorded in Maintenance notes).
3. **Dependency posture for sources** (resolving the dictated open
   point): 031 is a **hard** dependency because the migration declares the
   `file_revision_id` FK against `file_revisions`; 033 is **soft** —
   `manual` and `url` sources are fully functional without it, so this
   plan ships with `create_kb_document` rejecting `source_type="upload"`
   (typed `AppValidationError`, message naming file processing as
   pending) until the 033 markdown seam exists. The seam is one function,
   `get_revision_markdown(db, file_revision_id) -> str` in
   `services/kb/utils.py`, stubbed to raise until 033 lands; 046 (document
   sources surface) wires it for real. `conversation` and `integration`
   source types are accepted as *values* (CHECK constraint includes them)
   but have no producer until 046/041 — honest pending, not implied.
4. **Contextual annotation defaults: ON for `upload` and `url`, OFF for
   `manual`, `conversation`, and `integration`** — resolving the roadmap
   open decision (`000_MASTER_ROADMAP.md` §2 "contextual-annotation
   default"; donor §7.3 recommendation confirmed and extended: `manual`
   is user-curated text and `integration` rows are already structured, so
   neither benefits enough to pay one LLM pass per chunk). Stored as
   `annotation_enabled` resolved at creation time from source type, with
   an explicit per-document override parameter. Annotation prepends a
   50–100-token document-context line per chunk before embedding AND
   lexical indexing (the tsv generated column covers `context_line` +
   `content`), Anthropic contextual-retrieval style. Failures degrade:
   an annotation error logs and leaves that chunk un-annotated; it never
   fails ingestion.
5. **Chunk `content` is the exact source substring; context lines are a
   separate column.** Pinned invariant:
   `content_md[chunk.char_start:chunk.char_end] == chunk.content` for
   every chunk. The annotation line lives in `context_line` and is
   composed into the embedding input and the tsvector, never spliced into
   `content` — keeping offsets honest for 045's read/citation surface and
   making re-annotation cheap.
6. **Token counting is a chars//4 heuristic, no tokenizer dependency.**
   `tiktoken` is not installed (probed) and exact token counts buy
   nothing here — chunk bounds are targets, not contracts. Target 600
   estimated tokens, max 800, overlap 80 (~13%, inside the dictated
   10–15% band), all settings-tunable. Recorded so nobody "fixes" this
   with a heavyweight tokenizer later without a reason.
7. **The document is `ready` when its chunks are lexically searchable;
   embedding fills in asynchronously.** `kb.ingest_document` writes
   chunks (tsv is a generated column, so lexical search works the moment
   rows commit), sets `status='ready'`, then enqueues `kb.embed_chunks`.
   Chunk-level "pending embedding" is simply `embedding IS NULL` — this
   is precisely what makes 045's pending-embedding lexical fallback real
   rather than aspirational. Document status machine:
   `pending → processing → ready | error` with `processing_error` +
   `processing_attempts` retry columns; the jobs harness owns retry
   scheduling, the doc row records last-known state for the UI (047).
8. **Job kinds registered here** (the dictated 030 contract):
   `kb.ingest_document` (fetch/extract → markdown → chunk → annotate),
   `kb.embed_chunks` (embed WHERE embedding IS NULL — idempotent by
   construction), and the sweep kind `kb.sweep_deleted` (plan 030
   decision 6 assigns 044 one sweep kind; hard-deletes docs soft-deleted
   >30 d ago per governance §3, chunks cascade). All handlers are
   idempotent — stale reclaim means at-least-once execution: ingest
   replaces chunks transactionally (delete-then-insert keyed by
   document_id), embed only fills NULLs, sweep is a bounded DELETE.
   `ensure_kb_sweep_job` is called from `create_kb_document` and
   `delete_kb_document` (cheap — 030's in-flight dedup index makes it
   idempotent); the KB does not touch 030's worker loop.
9. **URL ingestion is SSRF-hardened, not just fetched.** The fetch helper
   allows only `http`/`https`, resolves DNS and rejects loopback,
   private, link-local, and unique-local addresses (`ipaddress` checks on
   every resolved address), caps redirects (3) and body size
   (`KB_URL_MAX_BYTES`, streamed with early abort), enforces a timeout,
   and sends no credentials. It uses a plain `httpx.AsyncClient` — NOT
   `retrying_http_client()`, which is the LLM-provider transport with
   provider-tuned retry semantics; retrying a user URL is the jobs
   harness's business. HTML converts to markdown via a single-call
   markitdown helper in `services/kb/utils.py` (the
   `services/skills/documents/utils.py:154-163` `_convert_sync` shape,
   copied per plan 030's "copy the tiny helper, do not import across
   service packages" precedent — this is one function call into the same
   installed library, not a second conversion pipeline; 033's shared
   extraction module supersedes it when it lands, see Maintenance notes).
10. **Canonical markdown lives on the document row** (`content_md` Text,
    capped by `KB_MAX_DOCUMENT_BYTES`, reusing the
    `truncate_markdown` UTF-8-boundary pattern from
    `services/skills/documents/utils.py:166-180`). It feeds chunk
    offsets (decision 5), the 045 `read_document` route, and the
    governance §3 markdown export path. Upload originals stay in Files
    (031/033); the KB never stores blobs. The doc-level tsvector covers
    `title + summary` only (the chunk tsv is the retrieval surface;
    a full-document tsvector risks the 1 MB tsvector size ceiling and
    buys nothing 045 needs) — recorded because the donor design says
    "tsvector column" on documents without specifying its source.
11. **No content-hash uniqueness constraint; `content_hash` is for change
    detection.** Re-ingesting a doc whose fetched/extracted markdown
    hashes identically to the stored `content_hash` short-circuits
    (chunks kept, status `ready`) — cheap idempotency for URL re-crawls.
    Duplicate documents across rows are allowed (two users may
    legitimately add the same URL); dedup-at-create is a 046 product
    decision, not a schema constraint here.
12. **The annotation model rides the utility-model pattern, not the agent
    runtime.** A one-shot structured-output `Agent` per chunk, exactly
    the `services/conversations/naming.py:50-71` shape
    (`build_model(resolve(...))` + `output_type`), with new settings
    `KB_ANNOTATION_PROVIDER`/`KB_ANNOTATION_MODEL` (defaults
    `openai`/`gpt-5.4-nano`, the naming-tier precedent from
    `core/settings/models.py:35-42`). One call per chunk with the full
    document in the prompt (prompt-cache-friendly ordering: document
    first, chunk last), bounded by `KB_ANNOTATION_MAX_CHUNKS` (200) —
    documents beyond the cap get their remaining chunks un-annotated
    with one WARNING. Live calls are blocked in tests by
    `pydantic_ai_models.ALLOW_MODEL_REQUESTS = False`
    (`tests/conftest.py:24`) — annotation tests use pydantic-ai
    `TestModel`/`FunctionModel` via the injectable `model` parameter.

## Why this matters

This is the knowledge base's foundation slice: the two tables everything
in Phase 4b/5 reads, and the pipeline that fills them. The donor's KB
post-mortem is the cautionary tale this plan exists to answer
(`DONOR_PORT_ROADMAP.md:273-279`): it never chunked (12k-char
truncation), never had a typed vector column (so HNSW was impossible and
every semantic query was a seq scan), and bookkept sources three ways.
Getting `halfvec(1024)` + HNSW + generated tsvectors into the *first*
migration, chunking with honest offsets, and running every step through
the 030 jobs harness means 045 (search + Gate G4 evals), 046 (agent
tools), 047 (UI), and 048 (memory reuses the embedding/collection
discipline) all build on schema that never needs a rescue migration. The
ingestion decisions here — annotation defaults, ready-on-lexical,
idempotent handlers — are exactly the ones that are cheap now and
politically expensive to change once real workspace corpora exist.

## Current state

Verified at `0cbbb39` unless marked as a sibling contract:

- **pgvector**: extension enabled since the first core migration
  (`alembic/versions/core/0001_create_core_schema.py:28`,
  `CREATE EXTENSION IF NOT EXISTS "vector"`); zero consumers — no vector
  column exists anywhere in `models/` (grep verified). Server: compose
  runs `pgvector/pgvector:pg17` (docker-compose.yml:15); live probe of
  the running container reports extension version **0.8.1**
  (`SELECT default_version, installed_version FROM
  pg_available_extensions WHERE name='vector'`). Python:
  `pgvector` absent from `pyproject.toml` dependencies (lines 8–25);
  probed `pgvector==0.4.2` installs cleanly and exposes
  `pgvector.sqlalchemy.Vector` and `pgvector.sqlalchemy.HALFVEC`.
- **No tsvector precedent**: grep for `TSVECTOR|tsvector` across
  `models/` and `alembic/versions/` returns nothing — the generated
  columns and GIN indexes in Step 2 are the first, hence hand-written.
- `apps/api/models/base.py`: `UUIDMixin` (18), `TimestampMixin` (24),
  soft-delete `BaseModel` (130). Register new models in
  `models/__init__.py` (registry comment, lines 1–12). Index style
  precedent: `models/agent.py:222-249` (`__table_args__` with partial
  indexes).
- Migrations: core head `core_0008`
  (`0008_add_conversation_todos.py:16`); 030 (jobs) and 031/032 (files)
  will consume numbers first — renumber at execution. D5: core branch.
- **030 contract** (sibling, verify at pre-flight): `services/jobs/`
  with `enqueue_job(db, *, kind, workspace_id=..., subject_type=...,
  subject_id=..., payload=..., initiated_by_user_id=...)`,
  `@job_handler(kind=..., timeout=...)` decorator registering into
  `JOB_HANDLERS` at the `services.jobs.handlers` assembly point,
  in-flight dedup on (kind, subject, content_hash), notification to the
  initiator only after the final retry (governance §6), and the
  self-rescheduling sweep pattern (`jobs.sweep_terminal` +
  `ensure_sweep_job`) that `kb.sweep_deleted` copies.
- **043 contract** (sibling, verify at pre-flight):
  `services/embeddings/embed_texts(db, texts, *, workspace_id,
  provider=None) -> EmbeddingBatch` with per-workspace token metering
  built in; `EmbeddingBatch` carries `provider`/`model`/`dimensions` to
  stamp; `tests/support/embeddings.py` `FakeEmbeddingProvider`
  (deterministic bag-of-words vectors) for every KB test that embeds.
- **031 contract** (sibling): `file_revisions` table with UUID `id`,
  immutable rows — the `kb_documents.file_revision_id` FK target.
- Markdown conversion machinery (017):
  `services/skills/documents/utils.py:134-163`
  `convert_document_to_markdown`/`_convert_sync` (markitdown
  `convert_stream`), `truncate_markdown` (166–180). `markitdown` with
  docx/pdf/pptx/xlsx extras is already a main dependency
  (pyproject.toml:15).
- Utility-LLM precedent: `services/conversations/naming.py:50-71` —
  one-shot `Agent` with `output_type`, model resolved via
  `resolve_naming_model()` (`services/agents/models/resolution.py:73`)
  and built by `build_model`; settings pair at
  `core/settings/models.py:35-42`.
- Settings composition: mixins in `core/settings/__init__.py:30-46`.
- Exceptions: `AppValidationError` (`core/exceptions/general.py:16`),
  `NotFoundError` (52), `ConflictError` (91) — RFC 7807 mapped.
- Tests: `TEST_DATABASE_URL` gating via `require_test_database_url`
  (`tests/support/database.py:13-23`); rollback-per-test fixtures
  (`tests/conftest.py:105-174`); live LLM calls blocked at
  `tests/conftest.py:24`; factories under `tests/factories/`
  (`workspaces.py`, `users.py` exist — `kb.py` joins them).
- Will exist after later plans (do not assume now): search/read routes +
  eval harness (045), agent tools + write-policy choke point + document
  source routes (046), KB UI (047).

## Commands you will need

| Purpose | Command (from `apps/api`) | Expected on success |
|---------|---------------------------|---------------------|
| Add dependency | `uv add "pgvector>=0.4"` | pyproject + lock updated |
| Lint | `uv run ruff check .` | exit 0 |
| Migration sanity | `uv run alembic check` | no pending operations after Step 2 |
| Apply migration | `uv run alembic upgrade heads` | `kb_documents`, `kb_chunks` created |
| Server version guard | `docker exec <pg-container> psql -U postgres -tc "SELECT installed_version FROM pg_available_extensions WHERE name='vector'"` | ≥ 0.8 (0.8.1 at planning) |
| Index guard | `docker exec <pg-container> psql -U postgres -c "\d kb_chunks"` after upgrade | `hnsw (embedding halfvec_cosine_ops)` + two GIN indexes listed |
| New tests | `TEST_DATABASE_URL=... uv run pytest tests/services/kb -q` | all pass; skip without env var |
| Jobs regression | `TEST_DATABASE_URL=... uv run pytest tests/services/jobs -q` | still green |
| Worker smoke | `uv run python -m workers.job_runner --once` | exit 0; kb kinds registered |

## Scope

**In scope:**

- `apps/api/pyproject.toml` (add `pgvector>=0.4`)
- `apps/api/models/kb.py` (create — `KBDocument`, `KBChunk`) +
  `apps/api/models/__init__.py` (register imports)
- `apps/api/alembic/versions/core/00XX_*.py` (create — core branch, D5;
  hand-written HNSW/GIN/generated-column DDL)
- `apps/api/core/settings/kb.py` (create — `KBSettingsMixin`) +
  `apps/api/core/settings/__init__.py` (compose it)
- `apps/api/services/kb/` (create): `__init__.py`, `domain.py`,
  `chunking.py`, `annotation.py`, `utils.py`, `create_document.py`,
  `delete_document.py`, `handlers/__init__.py`,
  `handlers/ingest_document.py`, `handlers/embed_chunks.py`,
  `handlers/sweep_deleted_documents.py`
- Registration of the three job kinds at 030's
  `services.jobs.handlers` assembly point (one import line there)
- `apps/api/tests/services/kb/` (create), `apps/api/tests/factories/kb.py`
  (create)

**Out of scope (do NOT touch):**

- HTTP routes of any kind — search/read are 045; document-source create
  routes are 046. The KB has **no public surface** in this plan; per
  AGENTS.md, document it as pending. `create_kb_document` is a service
  function with exactly two callers today: tests and (later) 046.
- Search SQL, RRF, rerankers, `hnsw.iterative_scan` session tuning — 045.
- The write-policy choke point (provenance rules, private-never-shared
  enforcement, secret blocking) — 046. This plan stores `is_private`
  faithfully; it does not yet arbitrate it.
- Agent tools, prompt blocks, UI — 046/047.
- `services/jobs/` internals and `services/embeddings/` internals — you
  register handlers and call `embed_texts`; you do not modify the
  substrates.
- Memory tables — 048.
- Upload-source ingestion beyond the rejection + seam stub (decision 3).

## Git workflow

- Branch: `advisor/044-kb-models-ingestion`
- Commit style: `API - KB Models & Ingestion Pipeline`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Dependency + settings

`uv add "pgvector>=0.4"`. Create `core/settings/kb.py` with
`KBSettingsMixin` (all `Field(..., description=...)` with bounds):

```python
KB_CHUNK_TARGET_TOKENS: int = 600        # greedy pack target (chars//4 heuristic, decision 6)
KB_CHUNK_MAX_TOKENS: int = 800           # hard per-chunk cap
KB_CHUNK_OVERLAP_TOKENS: int = 80        # ~13% trailing overlap
KB_MAX_DOCUMENT_BYTES: int = 2_000_000   # canonical markdown cap (truncate, decision 10)
KB_URL_FETCH_TIMEOUT_SECONDS: float = 30.0
KB_URL_MAX_BYTES: int = 5_000_000        # streamed fetch abort threshold
KB_URL_MAX_REDIRECTS: int = 3
KB_ANNOTATION_PROVIDER: str = "openai"   # utility-model pattern (decision 12)
KB_ANNOTATION_MODEL: str = "gpt-5.4-nano"
KB_ANNOTATION_MAX_CHUNKS: int = 200
KB_SWEEP_INTERVAL_SECONDS: int = 3600
KB_DELETED_RETENTION_DAYS: int = 30      # governance §3 KB row
```

Compose into `Settings` (`core/settings/__init__.py:30-46`). No
production-validator change (no local-only values).

**Verify**: `uv run python -c "from core.settings import settings; print(settings.KB_CHUNK_TARGET_TOKENS, settings.KB_DELETED_RETENTION_DAYS)"`
→ `600 30`; `uv run python -c "from pgvector.sqlalchemy import HALFVEC; print('ok')"`
→ `ok`; ruff exit 0.

### Step 2: Models + core migration (the hand-written DDL step)

`models/kb.py`. `KBDocument(BaseModel)` (soft-delete — governance §3),
`__tablename__ = "kb_documents"`:

- `workspace_id` UUID FK `workspaces.id`, not null, indexed
- `title` String(500) not null
- `concept_id` String(512) nullable, indexed — stable OKF-compatible
  concept identifier/path when the document comes from an OKF bundle or
  is later exported as one
- `source_type` String(32) not null, CHECK in
  `('upload','url','manual','conversation','integration')`
- `status` String(16) not null, server_default `'pending'`, CHECK in
  `('pending','processing','ready','error')`
- `processing_error` Text nullable; `processing_attempts` Integer not
  null, server_default `0` (decision 7 retry columns)
- `content_hash` String(64) not null, server_default `''` (decision 11)
- `content_md` Text nullable (decision 10); `summary` Text nullable
- `file_revision_id` UUID FK `file_revisions.id`, nullable,
  `ondelete="SET NULL"` (uploads ride Files; deleting the file must not
  orphan-break the doc row)
- `external_id` String(255) nullable; `external_url` Text nullable
- `is_private` Boolean not null, server_default `false`
- `created_by_user_id` UUID FK `users.id`, nullable,
  `ondelete="SET NULL"` (agent/system provenance arrives with 046's
  choke point)
- `annotation_enabled` Boolean not null (decision 4)
- `chunk_count` Integer not null, server_default `0`
- `meta` JSONB not null, server_default `'{}'::jsonb` — includes
  preserved OKF frontmatter keys not promoted to first-class columns
- `tsv` TSVECTOR, generated (decision 10 — title+summary only)

`KBChunk(Base, UUIDMixin, TimestampMixin)` (no soft delete, decision 1),
`__tablename__ = "kb_chunks"`:

- `document_id` UUID FK `kb_documents.id`, not null,
  `ondelete="CASCADE"`
- `workspace_id` UUID FK `workspaces.id`, not null, indexed —
  deliberately denormalized so 045's per-CTE filters never join for the
  hot predicate
- `chunk_index` Integer not null;
  `UniqueConstraint("document_id", "chunk_index")`
- `content` Text not null (exact substring, decision 5)
- `context_line` Text nullable (decision 4/5)
- `char_start` Integer not null; `char_end` Integer not null; CHECK
  `char_end > char_start`
- `token_estimate` Integer not null
- `embedding` `HALFVEC(1024)` nullable (`from pgvector.sqlalchemy import
  HALFVEC`) — NULL means pending embedding (decision 7)
- `embedding_provider` String(32) nullable; `embedding_model`
  String(128) nullable; `embedding_dims` Integer nullable — stamped
  together with the vector, all-or-none (decision 2)
- `tsv` TSVECTOR, generated
- `meta` JSONB not null, server_default `'{}'::jsonb` (heading path etc.)

Generate the migration on the core branch
(`uv run alembic revision --autogenerate --head core@head --version-path
alembic/versions/core -m "add kb documents and chunks"`, renumbered
against the real head), then **hand-write** what autogenerate cannot
produce, with exact matching `downgrade` drops:

```python
# upgrade(), after the autogenerated create_table calls:
op.execute("""
    ALTER TABLE kb_documents ADD COLUMN tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, ''))
    ) STORED
""")
op.execute("""
    ALTER TABLE kb_chunks ADD COLUMN tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(context_line, '') || ' ' || content)
    ) STORED
""")
op.execute("CREATE INDEX ix_kb_documents_tsv ON kb_documents USING gin (tsv)")
op.execute("CREATE INDEX ix_kb_chunks_tsv ON kb_chunks USING gin (tsv)")
op.execute("""
    CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks
    USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64)
""")
```

(Declare the `tsv` columns in the models with
`mapped_column(TSVECTOR, sa.Computed("...", persisted=True))` mirroring
the same expressions so `alembic check` stays clean — verify it reports
no pending operations; if the Computed round-trip fights autogenerate,
prefer raw DDL in the migration + `exclude` via the model using
`FetchedValue`, and record which route was taken.) Also add btree
indexes: `(workspace_id, status)` on documents (047's list surface),
`(document_id, chunk_index)` is covered by the unique constraint, and a
partial `(document_id) WHERE embedding IS NULL` on chunks (the embed
handler's scan). `halfvec_cosine_ops` is the cosine opclass this
collection standardizes on — 045's `<=>` operator hits exactly this
index.

Import both models in `models/__init__.py`.

**Verify**: `uv run alembic upgrade heads` clean; the Index-guard `\d
kb_chunks` shows the HNSW and GIN indexes; downgrade round-trips;
`uv run alembic check` → no pending operations.

### Step 3: Domain + chunker

`services/kb/domain.py`: status/source-type constants
(`KB_STATUS_PENDING = "pending"`, …, `KB_SOURCE_UPLOAD = "upload"`, …),
`ANNOTATION_DEFAULTS: dict[str, bool]` (decision 4),
`KB_COLLECTION_DIMS = 1024`, and a frozen `ChunkDraft` dataclass
(`chunk_index, content, char_start, char_end, token_estimate,
heading_path: tuple[str, ...]`).

`services/kb/chunking.py` — `chunk_markdown(content_md, *,
target_tokens, max_tokens, overlap_tokens) -> list[ChunkDraft]`, pure
and deterministic. Algorithm (spec, implement exactly):

1. **Block scan**: split the document into blocks with char offsets —
   ATX headings (`^#{1,6} `), fenced code blocks (``` … ``` — a fence
   is ONE block, never split), and paragraphs (blank-line separated).
   Maintain a heading-path stack (e.g. `("Setup", "VPN")`) updated at
   each heading block.
2. **Greedy pack**: accumulate consecutive blocks into a chunk while
   `estimate(chunk) <= target_tokens` where
   `estimate(text) = len(text) // 4` (decision 6); close the chunk
   before exceeding `max_tokens`.
3. **Oversized block**: a single block over `max_tokens` is split on
   sentence boundaries (`. `, `? `, `! `, newline) into max-sized
   pieces; a boundary-free run is hard-split at `max_tokens * 4` chars.
   Fenced blocks are exempt from sentence splitting — hard-split only.
4. **Overlap**: each chunk after the first extends its `char_start`
   backwards to include the previous chunk's trailing whole blocks (or
   sentences) up to `overlap_tokens` — overlap is expressed purely
   through the offsets, so the decision-5 substring invariant holds:
   `content == content_md[char_start:char_end]` always.
5. Emit `ChunkDraft`s with `heading_path` (stored into `meta["headings"]`
   at insert). Empty/whitespace documents → `[]`.

`services/kb/utils.py`: `estimate_tokens(text)`,
`compute_markdown_hash(text)` (sha256 hex),
`convert_html_to_markdown(data: bytes) -> str` (single markitdown call,
decision 9), `truncate_markdown` (copy of the
`skills/documents/utils.py:166-180` boundary-safe cap — plan 030's
copy-small-helpers rule), `fetch_url(url) -> tuple[bytes, str]` (the
SSRF-hardened fetch, decision 9: scheme allowlist, per-resolution
`ipaddress` private/loopback/link-local rejection, redirect cap
re-validating each hop, streamed size cap, timeout, returns body +
content type), and the 033 seam stub
`get_revision_markdown(db, file_revision_id)` (raises
`AppValidationError` "file-derived ingestion pending file processing"
until 033 — decision 3).

**Verify**: `uv run pytest tests/services/kb/test_chunking.py -q` (after
Step 7 exists; during development, ruff + a REPL spot-check of the
substring invariant on this plan file's own markdown).

### Step 4: Create/delete service ops

`services/kb/create_document.py` — `create_kb_document(db, *,
workspace_id, source_type, title, created_by_user_id=None, content=None,
url=None, file_revision_id=None, is_private=False, annotate=None,
meta=None) -> KBDocument`:

- Validate per source type: `manual` requires non-empty `content`;
  `url` requires a syntactically valid http(s) `url` (stored to
  `external_url`; the fetch happens in the job, not the request path);
  `upload` → rejected until 033 (decision 3); `conversation`/
  `integration` → rejected with "producer pending 046/041" (honest
  pending). Unknown source type → `AppValidationError`.
- Resolve `annotation_enabled` from `ANNOTATION_DEFAULTS[source_type]`
  unless `annotate` is explicitly passed (decision 4).
- Insert the doc (`status='pending'`; for `manual`, store
  `content_md=truncate_markdown(content)` and its hash immediately).
- Enqueue `enqueue_job(db, kind="kb.ingest_document",
  workspace_id=workspace_id, subject_type="kb_document",
  subject_id=doc.id, initiated_by_user_id=created_by_user_id)` — 030's
  in-flight dedup makes double-create-clicks collapse.
- Call `ensure_kb_sweep_job(db)` (decision 8).

`services/kb/delete_document.py` — `delete_kb_document(db, *,
workspace_id, document_id, deleted_by=None)`: workspace-scoped lookup
(`NotFoundError` on miss or cross-workspace), `soft_delete()` on the doc
(chunk rows stay until the sweep hard-deletes and cascades — search
excludes them via the doc join from day one in 045), then
`ensure_kb_sweep_job(db)`.

`services/kb/__init__.py` re-exports operation functions only.

**Verify**: ruff exit 0; `uv run pytest tests/services/jobs -q` still
green (nothing harness-side touched).

### Step 5: The ingest handler

`services/kb/handlers/ingest_document.py`:

```python
@job_handler(kind="kb.ingest_document", timeout=600.0)
async def ingest_document(db, job) -> None:
```

1. Load the doc by `job.subject_id`; missing or soft-deleted → return
   (idempotent no-op, not an error — the doc may have been deleted while
   queued).
2. `status='processing'`, `processing_attempts += 1`, commit-visible
   early so 047 can show progress later.
3. Obtain markdown by source: `manual` → stored `content_md`; `url` →
   `fetch_url` + `convert_html_to_markdown` (non-HTML content types with
   a markitdown-supported extension convert too; anything else →
   failure) + `truncate_markdown`; `upload` → `get_revision_markdown`
   seam (raises until 033).
4. `compute_markdown_hash`; if it equals the stored `content_hash` AND
   `status`-history shows chunks exist (`chunk_count > 0`) → set
   `ready` and return (decision 11 short-circuit).
5. Persist `content_md` + `content_hash`; delete existing chunks for the
   doc; run `chunk_markdown`; bulk-insert `KBChunk` rows (embedding NULL,
   `meta={"headings": [...]}`); update `chunk_count`.
6. If `annotation_enabled`: `annotate_chunks` (Step 6) — degraded
   failures never raise past the helper (decision 4).
7. `status='ready'`, clear `processing_error`; enqueue
   `kb.embed_chunks` with `subject_type="kb_document"`,
   `subject_id=doc.id`, same initiator.

Failure path: any raise propagates to the 030 harness (bounded retries,
initiator notified only on final exhaustion — governance §6); before
re-raising, stamp `status='error'` + `processing_error` (1000-char cap,
the harness's sanitize convention) in a fresh nested transaction so the
doc row reflects reality between retries. Re-runs are safe: step 5's
delete-then-insert is keyed by document_id (decision 8 idempotency).

**Verify**: `uv run python -m workers.job_runner --once` exits 0 and the
registry print
(`uv run python -c "from services.jobs.registry import JOB_HANDLERS; print(sorted(JOB_HANDLERS))"`)
includes `kb.embed_chunks`, `kb.ingest_document`, `kb.sweep_deleted`
(after Steps 5–6 and the handlers-package import line).

### Step 6: Annotation, embed handler, sweep

`services/kb/annotation.py` — `annotate_chunks(db, *, document,
chunks, model=None) -> int` (returns annotated count; decision 12):
one-shot `Agent` with
`output_type=ChunkContext` (`context: str` field, description pinning
50–100 tokens), instructions template:

```
Locate the chunk within the document and write one 50-100 token line
situating it (document topic, section, what the chunk covers) to improve
search retrieval of the chunk. Answer only with the context line.
<document>{content_md}</document>
<chunk>{chunk.content}</chunk>
```

Document-first ordering keeps the long prefix cache-stable across a
document's chunks. Cap at `KB_ANNOTATION_MAX_CHUNKS`; per-chunk failure →
log WARNING, continue; write `context_line` per chunk (the generated tsv
picks it up automatically; embedding input in the embed handler is
`f"{context_line}\n\n{content}"` when present).

`services/kb/handlers/embed_chunks.py`:

```python
@job_handler(kind="kb.embed_chunks", timeout=600.0)
async def embed_chunks(db, job) -> None:
```

Select chunks `WHERE document_id = :id AND embedding IS NULL` ordered by
`chunk_index` (hits the Step 2 partial index); no rows → return
(idempotent). Guard the collection contract (decision 2): if
`settings.EMBEDDINGS_DIMENSIONS != KB_COLLECTION_DIMS`, raise a
configuration error (fail the job loudly rather than write a mixed
collection). Batch through 043's
`embed_texts(db, inputs, workspace_id=doc.workspace_id)` in slices of
the embeddings batch size; stamp `embedding`,
`embedding_provider/model/dims` from the returned `EmbeddingBatch` per
row, committing per slice so a mid-run crash resumes at the NULL
boundary. Usage metering is automatic inside `embed_texts` — do not
count tokens here.

`services/kb/handlers/sweep_deleted_documents.py` — the 030 sweep
pattern verbatim:

```python
@job_handler(kind="kb.sweep_deleted", timeout=120.0)
async def sweep_deleted_documents(db, job) -> None:
    # hard-delete kb_documents soft-deleted more than KB_DELETED_RETENTION_DAYS ago
    # (governance §3 KB row: 30 d); chunk rows + vectors cascade via FK (decision 1)
    # then self-reschedule: same kind, run_after = now + KB_SWEEP_INTERVAL_SECONDS
```

Plus `ensure_kb_sweep_job(db)` (same file — enqueue-if-absent, dedup
index makes it idempotent). Register all three handlers by importing the
`services.kb.handlers` modules from 030's `services.jobs.handlers`
assembly point (the one-line extension 030's registry comment invites).

**Verify**: registry print shows all three kb kinds;
`uv run python -m workers.job_runner --once` → exit 0.

### Step 7: Tests

`tests/services/kb/` (async modules set
`pytestmark = pytest.mark.asyncio`; DB tests skip without
`TEST_DATABASE_URL`; every embedding path injects
`FakeEmbeddingProvider` from `tests/support/embeddings.py`; annotation
tests pass `TestModel`/`FunctionModel`). `tests/factories/kb.py`:
`create_kb_document(...)`/`create_kb_chunk(...)` helpers.

- `test_chunking.py` (no DB, the largest module): substring invariant
  `content_md[start:end] == content` for every chunk over a fixture doc
  with headings/fences/long paragraphs; no chunk exceeds max tokens;
  fenced block never split at a non-hard boundary; overlap present and
  within ~10–15% band; heading paths correct; empty doc → `[]`;
  single-oversized-paragraph doc splits on sentences; determinism (two
  runs identical).
- `test_create_document.py` (DB): manual happy path stores content+hash
  and enqueues `kb.ingest_document`; url stores `external_url` without
  fetching; upload rejected pending 033; conversation/integration
  rejected pending producers; annotation defaults per source type and
  explicit override; invalid url rejected.
- `test_fetch_url.py` (no DB, mocked transport + resolver): loopback,
  RFC 1918, link-local, and `::1` addresses rejected; `file://`
  rejected; redirect to a private address rejected; body over
  `KB_URL_MAX_BYTES` aborts; happy path returns bytes+content-type.
- `test_ingest_document.py` (DB): manual doc end-to-end — chunks
  inserted with offsets/tsv (assert a
  `tsv @@ websearch_to_tsquery(...)` SELECT finds a chunk: lexical
  works before any embedding, decision 7), doc `ready`, `chunk_count`
  set, `kb.embed_chunks` enqueued; re-run with unchanged hash
  short-circuits (chunk ids unchanged); re-run after content change
  replaces chunks; soft-deleted doc → no-op; failure stamps
  `status='error'` + `processing_error` and re-raises.
- `test_embed_chunks.py` (DB): fills only NULL embeddings; stamps
  provider/model/dims from the batch; second run no-ops; dims-mismatch
  settings → loud failure, nothing written; usage counter row incremented
  (via the 043 counter table).
- `test_annotation.py` (DB, FunctionModel): context lines written and
  picked up by the regenerated tsv; per-chunk model failure skips that
  chunk without failing ingestion; cap respected.
- `test_sweep_deleted.py` (DB): doc soft-deleted 31 d ago hard-deleted
  with its chunks (cascade verified by counting `kb_chunks`); fresh
  soft-delete kept; live docs untouched; handler re-enqueues itself;
  `ensure_kb_sweep_job` idempotent.

**Verify**:
`TEST_DATABASE_URL=... uv run pytest tests/services/kb tests/services/jobs tests/services/embeddings -q`
→ all pass; without the env var, DB modules skip.

## Test plan

Covered by Step 7 (~28–34 tests). The pinned invariants: **the substring
invariant** (`content_md[char_start:char_end] == content` — 045's
citations depend on it), **lexical-before-embedded** (a chunk is
tsv-searchable the moment ingest commits, embedding strictly additive —
the 045 fallback's foundation), **one collection, never mixed**
(provider/model/dims stamped all-or-none; dims guard fails loudly),
**at-least-once safety** (every handler re-runnable: replace-by-doc,
fill-NULLs-only, bounded sweep), and **no server-side request to a
private address** (SSRF suite).

## Done criteria

- [ ] `uv run ruff check .` exits 0; `pgvector>=0.4` in `pyproject.toml`
- [ ] `uv run alembic check` reports no pending operations; migration on
      the **core** branch (D5); downgrade round-trips; `\d kb_chunks`
      shows `hnsw (embedding halfvec_cosine_ops)` and the GIN indexes
- [ ] Server pgvector ≥ 0.8 verified at execution time (0.8.1 at
      planning) — the STOP guard actually ran
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/kb tests/services/jobs -q`
      exits 0; full `uv run pytest -q` green
- [ ] Registry print shows exactly three new kinds: `kb.embed_chunks`,
      `kb.ingest_document`, `kb.sweep_deleted`;
      `uv run python -m workers.job_runner --once` exits 0
- [ ] No routes package added; upload/conversation/integration sources
      reject with pending-plan messages (033/046/041 named)
- [ ] `docs/architecture/governance.md` §3 KB cell flipped to
      `[implemented: plan 044]` in the same change
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated (add the 044 row if
      absent)

## STOP conditions

Stop and report back (do not improvise) if:

- **Server pgvector < 0.8 or halfvec unsupported**: run the
  version-guard command first; if `installed_version` < 0.8 or
  `CREATE TABLE _probe (v halfvec(3))` fails in a scratch schema, stop —
  the compose image or a deployed environment has drifted from
  `pgvector/pgvector:pg17` (0.8.1 verified 2026-07-06).
- **030 is not implemented** (no `services/jobs/` with
  `enqueue_job`/`@job_handler`), or its contract shapes differ from the
  "Current state" description — the pipeline has nothing to ride.
- **043 is not implemented**, or `embed_texts` does not meter usage
  internally / does not return provider+model+dims — the collection
  stamping contract breaks.
- **An existing `kb_documents` or `kb_chunks` table, `models/kb.py`, or
  `services/kb/`** — someone started the vertical first.
- `file_revisions` does not exist at migration time (031 unlanded) —
  decision 3 made 031 hard; do not silently drop the FK.
- The generated tsvector columns cannot be expressed with your
  SQLAlchemy/Alembic versions without breaking `alembic check` — report
  the route taken rather than shipping a dirty autogenerate state.
- `tests/support/embeddings.py` (043's fake) is missing or
  non-deterministic — every KB test that embeds depends on it.
- You feel the need to add routes, search SQL, write-policy arbitration,
  or a second markdown-conversion pipeline — scope leaking in
  (045/046/033).

## Maintenance notes

- **Consumers**: 045 (hybrid search over `kb_chunks` — relies on the
  substring invariant, the `halfvec_cosine_ops` index, the tsv columns,
  the `embedding IS NULL` fallback semantics, and the soft-delete join
  predicate; its Gate G4 harness seeds through `create_kb_document` +
  the handlers, not raw inserts), 046 (agent tools + write-policy choke
  point + the real document-source routes; wires the
  `get_revision_markdown` seam and the conversation/integration
  producers), 047 (UI reads `status`/`processing_error`/`chunk_count`),
  048 (memory copies the collection-stamping discipline and reuses 043).
- **The 033 handoff**: when file processing lands, replace the
  `get_revision_markdown` stub with the real read of 033's `files.extract`
  output and delete `convert_html_to_markdown`'s skills-shaped twin if
  033 exports a shared helper (AGENTS.md: reusable helpers belong in
  top-level `apps/api/utils/`). The upload-source rejection in
  `create_document.py` comes out in the same change — 046 owns exposing
  it.
- **Collection migration**: changing embedding model or dims = add
  `embedding_v2 halfvec(N)` + new HNSW index, backfill via a new job
  kind, swap the search column, drop the old — never in-place. The
  dims guard in the embed handler is the tripwire that forces this
  conversation.
- **HNSW parameters** (`m=16, ef_construction=64`) are pgvector defaults
  written explicitly so tuning is a deliberate migration, not an
  accident. Query-side (`ef_search`, `iterative_scan`) tuning belongs to
  045 — and Gate G4 forbids touching it before 045's harness exists.
- **Retention coupling**: `KB_DELETED_RETENTION_DAYS` implements
  governance §3; changing it means updating governance.md, not just the
  setting.
- Reviewers should scrutinize: the migration's downgrade (drops every
  hand-written index/column), fence handling and the overlap-offset
  interaction in the chunker, the error-path nested transaction in the
  ingest handler (status stamping must survive the re-raise), the SSRF
  resolver checks (every redirect hop re-validated), and that no job
  payload carries document text (030's payload discipline — ids only).
