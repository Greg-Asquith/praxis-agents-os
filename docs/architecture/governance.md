<!-- docs/architecture/governance.md -->

# Governance and lifecycle

- **Status:** Living policy document.
- **Rule:** Implementation changes cite the relevant section (for example,
  "per `governance.md` §3 Retention"). Any deliberate deviation is recorded
  back into this note in the same pull request. When a policy ships, its cell
  moves from `[default — confirm at review]` to _(enforced)_.
- This note contains **policy, not implementation**. Enforcement details
  live in the code and tests that implement it.

Every default below is marked `[default — confirm at review]` unless marked
_(enforced)_. Flipping a default updates this note alongside the code.

## 1. Role matrix

Role definitions use the `WorkspaceRole` values `owner`, `admin`, `member`,
and `read_only` in `models/workspace.py`. The role sets are `MANAGER_ROLES`
(`owner` and `admin`), `EDITOR_ROLES` (also `member`), and `READ_ROLES` (also
`read_only`) in `services/workspaces/utils.py`. Access checks use `require_role` and the
`require_owner`/`require_editor`/`require_read` shortcuts
(`core/dependencies.py`). Super-admin is an email allowlist
(`require_super_admin`, `core/dependencies.py`).

Legend: ✓ allowed, — denied. All non-_(enforced)_ cells are
`[default — confirm at review]`.

| Operation                                                                                       | read_only | member | admin | owner |
| ----------------------------------------------------------------------------------------------- | --------- | ------ | ----- | ----- |
| View agents/conversations/schedules/skills/files/KB/artifacts                                   | ✓         | ✓      | ✓     | ✓     |
| Create/edit agents, skills _(enforced: EDITOR)_                                                 | —         | ✓      | ✓     | ✓     |
| Create schedules _(enforced: `agent_schedules/authorisation.py`)_                               | —         | ✓      | ✓     | ✓     |
| Mutate others' schedules _(enforced: owner-or-admin)_                                           | —         | —      | ✓     | ✓     |
| Upload/edit/delete files _(enforced: `services/files` access gates)_                            | —         | ✓      | ✓     | ✓     |
| Hard-delete / purge files _(enforced: `require_file_purge_access`)_                             | —         | —      | ✓     | ✓     |
| Connect/revoke own user-scoped integrations _(enforced)_                                        | —         | ✓      | ✓     | ✓     |
| Connect/revoke workspace-scoped integrations _(enforced)_                                       | —         | —      | ✓     | ✓     |
| Select integration resources / set conversation context / edit context groups _(enforced)_      | —         | ✓      | ✓     | ✓     |
| View credential metadata — never secret values _(enforced)_                                     | —         | —      | ✓     | ✓     |
| Enter API keys / secret references _(enforced)_                                                 | —         | —      | ✓     | ✓     |
| Replace API keys / service-account keys on an existing connection _(enforced)_                  | —         | —      | ✓     | ✓     |
| Create/edit KB documents _(enforced)_                                                           | —         | ✓      | ✓     | ✓     |
| Delete workspace-scope memories _(enforced)_                                                    | —         | —      | ✓     | ✓     |
| Edit/delete own-scope (user/agent) memories _(enforced)_                                        | —         | ✓      | ✓     | ✓     |
| Create artifacts via agents _(enforced)_                                                        | —         | ✓      | ✓     | ✓     |
| Create/revoke artifact share links _(enforced)_                                                 | —         | —      | ✓     | ✓     |
| View audit log _(enforced: MANAGER)_                                                            | —         | —      | ✓     | ✓     |
| View security events _(enforced: super-admin only — `security_events` has no workspace column)_ | —         | —      | —     | —     |
| Configure agent tool policies _(enforced: EDITOR via agents)_                                   | —         | ✓      | ✓     | ✓     |

Context Groups inherit the active workspace's scope. In a shared workspace,
group members must come from connections owned by that same workspace. In a
personal workspace, groups may additionally include connections owned by the
active actor, but never connections owned by another workspace. Standalone
resource context intentionally retains actor-or-workspace visibility, including
personal connections selected while acting in a shared workspace.

Memory authorization uses two explicit interpretations of the matrix. A
user-scoped memory is visible and mutable only to its owning user, including
when another workspace member is an admin or owner. Workspace-scoped memory
edits are member+, matching KB document edits; archive and purge remain
admin+. Agent-scoped memories are workspace-visible and member-editable.
_(enforced)_

