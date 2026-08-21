<!-- docs/architecture/agent-context.md -->

# Agent context systems

Praxis has four operator-facing context systems: Skills, Files, the Knowledge
Base, and Memories. This document explains how each system adds information to
an agent's context and where future features belong. It also distinguishes
internal conversation-summary compaction from memory.

All prompt-side injection flows through the single system-prompt assembly
point in `apps/api/services/agents/runtime/prompt.py`; all tool-side access
flows through the runtime tool registry. New context sources must extend
those two seams rather than adding a third path.

For an operator-focused comparison, see [Choose between skills, files, the
Knowledge Base, and memories](../guides/skills-files-knowledge-memories.md).

## At a glance

| Comparison         | Skills                                                                  | Files                                                                                      | Knowledge Base                                                            | Memories                                                                                            |
| ------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Answers            | "How do I do this task?"                                                | "Work with this specific document"                                                         | "What does the workspace know?"                                           | "What has the agent learned over time?"                                                             |
| Content            | Procedural instructions + reference docs                                | Arbitrary documents with revision history                                                  | Canonical markdown, chunked and embedded                                  | Durable facts with provenance                                                                       |
| Storage            | `skills` table; docs in object storage                                  | `files` / `file_revisions` / `file_references` / `file_uploads`; content in object storage | `kb_documents` / `kb_chunks` (markdown in Postgres, `HALFVEC` embeddings) | `agent_memories` (markdown in Postgres, `HALFVEC` embeddings)                                       |
| Enters context via | Deferred capability catalog; instructions injected on `load_capability` | `available_files` prompt block + auto-mounted file tools + turn attachments                | `knowledge` instruction prompt block + auto-mounted search tools          | Budgeted core-memory prompt block + auto-mounted memory tools                                       |
| Retrieval          | None                                                                    | None                                                                                       | Hybrid RRF: lexical + pgvector semantic + recency                         | Hybrid RRF with read-time confidence decay (shares `services/retrieval/`)                           |
| Scope              | Workspace rows, assigned per agent via `Agent.skill_ids`                | Workspace; conversation visibility via `file_references`                                   | Workspace-wide, with per-user private tier                                | Per workspace/agent/user scope                                                                      |
| Agent-writable     | No                                                                      | Yes (`write_file`; auto by default, approval configurable)                                 | No (read tools only)                                                      | Yes (`save_memory` / `update_memory` / `forget_memory`; core-memory writes always require approval) |
| Status             | Shipped end to end                                                      | Shipped end to end                                                                         | Shipped end to end                                                        | Shipped end to end                                                                                  |

## Skills

Reusable _procedural_ knowledge: how an agent should perform a class of task.

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
  skill capability is loaded. Skills are _not_ a system-prompt block.
- **Management.** `/skills` routes, `services/skills/`, web UI at `/skills`.
  Assigned to agents in the agent editor.
- **Lifecycle notes.** `load_capability` call/return pairs are preserved
  across history trimming so activated skills survive compaction.
  `last_used_at` is stamped on activation.

Use a skill for instructions that selected agents must follow, including
procedures and required formats.

## Files

General-purpose document storage with revision history, and the mechanism for
handing an agent a specific document to work on.

- **Model.** `apps/api/models/files.py`: `files` (logical file),
  `file_revisions` (append-only, immutable), `file_references` (non-copying
  attachment to a conversation, artifact, agent, or schedule run), and
  `file_uploads` (signed two-phase upload staging). Workspace-scoped
  `file_folders` provide optional, single-level organisation through
  `files.folder_id`; folders are not an authorization boundary. Non-markdown
  formats get background markdown extraction (job `files.extract`).
