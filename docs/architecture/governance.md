<!-- docs/architecture/governance.md -->

# Governance & Lifecycle

- **Status**: living policy document
- **Rule**: implementation changes cite the relevant section (for example,
  "per `governance.md` §3 Retention"). Any deliberate deviation is recorded
  back into this note in the same pull request. When a policy ships, its cell
  moves from `[default — confirm at review]` to *(enforced)*.
- This note contains **policy, not implementation**. Enforcement mechanics
  live in the code and tests that implement it.

Every default below is marked `[default — confirm at review]` unless marked
*(enforced)*. Flipping a default updates this note alongside the code.

## 1. Role Matrix

Role machinery: `WorkspaceRole` owner/admin/member/read_only
(`models/workspace.py`); role sets `MANAGER_ROLES` (owner+admin),
`EDITOR_ROLES` (+member), `READ_ROLES` (+read_only)
(`services/workspaces/utils.py`); gating via `require_role` and the
`require_owner`/`require_editor`/`require_read` shortcuts
(`core/dependencies.py`). Super-admin is an email allowlist
(`require_super_admin`, `core/dependencies.py`).

Legend: ✓ allowed, — denied. All non-*(enforced)* cells are
`[default — confirm at review]`.

| Operation | read_only | member | admin | owner |
|---|---|---|---|---|
| View agents/conversations/schedules/skills/files/KB/artifacts | ✓ | ✓ | ✓ | ✓ |
| Create/edit agents, skills *(enforced: EDITOR)* | — | ✓ | ✓ | ✓ |
| Create schedules *(enforced: `agent_schedules/authorisation.py`)* | — | ✓ | ✓ | ✓ |
| Mutate others' schedules *(enforced: owner-or-admin)* | — | — | ✓ | ✓ |
| Upload/edit/delete files *(enforced: `services/files` access gates)* | — | ✓ | ✓ | ✓ |
| Hard-delete / purge files *(enforced: `require_file_purge_access`)* | — | — | ✓ | ✓ |
| Connect/revoke own user-scoped integrations *(enforced)* | — | ✓ | ✓ | ✓ |
| Connect/revoke workspace-scoped integrations *(enforced)* | — | — | ✓ | ✓ |
| Select integration resources / set conversation context / edit context groups *(enforced)* | — | ✓ | ✓ | ✓ |
| View credential metadata — never secret values *(enforced)* | — | — | ✓ | ✓ |
| Enter API keys / secret references *(enforced)* | — | — | ✓ | ✓ |
| Replace API keys / service-account keys on an existing connection *(enforced)* | — | — | ✓ | ✓ |
| Create/edit KB documents *(enforced)* | — | ✓ | ✓ | ✓ |
| Delete workspace-scope memories *(enforced)* | — | — | ✓ | ✓ |
| Edit/delete own-scope (user/agent) memories *(enforced)* | — | ✓ | ✓ | ✓ |
| Create artifacts via agents *(enforced)* | — | ✓ | ✓ | ✓ |
| Create/revoke artifact share links *(enforced)* | — | — | ✓ | ✓ |
| View audit log *(enforced: MANAGER)* | — | — | ✓ | ✓ |
| View security events *(enforced: super-admin only — `security_events` has no workspace column)* | — | — | — | — |
| Configure agent tool policies *(enforced: EDITOR via agents)* | — | ✓ | ✓ | ✓ |

Context Groups inherit the active workspace's scope. In a shared workspace,
group members must come from connections owned by that same workspace. In a
personal workspace, groups may additionally include connections owned by the
current actor, but never connections owned by another workspace. Standalone
resource context intentionally retains actor-or-workspace visibility, including
personal connections selected while acting in a shared workspace.

Memory authorization uses two explicit interpretations of the matrix. A
user-scoped memory is visible and mutable only to its owning user, including
when another workspace member is an admin or owner. Workspace-scoped memory
edits are member+, matching KB document edits; archive and purge remain
admin+. Agent-scoped memories are workspace-visible and member-editable.
*(enforced)*

## 2. Approval Defaults Per Tool Effect

Mechanics are the registry `effect` metadata, the dispatch choke point, and
per-agent `tool_policies`; this section is the policy law:

- `effect="read"` tools default `auto`. [default — confirm at review]
- `effect="write"` tools targeting **Praxis-internal state** (todos,
  scratch, Praxis Files, memory notes, KB documents — Praxis owns the
  KB) are internal in the run envelope. Their tool-level approval policy
  can still be stricter: durable Praxis file writes require approval even
  though they do not cross the Praxis boundary, and agent-initiated KB
  document writes default `approval` through the KB write-policy choke
  point. *(enforced for todos, scratch, Praxis Files, and auto-mounted
  memory notes. There is deliberately no agent KB write tool; the recorded
  default applies when one ships.)*