## 2. Approval defaults by tool effect

Mechanics are the registry `effect` metadata, the dispatch choke point, and
per-agent `tool_policies`. The following rules define the policy:

- `effect="read"` tools default `auto`. [default — confirm at review]
- `effect="write"` tools targeting **Praxis-internal state** (todos,
  scratch, Praxis Files, memory notes, KB documents — Praxis owns the
  KB) are internal in the run envelope. Their tool-level approval policy
  can still be stricter: durable Praxis file writes require approval even
  though they do not cross the Praxis boundary, and agent-initiated KB
  document writes default `approval` through the KB write-policy choke
  point. _(enforced for todos, scratch, Praxis Files, and auto-mounted
  memory notes. There is deliberately no agent KB write tool; the recorded
  default applies when one ships.)_
- Core-memory saves and updates always require approval, even though memory is
  Praxis-internal state and the tools are auto-mounted. The conditional check
  remains inside the tool body so an agent policy cannot weaken it.
  _(enforced)_
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
  metadata or an application availability gate. _(enforced except manual
  re-probe discipline)_
  A 2026-08-17 Plan 157 bridge probe on those same pinned versions confirmed
  that Anthropic and OpenAI accepted an unchanged XLSX upload, mounted the real
  workbook at `/files/input/OPAQUE_ID/input.xlsx` and
  `/mnt/data/OPAQUE_ID-input.xlsx` respectively, and edited it with sandbox
  `openpyxl`. OpenAI accepted `purpose="user_data"` with a one-hour
  `expires_after` backstop. Both bridge-active sandboxes again failed DNS and
  HTTPS access, and both uploaded inputs were deleted successfully and returned
  404 on a subsequent metadata read; repeating either delete also returned the
  provider's typed 404 `NotFoundError`, which pins the non-fatal deletion-failure
  surface. The published provider ceilings are 500 MB per Anthropic file and
  512 MB per OpenAI file; Praxis remains materially tighter at 50 MB per input
  and 100 MB per invocation. Uploaded inputs are fresh for every invocation,
  named in approval evidence, deleted in `finally`, and identified durably only
  in one file-scoped workspace audit event per upload (kept outside the
  tool-call roll-up so deletion outcomes stay visible). OpenAI additionally supplies a one-hour expiry
  backstop, while Anthropic inputs persist until the deletion attempt and then
  follow Anthropic's retention policy. The first pass exposed SDK response-shape
  drift in 059's downloader: OpenAI requires awaiting `aiter_bytes()` before
  iterating its result, while Anthropic exposes `iter_bytes()` directly. After
  correcting and regression-testing both shapes, edited XLSX outputs from both
  providers downloaded within the byte budget and passed package/formula
  validation. The final smoke also confirmed that OpenAI lists the mounted input
  beside generated container files; capture excludes known provider input ids
  before output budgeting and source-byte hashes as a defensive fallback, so an
  unchanged input is never duplicated as a generated Praxis File. A Google Files
  API control probe supplied the same XLSX both as
  prompt content and through `CodeExecutionTool.files`; Gemini rejected it with
  `400 INVALID_ARGUMENT` because XLSX is not a supported code-execution MIME
  type. A second probe uploaded bounded AnyDoc-derived Markdown successfully,
  but that prompt attachment was not mounted in Gemini's code filesystem.
  Google therefore retains the framed inline-text path: ingestible binary
  documents may degrade to bounded, explicitly derived Markdown for read-only
  computation, but binary revision editing remains unavailable. Scripted runtime
  scenarios separately confirm agent-attributed revision append and
  optimistic-conflict preservation through the production persistence seam;
  the revision and file-bridge operation audit events are verified at the
  service and route layers.
- `effect="write"` tools with **external side effects** (integration
  writes such as Google Drive or SharePoint mutations, artifact publication,
  and external KB writes) default `approval`. _(enforced for integration
  writes and artifact publication; no external KB targets exist)_
- Tool policy and human approval never grant a workspace role. Runtime
  dispatch reloads the initiating user's active membership and requires
  `EDITOR_ROLES` before every `effect="write"` invocation; read-only members
  may continue conversations and use `effect="read"` tools. _(enforced)_