- **Runtime.** Three paths in:
  1. The `available_files` prompt block lists files referenced by the current
     conversation (capped and budgeted; see `core/settings/scratch.py`).
  2. Auto-mounted tools on every agent: `list_files`, `read_file` (returns
     images as native multimodal parts), and `write_file` (durable files;
     auto by default, approval configurable). File listing can be scoped by
     folder name and new writes can resolve or create an explicitly named
     folder. Provider-native `run_code` groups retained File outputs in one
     lazily created folder per conversation unless the agent names a folder;
     artifact-only runs do not create one. Generated Files retain a
     conversation reference so they appear in `available_files`. Artifact
     drafting and versioning use `create_artifact`/`update_artifact`.
  3. Turn attachments: attached file content is spliced directly into the
     user prompt (`services/files/resolve_chat_attachments.py`).
- **Management.** `/files` routes, `services/files/`, web UI at `/files` with
  root folder cards, folder-scoped search and upload, single/bulk move,
  delete-with-contents, revisions, diffs, previews, and restore. Deleting a
  folder uses the normal per-file soft-delete and audit lifecycle before the
  existing sweeper purges both files and old folder tombstones.
- **Scope note.** Attachment scopes what is _listed in the prompt_, but the
  file tools can reach any workspace file — attachment is salience, not a
  security boundary.
- **Relationship to Artifacts.** Separate aggregates, deliberately. Files are
  the workspace's document store — inputs and working material, inert bytes
  behind signed downloads. Artifacts are agent-authored deliverables that get
  _rendered_: the CSP-locked serving pipeline, sandboxed previews, and share
  links exist only for artifacts. `create_artifact` and `update_artifact` are
  auto-mounted on every agent and remain external-effect tools with an
  approval default, while `write_file` is an internal write. The razor:
  use an artifact for content that someone views, presents, or shares. Use a
  file for data or documents kept for reference and later work. An `.html`
  file is never served as
  a page; an `html` artifact is.

Use a file when the task reads, edits, or creates a specific document. Use the
Knowledge Base when the agent must find information by searching.

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

Use the Knowledge Base for reference information that any agent might need to
find. Use a file when the agent must process a specific document.

## Memories

Durable, cross-conversation facts associated with a user, agent, or workspace.

- **Model.** `apps/api/models/agent_memories.py`: scoped `agent_memories` rows
  (`scope ∈ {agent, user, workspace}`, `kind ∈ {core, note}`) with
  backend-minted provenance (source conversation/run, creator), reinforcement
  counters, expiry, and supersession links. Content is markdown in Postgres
  with `HALFVEC` embeddings.
- **Runtime.** The backend deduplicates and reinforces matching facts, applies
  confidence decay and supersession at read time, and renders a budgeted
  core-memory block through the shared prompt assembler. Search is hybrid RRF
  (lexical + semantic + recency) through the shared `services/retrieval/`
  seam.
- **Tools.** Auto-mounted `save_memory`, `search_memory`, `update_memory`, and
  `forget_memory` go through the audited tool registry; core-memory writes
  always require approval, and an agent policy cannot weaken that.
- **Management.** `/memories` routes, `services/memories/`, web UI where
  operators review, correct, archive, and purge memories.

Use memory for information learned during a conversation that must shape later
conversations. Store reference documents in the Knowledge Base and working
documents in Files.

## Conversation summaries (compaction—not memory)

When a conversation's history is trimmed (`services/agents/runtime/history.py`),
a background job summarizes the trimmed span with a small model and the
summary is injected as a synthetic user message at the trim watermark
(`conversation_summaries` table and `services/conversation_summaries/`).
This is per-conversation, derived, and has no user surface. It keeps long
conversations coherent; it does not persist anything across conversations and
should never be described as memory.

## Choose a home for context

- For selectively assigned instructions about how to act, use a **Skill**.
- For a durable uploaded or generated document to read or edit, use a **File**.
- For a versioned agent-authored report, page, diagram, or table that someone
  views, presents, or shares, use an **Artifact**.
- For shared reference material found through search, use a **Knowledge Base
  document**.
- For learned information that must persist across conversations, use a
  **Memory**.
