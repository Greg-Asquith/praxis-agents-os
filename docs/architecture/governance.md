# Governance & Lifecycle

- **Status**: living document (owning gate: G3, `docs/plans/000_MASTER_ROADMAP.md` §3)
- **Written**: 2026-07-06 at `0cbbb39` (plan 029)
- **Rule**: downstream plans implement *slices* of this note and cite the
  section they implement ("per `governance.md` §3 Retention"). A plan that
  deviates records the deviation back into this note in the same PR. When a
  slice ships, its cell moves from `[default — confirm at review]` to
  `[implemented: plan NNN]`. A cell left unmarked after its plan ships is a
  review failure.
- This note contains **policy, not implementation**. Enforcement mechanics
  live in the plans and code that cite it.

Every default below is marked `[default — confirm at review]` unless marked
*(enforced today)*. Flipping a default updates this note, not plan 029.

## 1. Role Matrix

Role machinery: `WorkspaceRole` owner/admin/member/read_only
(`models/workspace.py:26-32`); role sets `MANAGER_ROLES` (owner+admin),
`EDITOR_ROLES` (+member), `READ_ROLES` (+read_only)
(`services/workspaces/utils.py:24-31`); gating via `require_role` and the
`require_owner`/`require_editor`/`require_read` shortcuts
(`core/dependencies.py:243-269`). Super-admin is an email allowlist
(`require_super_admin`, `core/dependencies.py:227`).

Legend: ✓ allowed, — denied. Plan numbers name the implementing plan.
All non-*(enforced)* cells are `[default — confirm at review]`.

| Operation | read_only | member | admin | owner |
|---|---|---|---|---|
| View agents/conversations/schedules/skills/files/KB/artifacts | ✓ | ✓ | ✓ | ✓ |
| Create/edit agents, skills *(enforced today: EDITOR)* | — | ✓ | ✓ | ✓ |
| Create schedules *(enforced today: 021, `agent_schedules/authorisation.py`)* | — | ✓ | ✓ | ✓ |
| Mutate others' schedules *(enforced today: 021 owner-or-admin)* | — | — | ✓ | ✓ |
| Upload/edit/delete files (031–032) *(enforced today: 032, `services/files` access gates)* | — | ✓ | ✓ | ✓ |
| Hard-delete / purge files (032) *(enforced today: 032, `require_file_purge_access`)* | — | — | ✓ | ✓ |
| Connect/revoke own user-scoped integrations (037–038) | — | ✓ | ✓ | ✓ |
| Connect/revoke workspace-scoped integrations (037–038) | — | — | ✓ | ✓ |
| Select integration resources / edit context groups (039–040) | — | ✓ | ✓ | ✓ |
| View credential metadata — never secret values (037/042) | — | — | ✓ | ✓ |
| Enter API keys / secret references (037) | — | — | ✓ | ✓ |
| Create/edit KB documents (044/046) | — | ✓ | ✓ | ✓ |
| Delete workspace-scope memories (049) | — | — | ✓ | ✓ |
| Edit/delete own-scope (user/agent) memories (049) | — | ✓ | ✓ | ✓ |
| Create artifacts via agents (050) | follows tool policy | ✓ | ✓ | ✓ |
| Create/revoke artifact share links (051) | — | — | ✓ | ✓ |
| View audit log *(enforced today: 023 MANAGER)* | — | — | ✓ | ✓ |
| View security events *(enforced today: 023 super-admin only — `security_events` has no workspace column)* | — | — | — | — |
| Configure agent tool policies *(enforced today: EDITOR via agents)* | — | ✓ | ✓ | ✓ |

## 2. Approval Defaults Per Tool Effect

Mechanics are plans 025/026 (registry `effect` metadata, dispatch choke
point, per-agent `tool_policies`); this section is the policy law:

- `effect="read"` tools default `auto`. [default — confirm at review]
- `effect="write"` tools targeting **Praxis-internal state** (todos,
  scratch, memory notes) default `auto`. [default — confirm at review]
- `effect="write"` tools with **external side effects** (integration
  writes, durable file writes via promote, artifact creation, KB writes
  from conversations) default `approval`. [default — confirm at review]
- Anything that **spends money** (e.g. Google Ads mutations, 041) is
  `approval` with `supports_auto=False` — per-agent configuration may not
  weaken it. [default — confirm at review]
- Non-interactive principals: scheduled runs pause on approval (026
  decision, *(enforced today)*); delegated runs inherit the parent
  envelope's cap *(enforced today: 026 envelopes)*.

## 3. Retention & Deletion

Two laws:

1. **Deletion is symmetric** — soft-deleting a row that owns blobs
   tombstones the blobs; the sweeper hard-deletes rows AND blobs together.
2. **Audit rows survive their subject's deletion** — audit FKs are
   `ondelete="SET NULL"` *(enforced today: `models/audit_event.py:19,37,44`)*.

Sweepers ride the plan 030 jobs harness (one sweep kind per resource,
registered by the owning plan). All values `[default — confirm at review]`.