- Code mode never aggregates or weakens tool decisions. The outer
  `run_workflow` tool has no side effect; every nested call independently
  retains its declared effect and egress, active membership and role check,
  run-envelope verdict, approval policy, output contract, bounds, and audit
  record through the same dispatch choke point as a direct call. A nested
  approval carries the same staged-content, expiry, and audit treatment as a
  direct call's approval. Eligible gated and write tools may therefore be
  exposed as workflow stubs; every decision remains scoped to one nested call
  and its validated effective arguments. _(enforced)_
- Batch consent is one list-shaped call whose complete bounded row set the
  operator reviews and may edit before approval. The edited set is what
  executes and what the audit digest records. No Code Mode mechanism approves
  arguments the operator has not seen. _(enforced)_
- Any tool that **spends money**, such as a Google Ads mutation, is
  `approval` with `supports_auto=False` — per-agent configuration may not
  weaken it. _(enforced)_
- Non-interactive principals: scheduled runs stamp a server-minted
  side-effect grant at run preparation time; the default is
  `require_approval`, and schedules may explicitly opt into `allow` when
  they are expected to perform external writes. Unapproved external writes
  under `require_approval` pause through the normal approval flow, while
  internal writes continue automatically. Delegated runs inherit the
  parent's side-effect grant and delegation cap at child-run creation.
  _(enforced)_

## 3. Retention and deletion

Two rules govern deletion:

1. **Deletion is symmetric.** Soft-deleting a row that owns blobs marks the
   blobs for deletion. The cleanup job permanently deletes the rows and blobs
   together.
2. **Audit rows survive their subject's deletion.** Audit foreign keys are
   `ondelete="SET NULL"` _(enforced: `models/audit_event.py`)_.

Cleanup operations use the generic jobs system, with one operation per resource
registered by the owning domain). Values not marked _(enforced)_ are
`[default — confirm at review]`.

| Resource                             | Soft delete                                      | Hard delete after                                                                | Storage cascade                                   | Audit survives                                      | Export                                                                                |
| ------------------------------------ | ------------------------------------------------ | -------------------------------------------------------------------------------- | ------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Files/FileRevisions                  | ✓ _(enforced)_                                   | 30 d _(enforced)_                                                                | tombstone blob; sweeper deletes both _(enforced)_ | ✓ _(enforced)_                                      | single-file signed downloads _(enforced)_; batch export [default — confirm at review] |
| Scratch                              | TTL expiry _(enforced)_                          | 7 d rolling TTL; content purged on expiry _(enforced)_                           | n/a (DB text)                                     | rows summarized _(enforced)_                        | —                                                                                     |
| Jobs + payloads                      | terminal rows kept _(enforced)_                  | 30 d _(enforced)_                                                                | n/a                                               | counters only _(enforced)_                          | —                                                                                     |
| KB documents/chunks/embeddings       | ✓ _(enforced)_                                   | 30 d after soft-delete; chunks/vectors cascade on hard-delete _(enforced)_       | n/a (canonical markdown in Postgres)              | ✓ (audit rows have no subject FK) _(enforced)_      | ✓ (canonical markdown) _(enforced)_                                                   |
| Memories                             | supersession and archive by default _(enforced)_ | archive at `expires_at`; hard-delete only by an explicit user purge _(enforced)_ | n/a                                               | ✓                                                   | ✓                                                                                     |
| Credentials                          | revoke = soft _(enforced)_                       | 30 d after revoke; tokens crypto-shredded at revoke _(enforced)_                 | n/a                                               | metadata only, never values                         | —                                                                                     |
| Integration resources/discovery runs | ✓ / plain rows _(enforced)_                      | 90 d _(enforced)_                                                                | n/a                                               | counters                                            | —                                                                                     |
| Artifact shares                      | revocable _(enforced)_                           | at `expires_at` (default 7 d) _(enforced)_                                       | n/a                                               | ✓ _(enforced)_                                      | —                                                                                     |
| Audit events                         | append-only                                      | 400 d                                                                            | n/a                                               | n/a                                                 | ✓ (super-admin)                                                                       |
| Security events                      | append-only                                      | 400 d                                                                            | n/a                                               | n/a                                                 | super-admin only                                                                      |
| Conversation todos                   | follows the conversation lifecycle               | with conversation                                                                | n/a                                               | digest rows                                         | —                                                                                     |
| Conversation summaries               | derived rows, one per trim watermark             | with conversation; safe to regenerate                                            | n/a (bounded Postgres text)                       | no separate audit; source messages remain canonical | —                                                                                     |

