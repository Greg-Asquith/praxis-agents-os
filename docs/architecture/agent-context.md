<!-- docs/architecture/agent-context.md -->

# Agent Context Systems

How the four operator-facing context mechanisms — Skills, Files, the Knowledge
Base, and Memories — get information into an agent's context window, how they
differ, and when a new feature should build on each. A fifth mechanism,
conversation-summary compaction, is internal and included here only to keep it
from being confused with memory.

All prompt-side injection flows through the single system-prompt assembly
point in `apps/api/services/agents/runtime/prompt.py`; all tool-side access
flows through the runtime tool registry. New context sources should extend
those two seams rather than adding a third path.

For the non-technical version of this comparison, see
`docs/guides/skills-files-knowledge-memories.md`.

## At a glance

| | Skills | Files | Knowledge Base | Memories |
|---|---|---|---|---|
| Answers | "How do I do this task?" | "Work with this specific document" | "What does the workspace know?" | "What has the agent learned over time?" |
| Content | Procedural instructions + reference docs | Arbitrary documents with revision history | Canonical markdown, chunked and embedded | Durable facts with provenance |
| Storage | `skills` table; docs in object storage | `files` / `file_revisions` / `file_references` / `file_uploads`; content in object storage | `kb_documents` / `kb_chunks` (markdown in Postgres, `HALFVEC` embeddings) | Planned |
| Enters context via | Deferred capability catalog; instructions injected on `load_capability` | `available_files` prompt block + auto-mounted file tools + turn attachments | `knowledge` instruction prompt block + auto-mounted search tools | Planned: budgeted core-memory prompt block + tools |
| Retrieval | None | None | Hybrid RRF: lexical + pgvector semantic + recency | Planned (shares `services/retrieval/`) |
| Scope | Workspace rows, assigned per agent via `Agent.skill_ids` | Workspace; conversation visibility via `file_references` | Workspace-wide, with per-user private tier | Planned: per workspace/agent/user scope |
| Agent-writable | No | Yes (`write_file`; auto by default, approval configurable) | No (read tools only) | Planned |
| Status | Shipped end to end | Shipped end to end | Shipped end to end | Planned — not built |

## Skills

Reusable *procedural* knowledge: how an agent should perform a class of task.

- **Model.** `apps/api/models/skills.py`. A skill is `name`, `human_name`,
  `description`, full `instructions`, and a `documentation_refs` manifest for
  attached reference documents (original + converted markdown in object
  storage under `workspaces/{workspace_id}/skills/{skill_id}/`).
- **Runtime.** Three-level progressive disclosure. Skills assigned to the
  agent (`Agent.skill_ids`) become Pydantic AI capabilities with
  `defer_loading=True` (`services/agents/runtime/skills.py`): the model sees
  only `"{human_name}: {description}"` until it calls `load_capability`,
  which injects the full `instructions`. A conditional `read_skill_document`
  tool serves attached documents on demand, and refuses until the owning
  skill capability is loaded. Skills are *not* a system-prompt block.
- **Management.** `/skills` routes, `services/skills/`, web UI at `/skills`.
  Assigned to agents in the agent editor.
- **Lifecycle notes.** `load_capability` call/return pairs are preserved
  across history trimming so activated skills survive compaction.
  `last_used_at` is stamped on activation.

Use a skill when the content is *instructions the agent should follow* —
playbooks, formats, procedures — and only some agents should have it.

## Files

General-purpose document storage with revision history, and the mechanism for
handing an agent a specific document to work on.

- **Model.** `apps/api/models/files.py`: `files` (logical file),
  `file_revisions` (append-only, immutable), `file_references` (non-copying
  attachment to a conversation, artifact, agent, or schedule run), and
  `file_uploads` (signed two-phase upload staging). Non-markdown formats get
  background markdown extraction (job `files.extract`).
- **Runtime.** Three paths in:
  1. The `available_files` prompt block lists files referenced by the current
     conversation (capped and budgeted; see `core/settings/scratch.py`).
  2. Auto-mounted tools on every agent: `list_files`, `read_file` (returns
     images as native multimodal parts), and `write_file` (durable files;
     auto by default, approval configurable). Artifact drafting and
     versioning use `create_artifact`/`update_artifact`; the former
     scratch/promote tool workflow was retired with artifacts.
  3. Turn attachments: attached file content is spliced directly into the
     user prompt (`services/files/resolve_chat_attachments.py`).