| Resource | Soft delete | Hard delete after | Storage cascade | Audit survives | Export |
|---|---|---|---|---|---|
| Files/FileRevisions (031/032) | ✓ [implemented: plan 031 schema + plan 032 lifecycle] | 30 d [implemented: plan 032] | tombstone blob; sweeper deletes both [implemented: plan 032] | ✓ [implemented: plan 032 mutation audit] | ✓ (single-file signed downloads shipped in 032; signed URL batch unplanned) [default — confirm at review] |
| Scratch (034) | TTL expiry | 7 d rolling TTL; purge content on expiry; delete after promotion | n/a (DB text) | rows summarized | — |
| Jobs + payloads (030) | terminal rows kept [implemented: plan 030] | 30 d [implemented: plan 030] | n/a | counters only [implemented: plan 030] | — |
| KB documents/chunks/embeddings (044) | ✓ | 30 d after doc hard-delete; chunks/vectors cascade immediately with doc | n/a | ✓ | ✓ (markdown) |
| Memories (048) | supersession, never hard | archive at `expires_at`; hard-delete only by user action | n/a | ✓ | ✓ |
| Credentials (037) | revoke = soft | 30 d after revoke; tokens crypto-shredded at revoke | n/a | metadata only, never values | — |
| Integration resources/discovery runs (039) | ✓ / plain rows | 90 d | n/a | counters | — |
| Artifact shares (051) | revocable | at `expires_at` (default 7 d) | n/a | ✓ | — |
| Audit events | append-only | 400 d | n/a | n/a | ✓ (super-admin) |
| Security events | append-only | 400 d | n/a | n/a | super-admin only |
| Conversation todos (028) | rides conversation | with conversation | n/a | digest rows | — |

## 4. Quotas & Cost Controls

Law: all limits are **soft in v1 — counters + admin visibility first, hard
enforcement second**. Each counter names the plan that adds it. All values
`[default — confirm at review]`.

| Quota | Default | Counter added by |
|---|---|---|
| Per-workspace storage | 10 GB | 032 [implemented: counter + soft flag, no hard enforcement] |
| Upload size | existing `core/settings/files.py` keys: `MAX_FILE_SIZE_DOCUMENT` (50 MB), `MAX_FILE_SIZE_AGENT_FILE` (100 MB), `MAX_FILE_SIZE_AVATAR` (5 MB), `MAX_FILE_SIZE_ICON` (2 MB), `MAX_FILE_SIZE_IMAGE` (10 MB), `MAX_FILE_SIZE_VIDEO` (100 MB) *(enforced today; image/video keys normalized by 031 from AI-specific names for shared file use)* | — |
| Embedding budget | 2 M tokens/month/workspace | 043 |
| Job concurrency | 4/workspace, observed at claim time; global cap = worker batch/concurrency settings [implemented: plan 030 counter + warning, plan 033 claim-seam enforcement and files surface] | 030 (counter implemented), 033 (first enforcement seam) |
| Per-run token/step caps | plan 011 `UsageLimits` + `max_steps` *(enforced today)* | — |
| Artifact-share creation | 10/hour/workspace | 051 |
| Integration API retries | `Retry-After`-aware, bounded attempts | 037 |

## 5. Secrets Operating Model

- Production **requires** a secret-manager provider (GCP Secret Manager
  first, behind a provider ABC like storage). Dev uses an env-var provider,
  **local-only** the way console email is; the production-safety
  `model_validator` in `core/settings/__init__.py:51` must reject a missing
  secret provider outside local environments. [default — confirm at review]
- The API accepts **references only** (`{provider, name, version}`). A raw
  secret value in a request body is a validation error — except the
  deliberate api-key connect flow (037), which immediately writes the value
  to the manager and stores only the reference. [default — confirm at review]
- Only OAuth tokens are stored (encrypted) in Postgres; everything else is
  a reference resolved at call time. [default — confirm at review]
- Rotation = new secret version + connection re-test; the old version stays
  readable until the new one is confirmed. [default — confirm at review]
- Entry rights per §1 (admin+). [default — confirm at review]
- Audited events: reference create/update/delete and every **resolve
  failure** — never secret values, and no audit on successful resolves (too
  noisy). [default — confirm at review]

## 6. Notification Policy

Target: the existing in-app substrate
(`services/notifications/service.py:105` `create_notification`, already
used by invites). Email stays out until a digest exists. All rows
`[default — confirm at review]`.

| Event | Notify (in-app) | Recipient | Emitting plan |
|---|---|---|---|
| Schedule run terminal failure / auto-disable | ✓ | schedule owner | 021-adjacent worker |
| Integration `needs_reauth` / discovery failure | ✓ | connecting user | 039 |
| Job pipeline failure — only after final retry exhausted | ✓ [implemented: plan 030] | initiator (`initiated_by_user_id`) [implemented: plan 030] | 030 |
| Every tool invocation, successful runs, routine refreshes | — (audit only) | — | — |

## Consumed By

| Plan | Sections implemented |
|---|---|
| 030 (jobs) | §3 (jobs retention, sweep pattern), §4 (jobs counter), §6 (job failure notify) |
| 031/032 (files) | §1, §3 (files), §4 (storage counter) |
| 034 (scratch + file tools) | §2, §3 (scratch) |
| 037–039 (integrations core) | §1, §3 (credentials/resources), §4 (retries), §5, §6 |
| 041 (first providers) | §2 (spend rule) |
| 043–046 (KB) | §1, §3 (KB), §4 (embedding budget), §2 (KB writes) |
| 048–049 (memory) | §1, §2, §3 (memories) |
| 050–051 (artifacts) | §1, §2, §3 (shares), §4 (share rate limit) |
