# Plan 029: Governance & lifecycle design note (Gate G3)

> **Executor instructions**: This is a **design-doc plan** — the deliverable
> is `docs/architecture/governance.md` plus tiny consistency fixes, not a
> feature. Follow the steps; where this plan states a default, adopt it in
> the doc and mark it `[default — confirm at review]` so the operator can
> veto cheaply at PR review. If anything in "STOP conditions" occurs, stop
> and report. When done, update the status row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/services/workspaces/utils.py apps/api/core/settings/ docs/architecture/`
> Verify the role sets and settings keys cited below still exist as
> described before transcribing them.

## Status

- **Priority**: P1 (blocks Gate G3: must be DONE before 037, 043, 048, 050)
- **Effort**: M (mostly writing + code-verification; near-zero code)
- **Risk**: LOW to execute, HIGH to skip (every later phase mints resource
  types; retrofitting governance across six subsystems is the expensive
  path)
- **Depends on**: none hard; best written after 021–026 exist so the matrix
  cites real enforcement points
- **Category**: cross-cutting design (roadmap `000_MASTER_ROADMAP.md` §4,
  Gate G3)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

This plan resolves the gaps-doc clusters (Governance Matrix, Data Lifecycle
And Retention, Quotas And Cost Controls, Secret Manager Operations,
Notifications) by writing the recommended defaults below into one
architecture note. Two meta-decisions:

1. **One note, five sections, plan-cited.** Downstream plans implement
   *slices* of this note and must cite the section they implement
   ("per `governance.md` §Retention"); the note itself never contains
   implementation detail — it contains policy.
2. **Defaults are decided here, vetoed at review.** The executor adopts the
   tables below verbatim; every value carries the confirm-at-review marker
   so product can flip individual cells without re-planning. A flipped cell
   updates the note, not this plan.

## Why this matters

Phases 4a/4b/5/6 each mint new resource types (connections, credentials,
documents, memories, artifacts, shares). The gaps review found the roadmap
silent on who-may-do-what, what-gets-deleted-when, what-costs-are-bounded,
how-secrets-operate, and what-notifies — five questions that are cheap to
answer once, now, and brutally expensive to answer per-subsystem after the
schemas ship. Gate G3 exists so no plan writes `CREATE TABLE` for a new
resource type before its row exists in these tables.

## Current state

- Role machinery: `WorkspaceRole` owner/admin/member/read_only
  (`models/workspace.py:26-32`); role sets `MANAGER_ROLES` (owner+admin),
  `EDITOR_ROLES` (+member), `READ_ROLES` (+read_only)
  (`services/workspaces/utils.py:24-33`); route/service gating via
  `require_role`/`require_owner` (`core/dependencies.py:238-264`) and
  service-level `require_workspace_role`. Super-admin =
  email allowlist (`require_super_admin`, `core/dependencies.py:222-235`).
- Existing per-resource authz precedents: agents (EDITOR write —
  `require_agent_write_access`), schedules (owner-or-admin mutate —
  `services/agent_schedules/authorisation.py`), invitations/memberships
  (MANAGER), audit viewer (MANAGER, plan 023), security events
  (super-admin, plan 023).
- Soft-delete: `BaseModel` `deleted/deleted_at/deleted_by`
  (`models/base.py:33-115`) everywhere; **no sweeper hard-deletes anything
  today**, and blob deletion exists only for avatars/icons.
- Size limits already in settings: `core/settings/files.py`
  (`MAX_FILE_SIZE_DOCUMENT/AGENT_FILE/...`) — cite exact keys after reading
  the file. Token caps: plan 011 (`UsageLimits`). No storage, embedding, or
  job quotas exist.
- Secrets: OAuth login secrets via env settings; **no secret-manager
  abstraction exists**; `docs/legacy/ROADMAP_QUESTIONS_GAPS.md` §Secret
  Manager Operations holds the open questions. Donor design:
  references-only (`{provider, name, version}`), resolve at call time
  (DONOR_PORT_ROADMAP.md §4.2).
- Notifications: `services/notifications/service.py` exists (used for
  invites) — a real substrate the policy can target.
- `docs/architecture/` exists (`agent-runtime.md`); the note joins it.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Verify citations | `grep -n "MANAGER_ROLES\|EDITOR_ROLES\|READ_ROLES" apps/api/services/workspaces/utils.py` | the three sets |
| Verify settings | `sed -n '1,60p' apps/api/core/settings/files.py` | size-limit keys |
| Lint (if any code) | `cd apps/api && uv run ruff check .` | exit 0 |

## Scope

**In scope:**

- `docs/architecture/governance.md` (create — the deliverable)
- `docs/plans/000_MASTER_ROADMAP.md` (modify: one line marking G3's doc as
  existing once merged)
- Optional micro-fixes discovered while verifying citations (typos in
  docstrings only — nothing behavioral)

**Out of scope (do NOT touch):**

- ANY enforcement code — no new dependencies, columns, sweepers, quota
  counters, or secret providers. Those are 030+/037+ slices citing this
  note.
- Re-opening decisions already taken in plans 021–028 ("Decisions taken"
  blocks there are settled; the note records them).

## Git workflow

- Branch: `advisor/029-governance-design-note`
- Commit style: `Docs - Governance & Lifecycle Design Note`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Skeleton + sourcing rules

Create `docs/architecture/governance.md` with front matter stating: status
(living document), owning gate (G3), and the rule that downstream plans cite
sections and record deviations back into the note. Sections: 1 Role Matrix,
2 Approval Defaults, 3 Retention & Deletion, 4 Quotas & Cost Controls,
5 Secrets Operating Model, 6 Notification Policy.

### Step 2: §1 Role matrix

Transcribe this matrix (rows = resource operations, columns = read_only /
member / admin / owner / super-admin), verifying every "already enforced"
citation against code. Legend: ✓ allowed, — denied. All cells
`[default — confirm at review]` unless marked *(enforced today)*.

| Operation | read_only | member | admin | owner |
|---|---|---|---|---|
| View agents/conversations/schedules/skills/files/KB/artifacts | ✓ | ✓ | ✓ | ✓ |
| Create/edit agents, skills *(enforced: EDITOR)* | — | ✓ | ✓ | ✓ |
| Create schedules *(enforced: 021)* | — | ✓ | ✓ | ✓ |
| Mutate others' schedules *(enforced: 021 owner-or-admin)* | — | — | ✓ | ✓ |
| Upload/edit/delete files (031–032) | — | ✓ | ✓ | ✓ |
| Hard-delete / purge files | — | — | ✓ | ✓ |
| Connect/revoke own user-scoped integrations (037–038) | — | ✓ | ✓ | ✓ |
| Connect/revoke workspace-scoped integrations | — | — | ✓ | ✓ |
| Select integration resources / edit context groups (039–040) | — | ✓ | ✓ | ✓ |
| View credential metadata (never secret values) | — | — | ✓ | ✓ |
| Enter API keys / secret references (037) | — | — | ✓ | ✓ |
| Create/edit KB documents (044/046) | — | ✓ | ✓ | ✓ |
| Delete workspace-scope memories (049) | — | — | ✓ | ✓ |
| Edit/delete own-scope (user/agent) memories (049) | — | ✓ | ✓ | ✓ |
| Create artifacts via agents (050) | follows tool policy | ✓ | ✓ | ✓ |
| Create/revoke artifact share links (051) | — | — | ✓ | ✓ |
| View audit log *(enforced: 023 MANAGER)* | — | — | ✓ | ✓ |
| View security events *(enforced: 023 super-admin)* | — | — | — | — |
| Configure agent tool policies *(enforced: EDITOR via agents)* | — | ✓ | ✓ | ✓ |

### Step 3: §2 Approval defaults per tool effect

Record the policy law (025/026 mechanics referenced, not restated):
`effect="read"` tools default `auto`; `effect="write"` tools targeting
**Praxis-internal state** (todos, scratch, memory notes) default `auto`;
`effect="write"` tools with **external side effects** (integration writes,
durable file writes via promote, artifact creation, KB writes from
conversations) default `approval`; anything that **spends money** (Google
Ads mutations, 041) is `approval` and `supports_auto=False` — per-agent
config may not weaken it. Non-interactive principals: scheduled runs pause
on approval (026 decision 3); delegated runs inherit the parent cap.

### Step 4: §3 Retention & deletion matrix

Columns: soft-delete?, hard-delete after, storage cascade, survives-in-audit,
export path. Defaults to transcribe:

| Resource | Soft | Hard after | Storage cascade | Audit survives | Export |
|---|---|---|---|---|---|
| Files/FileRevisions (031) | ✓ | 30 d | tombstone blob, sweeper deletes both | ✓ | ✓ (signed URL batch) |
| Scratch (034) | TTL expiry | 7 d rolling TTL, purge content on expiry | n/a (DB text) | rows summarized | — |
| Jobs + payloads (030) | terminal rows kept | 30 d | n/a | counters only | — |
| KB documents/chunks/embeddings (044) | ✓ | 30 d after doc hard-delete; chunks/vectors cascade immediately with doc | n/a | ✓ | ✓ (markdown) |
| Memories (048) | supersession, never hard | archive at `expires_at`; hard-delete only by user action | n/a | ✓ | ✓ |
| Credentials (037) | revoke = soft | 30 d after revoke (tokens crypto-shredded at revoke) | n/a | metadata only, never values | — |
| Integration resources/discovery runs (039) | ✓ / plain rows | 90 d | n/a | counters | — |
| Artifact shares (051) | revocable | at `expires_at` (default 7 d) | n/a | ✓ | — |
| Audit events | append-only | 400 d | n/a | n/a | ✓ (super-admin) |
| Security events | append-only | 400 d | n/a | n/a | super-admin only |
| Conversation todos (028) | rides conversation | with conversation | n/a | digest rows | — |

Plus the two laws: **deletion is symmetric** (rows AND blobs, donor rule) and
**audit rows survive their subject's deletion** (FKs already SET NULL —
cite `models/audit_event.py`).

### Step 5: §4 Quotas & cost controls

Defaults: per-workspace storage 10 GB; upload size = existing
`core/settings/files.py` keys (cite them); embedding budget 2 M
tokens/month/workspace; job concurrency 4/workspace with global worker cap;
per-run token/step caps = plan 011 + `max_steps`; artifact-share creation
10/hour/workspace; integration API retries = `Retry-After`-aware with
bounded attempts (donor rule). All soft limits v1: **counters + admin
visibility first, hard enforcement second** — the note must say which plan
adds each counter (030 jobs, 032 storage, 043 embeddings, 051 shares).

### Step 6: §5 Secrets operating model

Answering the gaps-doc questions: production **requires** a secret-manager
provider (GCP Secret Manager first, provider ABC like storage); dev uses an
env-var provider, **local-only** the way console email is; the API accepts
**references only** — a raw secret value in a request body is a validation
error, except the deliberate api-key connect flow (037) which immediately
writes to the manager and stores the reference; rotation = new version +
connection re-test, old version readable until confirmed; entry rights per
§1 (admin+); audited events: reference create/update/delete and every
resolve failure (never values, never audit on successful resolve — too
noisy). Settings validation belongs in `core/settings` per AGENTS.md
(unsafe prod combination = no secret provider configured).

### Step 7: §6 Notification policy

Target the existing notification service: notify (in-app) on — schedule run
terminal failure + auto-disable (to schedule owner), integration
`needs_reauth`/discovery failure (to connector), job pipelines only after
final retry exhausted (to initiator). Audit-only (no notification): every
tool invocation, successful runs, routine refreshes. Email stays out until
a digest exists. Each row names the emitting plan (021-adjacent worker, 030,
039).

### Step 8: Cross-link and close the gate

Add to the note a "Consumed by" table (037/043/048/050 → sections). In
`000_MASTER_ROADMAP.md` §3, annotate G3: "design note exists:
`docs/architecture/governance.md`". Verify every code citation one final
time; produce the PR for operator review (the veto pass).

## Test plan

Not applicable (documentation). The "test" is Step 8's citation
verification plus operator review of every `[default — confirm at review]`
marker.

## Done criteria

- [ ] `docs/architecture/governance.md` exists with all six sections and
      every default marked for review
- [ ] Every code citation verified against HEAD (no stale line refs)
- [ ] All five gaps-doc question clusters have an answer or an explicit
      "deferred to plan NNN" line — zero silently dropped questions
- [ ] `000_MASTER_ROADMAP.md` G3 annotation added
- [ ] No code changes beyond docstring typo fixes
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- A downstream plan (037+) has already started implementing governance
  decisions that contradict a default here — reconcile direction first.
- The role sets or settings keys cited in "Current state" no longer exist.
- You find yourself writing enforcement code — wrong plan.
- Any table above conflicts with a "Decisions taken" block in plans 021–028
  (those win; update this note's table and flag the conflict).

## Maintenance notes

- This note is **living**: every downstream plan that implements a slice
  updates the corresponding cell from `[default — confirm at review]` to
  `[implemented: plan NNN]`. A cell left unmarked after its plan ships is a
  review failure.
- The retention sweeper itself is deliberately unowned here — plan 030's
  worker harness is its natural home (one sweep job kind per resource);
  record that in 030's plan when written.
- When multi-workspace orgs or per-seat billing arrive, §4 becomes a real
  quota service; the counters-first default is what makes that incremental.