- **Management.** `/files` routes, `services/files/`, web UI at `/files` with
  revisions, diffs, previews, and restore.
- **Scope note.** Attachment scopes what is *listed in the prompt*, but the
  file tools can reach any workspace file — attachment is salience, not a
  security boundary.
- **Relationship to Artifacts.** Separate aggregates, deliberately. Files are
  the workspace's document store — inputs and working material, inert bytes
  behind signed downloads. Artifacts are agent-authored deliverables that get
  *rendered*: the CSP-locked serving pipeline, sandboxed previews, and share
  links exist only for artifacts, which is why artifact tools are
  external-effect with an approval default while `write_file` is an internal
  write. The razor: content the user will view, present, or share → artifact;
  data or documents kept for reference and later work → file. An `.html` File
  is never served as a page; an `html` artifact is.

Use files when the unit of work is *a specific document* — read it, edit it,
produce it — rather than something the agent should find by searching.

## Knowledge Base

The workspace's searchable reference layer: canonical markdown that every
agent consults via retrieval.

- **Model.** `apps/api/models/kb.py`: `kb_documents` (canonical `content_md`
  in Postgres, `source_type ∈ {upload, url, manual, conversation,
  integration}`, `is_private`, optional pin to a `file_revision_id`) and
  `kb_chunks` (chunk text, LLM-generated `context_line`, `HALFVEC(1024)`
  embedding with HNSW index, generated `tsv`).
- **Ingestion.** `services/kb/create_document.py` → `ingest_kb_document` job:
  load markdown → hash + duplicate lock → write policy (secret scanning,
  backend-minted provenance) → chunk → annotate → `embed_kb_chunks` job.
- **Search.** `services/kb/search_chunks.py`: hybrid RRF over lexical
  (`websearch_to_tsquery`), semantic (pgvector cosine), and recency ranks,
  with lexical-only fallback when embeddings are unavailable. Settings in
  `core/settings/kb.py`.
- **Runtime.** A standing `knowledge` prompt block instructs agents to search
  the KB before answering, plus two auto-mounted read-only tools:
  `search_knowledge` and `read_document`
  (`services/agents/runtime/tools/kb.py`). Results are wrapped in the shared
  untrusted-content framing. There is deliberately no agent write tool yet.
- **Scope.** Workspace-wide — every agent searches the same KB. Private
  documents (`is_private`) are visible only to their creator, enforced in
  both the search SQL and document reads.
- **Relationship to Files.** Separate tables and UIs. Uploading a document to
  the KB through the web UI first creates a workspace File, then pins the KB
  document to that file revision; URL and manual KB documents have no File
  at all. A File is not searchable unless a KB document is created from it.

Use the KB when the content is *reference information any agent might need*
and the access pattern is "find the relevant part", not "process this
document".

## Memories (planned)

Durable, cross-conversation facts an agent accumulates. **Not built** — no
model, routes, tools, or UI exist yet. The planned design (see
`docs/plans/`): scoped `agent_memories` with backend-minted provenance,
dedup/reinforcement, read-time confidence decay and supersession, agent-facing
memory tools through the existing registry, and a budgeted core-memory block
rendered through the same prompt assembler. Until it ships, document
memory-like behavior as pending — do not imply agents remember anything
across conversations.

## Conversation summaries (compaction — not memory)

When a conversation's history is trimmed (`services/agents/runtime/history.py`),
a background job summarizes the trimmed span with a small model and the
summary is injected as a synthetic user message at the trim watermark
(`conversation_summaries` table and `services/conversation_summaries/`).
This is per-conversation, derived, and has no user surface. It keeps long
conversations coherent; it does not persist anything across conversations and
should never be described as memory.

## Choosing a home for new context

- Instructions on *how to act*, selectively assigned → **Skill**.
- A durable uploaded or generated document to read or edit → **File**.
- A versioned agent-authored report, page, diagram, or table the user will
  view, present, or share → **Artifact**.
- Reference material found by search, shared workspace-wide → **KB document**.
- Something learned that should persist across conversations → **Memory**
  (blocked until the memory vertical ships; do not bolt lookalikes onto the
  other three in the meantime).