- Core-memory saves and updates always require approval, even though memory is
  Praxis-internal state and the tools are auto-mounted. The conditional check
  remains inside the tool body so an agent policy cannot weaken it.
  *(enforced)*
- `run_code` is an internal-effect write because it can create durable Praxis
  Files and artifacts. It defaults to `approval` but supports `auto`, including
  unattended scheduled computations. Only OpenAI, Anthropic, and Google are
  eligible, each after 2026-08-14 DNS and HTTPS canary probes showed no sandbox
  egress. Those probes used Pydantic AI 2.28.0 with Anthropic 0.113.0,
  google-genai 2.10.0, and OpenAI 2.50.0. OpenAI `gpt-5.6-luna`, Anthropic
  `claude-sonnet-5` (code execution 20260120), and Google
  `gemini-3.7-flash` accepted native code execution and exposed native
  call/return parts. Generated office documents and images were recovered
  through OpenAI container files, Anthropic beta files, and Google inline file
  bytes. Re-run the capability, file-output, DNS, and HTTPS probes after a
  relevant Pydantic AI, provider SDK, or provider API change. This dated probe
  evidence is an operator-maintained verification record, not runtime package
  metadata or an application availability gate. *(enforced except manual
  re-probe discipline)*
- `effect="write"` tools with **external side effects** (integration
  writes such as Google Drive or SharePoint mutations, artifact publication,
  and external KB writes) default `approval`. *(enforced for integration
  writes and artifact publication; no external KB targets exist)*
- Tool policy and human approval never grant a workspace role. Runtime
  dispatch reloads the initiating user's active membership and requires
  `EDITOR_ROLES` before every `effect="write"` invocation; read-only members
  may continue conversations and use `effect="read"` tools. *(enforced)*
- Code mode never aggregates or weakens tool decisions. The outer
  `run_workflow` tool has no side effect; every nested call independently
  retains its declared effect and egress, active membership and role check,
  run-envelope verdict, approval policy, output contract, bounds, and audit
  record through the same dispatch choke point as a direct call. A nested
  approval carries the same staged-content, expiry, and audit treatment as a
  direct call's approval. Eligible gated and write tools may therefore be
  exposed as workflow stubs; every decision remains scoped to one nested call
  and its validated effective arguments. *(enforced)*
- Batch consent is one list-shaped call whose complete bounded row set the
  operator reviews and may edit before approval. The edited set is what
  executes and what the audit digest records. No Code Mode mechanism approves
  arguments the operator has not seen. *(enforced)*
- Anything that **spends money** (e.g. Google Ads mutations) is
  `approval` with `supports_auto=False` — per-agent configuration may not
  weaken it. *(enforced)*
- Non-interactive principals: scheduled runs stamp a server-minted
  side-effect grant at run preparation time; the default is
  `require_approval`, and schedules may explicitly opt into `allow` when
  they are expected to perform external writes. Unapproved external writes
  under `require_approval` pause through the normal approval flow, while
  internal writes continue automatically. Delegated runs inherit the
  parent's side-effect grant and delegation cap at child-run creation.
  *(enforced)*

## 3. Retention & Deletion

Two laws:

1. **Deletion is symmetric** — soft-deleting a row that owns blobs
   tombstones the blobs; the sweeper hard-deletes rows AND blobs together.
2. **Audit rows survive their subject's deletion** — audit FKs are
   `ondelete="SET NULL"` *(enforced: `models/audit_event.py`)*.

Sweepers ride the generic jobs harness (one sweep kind per resource,
registered by the owning domain). Values not marked *(enforced)* are
`[default — confirm at review]`.

| Resource | Soft delete | Hard delete after | Storage cascade | Audit survives | Export |
|---|---|---|---|---|---|
| Files/FileRevisions | ✓ *(enforced)* | 30 d *(enforced)* | tombstone blob; sweeper deletes both *(enforced)* | ✓ *(enforced)* | single-file signed downloads *(enforced)*; batch export [default — confirm at review] |
| Scratch | TTL expiry *(enforced)* | 7 d rolling TTL; content purged on expiry *(enforced)* | n/a (DB text) | rows summarized *(enforced)* | — |
| Jobs + payloads | terminal rows kept *(enforced)* | 30 d *(enforced)* | n/a | counters only *(enforced)* | — |
| KB documents/chunks/embeddings | ✓ *(enforced)* | 30 d after soft-delete; chunks/vectors cascade on hard-delete *(enforced)* | n/a (canonical markdown in Postgres) | ✓ (audit rows have no subject FK) *(enforced)* | ✓ (canonical markdown) *(enforced)* |
| Memories | supersession and archive by default *(enforced)* | archive at `expires_at`; hard-delete only by an explicit user purge *(enforced)* | n/a | ✓ | ✓ |
| Credentials | revoke = soft *(enforced)* | 30 d after revoke; tokens crypto-shredded at revoke *(enforced)* | n/a | metadata only, never values | — |
| Integration resources/discovery runs | ✓ / plain rows *(enforced)* | 90 d *(enforced)* | n/a | counters | — |
| Artifact shares | revocable *(enforced)* | at `expires_at` (default 7 d) *(enforced)* | n/a | ✓ *(enforced)* | — |
| Audit events | append-only | 400 d | n/a | n/a | ✓ (super-admin) |
| Security events | append-only | 400 d | n/a | n/a | super-admin only |
| Conversation todos | rides conversation | with conversation | n/a | digest rows | — |
| Conversation summaries | derived rows, one per trim watermark | with conversation; safe to regenerate | n/a (bounded Postgres text) | no separate audit; source messages remain canonical | — |