## 4. Quotas and cost controls

All limits initially use **counters and admin visibility without hard
enforcement**. Values not marked _(enforced)_ are
`[default — confirm at review]`.

| Quota                   | Default                                                                                                                                                                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-workspace storage   | 10 GB _(counter + soft flag enforced; no hard enforcement)_                                                                                                                                                                                           |
| Upload size             | existing `core/settings/files.py` keys: `MAX_FILE_SIZE_DOCUMENT` (50 MB), `MAX_FILE_SIZE_AGENT_FILE` (100 MB), `MAX_FILE_SIZE_AVATAR` (5 MB), `MAX_FILE_SIZE_ICON` (2 MB), `MAX_FILE_SIZE_IMAGE` (10 MB), `MAX_FILE_SIZE_VIDEO` (100 MB) _(enforced)_ |
| Embedding budget        | 2 M tokens/month/workspace _(enforced)_                                                                                                                                                                                                               |
| Job concurrency         | 4/workspace, observed at claim time; global cap = worker batch/concurrency settings _(counter and claim-seam enforcement in place)_                                                                                                                   |
| Per-run token/step caps | runtime `UsageLimits` + `max_steps`; unattended schedules may tighten request and total-token limits through schedule completion contracts _(enforced)_                                                                                               |
| Artifact-share creation | 10/hour/workspace _(enforced)_                                                                                                                                                                                                                        |
| Integration API retries | `Retry-After`-aware, bounded attempts _(enforced)_                                                                                                                                                                                                    |

## 5. Secrets operating model

- Production **requires** a cloud secret-manager provider (GCP Secret
  Manager, Azure Key Vault, or AWS Secrets Manager, behind a provider
  contract like storage). Dev uses an env-var/encrypted-file provider,
  **local-only** the way console email is; the production-safety
  `model_validator` in `core/settings/__init__.py` rejects a missing
  or incompletely configured secret provider outside local environments.
  _(enforced)_
- The API accepts **references only** (`{provider, name, version}`). A raw
  secret value in a request body is a validation error — except the
  deliberate api-key connect flow, which immediately writes the value
  to the manager and stores only the reference. _(enforced)_
- Only OAuth tokens are stored (encrypted) in Postgres; everything else is
  a reference resolved at call time. _(enforced)_
- Rotation adds a secret version and starts asynchronous connection discovery. The old
  version stays readable while the new version is checked. Reference
  credentials are replaced in place on the existing connection, without
  changing auth mode or deleting externally owned secrets. _(enforced)_
- The local-only encrypted store has its own API-root-anchored path, separate
  from served object storage. API and worker processes coordinate through an
  OS-level lock, and same-directory atomic replacement prevents partial or
  lost writes. Secret-store availability failures are operational 503s; they
  preserve credentials and prior resources for discovery retry rather than
  requesting reauthentication. _(enforced)_
- Entry rights follow section 1 and require an admin or owner. [default — confirm at review]
- Audited events: reference create/update/delete and every **resolve
  failure** — never secret values, and no audit on successful resolves (too
  noisy). _(enforced)_

## 6. Notification policy

In-app delivery uses the notification service at
`services/notifications/service.py`. Public notification routes and UI are
pending. Email delivery is pending until a digest exists. Workspace invitations
create neither email nor in-app notifications, so the inviting operator shares the returned link.
A pending, unexpired invitation may admit account creation while signup is
closed; OAuth requires the provider-verified address and auto-accepts on full
sign-in, while password registration requires the raw invitation token. Rows not marked
_(enforced)_ are `[default — confirm at review]`.

| Event                                                     | Notify (in-app) | Recipient                                       |
| --------------------------------------------------------- | --------------- | ----------------------------------------------- |
| Schedule run terminal failure / auto-disable              | ✓               | schedule owner                                  |
| OAuth integration `needs_reauth`                          | ✓ _(enforced)_  | connecting user _(enforced)_                    |
| Reference integration `needs_credential`                  | ✓ _(enforced)_  | connecting user                                 |
| Integration discovery terminal failure                    | ✓ _(enforced)_  | connecting user _(enforced)_                    |
| Job pipeline failure — only after final retry exhausted   | ✓ _(enforced)_  | initiator (`initiated_by_user_id`) _(enforced)_ |
| Every tool invocation, successful runs, routine refreshes | — (audit only)  | —                                               |