## 4. Quotas & Cost Controls

Law: all limits are **soft in v1 — counters + admin visibility first, hard
enforcement second**. Values not marked *(enforced)* are
`[default — confirm at review]`.

| Quota | Default |
|---|---|
| Per-workspace storage | 10 GB *(counter + soft flag enforced; no hard enforcement)* |
| Upload size | existing `core/settings/files.py` keys: `MAX_FILE_SIZE_DOCUMENT` (50 MB), `MAX_FILE_SIZE_AGENT_FILE` (100 MB), `MAX_FILE_SIZE_AVATAR` (5 MB), `MAX_FILE_SIZE_ICON` (2 MB), `MAX_FILE_SIZE_IMAGE` (10 MB), `MAX_FILE_SIZE_VIDEO` (100 MB) *(enforced)* |
| Embedding budget | 2 M tokens/month/workspace *(enforced)* |
| Job concurrency | 4/workspace, observed at claim time; global cap = worker batch/concurrency settings *(counter and claim-seam enforcement in place)* |
| Per-run token/step caps | runtime `UsageLimits` + `max_steps`; unattended schedules may tighten request and total-token limits through schedule completion contracts *(enforced)* |
| Artifact-share creation | 10/hour/workspace *(enforced)* |
| Integration API retries | `Retry-After`-aware, bounded attempts *(enforced)* |

## 5. Secrets Operating Model

- Production **requires** a cloud secret-manager provider (GCP Secret
  Manager, Azure Key Vault, or AWS Secrets Manager, behind a provider
  contract like storage). Dev uses an env-var/encrypted-file provider,
  **local-only** the way console email is; the production-safety
  `model_validator` in `core/settings/__init__.py` rejects a missing
  or incompletely configured secret provider outside local environments.
  *(enforced)*
- The API accepts **references only** (`{provider, name, version}`). A raw
  secret value in a request body is a validation error — except the
  deliberate api-key connect flow, which immediately writes the value
  to the manager and stores only the reference. *(enforced)*
- Only OAuth tokens are stored (encrypted) in Postgres; everything else is
  a reference resolved at call time. *(enforced)*
- Rotation = new secret version + asynchronous connection discovery; the old
  version stays readable while the new version is checked. Reference
  credentials are replaced in place on the existing connection, without
  changing auth mode or deleting externally owned secrets. *(enforced)*
- The local-only encrypted store has its own API-root-anchored path, separate
  from served object storage. API and worker processes coordinate through an
  OS-level lock, and same-directory atomic replacement prevents partial or
  lost writes. Secret-store availability failures are operational 503s; they
  preserve credentials and prior resources for discovery retry rather than
  requesting reauthentication. *(enforced)*
- Entry rights per §1 (admin+). [default — confirm at review]
- Audited events: reference create/update/delete and every **resolve
  failure** — never secret values, and no audit on successful resolves (too
  noisy). *(enforced)*

## 6. Notification Policy

Target: the existing in-app substrate
(`services/notifications/service.py` `create_notification`, used by
invites). Email stays out until a digest exists. Rows not marked
*(enforced)* are `[default — confirm at review]`.

| Event | Notify (in-app) | Recipient |
|---|---|---|
| Schedule run terminal failure / auto-disable | ✓ | schedule owner |
| OAuth integration `needs_reauth` | ✓ *(enforced)* | connecting user *(enforced)* |
| Reference integration `needs_credential` | ✓ *(enforced)* | connecting user |
| Integration discovery terminal failure | ✓ *(enforced)* | connecting user *(enforced)* |
| Job pipeline failure — only after final retry exhausted | ✓ *(enforced)* | initiator (`initiated_by_user_id`) *(enforced)* |
| Every tool invocation, successful runs, routine refreshes | — (audit only) | — |
