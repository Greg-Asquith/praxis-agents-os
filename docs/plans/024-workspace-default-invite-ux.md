# Plan 024: Workspace default persistence and invite UX

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**: `git diff --stat f83d210..HEAD -- apps/api/models/user.py apps/api/models/workspace.py apps/api/services/auth/ apps/api/services/workspaces/invitations/ apps/web/src/features/workspaces/ apps/web/src/features/auth/ apps/web/src/components/shell/workspace-switcher.tsx`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM (touches sign-in flow; high-risk area per AGENTS.md)
- **Depends on**: none (independent of the registry lane; roadmap Lane O)
- **Category**: operational surfaces (roadmap `000_MASTER_ROADMAP.md` Lane O)
- **Planned at**: commit `f83d210`, 2026-07-02

## Decisions taken

Resolving the open questions from `docs/legacy/ROADMAP_QUESTIONS_GAPS.md`
§Workspace And Invite UX:

1. **Switching persists.** Changing the active workspace in the UI persists to
   `users.default_workspace_id` via the existing `PATCH /auth/me` route.
   localStorage remains the instant same-device source; the server value makes
   the choice follow the user across devices and is already the fallback the
   provider uses.
2. **Pending invites auto-accept on sign-in.** After a *full* (not
   2FA-pending) authentication, all valid pending invitations addressed to
   the user's email are accepted through the existing acceptance service, so
   every acceptance keeps its audit + security events. Per-invite failures are
   logged and skipped — sign-in must never fail because of an invite.
3. **Acceptance does not switch the active workspace.** The user stays where
   they are; the new workspace simply appears in the switcher.
4. **Copy URL and copy code are separate buttons.** The invite URL is
   `{app-origin}/invitations/accept?token=…`, constructed in the frontend
   (no backend change). A new frontend accept route consumes it. Logged-out
   recipients are redirected to login by the auth layout; decision 2 then
   accepts the invite anyway, so the link still "works" end-to-end for them.
5. **Personal workspaces group first in the switcher**, labeled, with team
   workspaces below — presentation only, no behavioral difference.
6. **The invitation dialog gains a role select** (admin / member / read_only)
   — the backend create service already accepts `role`; the dialog currently
   hardcodes `"member"`.

## Why this matters

The backend validates the `X-Workspace` header against DB membership on every
request, but which workspace a user is "in" is currently a localStorage-only
fact, and joining a workspace requires pasting a raw token into… nothing (no
accept UI exists). Before integrations (Phase 4a) attach credentials and
active-context selections to workspaces, workspace identity needs to be
deliberate: persisted default, working invite links, and a switcher that
distinguishes personal from team. This closes the NOTES items "pending invites
accepted on sign in", "Copy Code/URL invitation button", and the
default-workspace question, and completes roadmap Lane O.

## Current state

Backend:

- `apps/api/models/user.py:57-66` — `users.default_workspace_id` **already
  exists** (UUID FK → workspaces, `ondelete="SET NULL"`, nullable, indexed via
  `ix_users_default_workspace`). It is written only by
  `services/workspaces/provisioning.py:47-48,95-96` (personal-workspace
  provisioning) and cleared by workspace/membership deletion
  (`services/workspaces/delete_workspace.py:46-47`,
  `.../memberships/delete_membership.py:57-59`). **No route lets a user set
  it.**
- `apps/api/services/auth/update_current_user.py:22-24` — `PATCH /auth/me`
  handles `display_name` only; audits via `record_user_audit_event` (line 28).
  Request schema `CurrentUserUpdateRequest` at
  `services/auth/schemas.py:122-131`. `AuthUser` already exposes
  `default_workspace_id` (`schemas.py:22`).
- `apps/api/core/dependencies.py:161-200` — active workspace resolved from the
  `X-Workspace` **slug** header, validated against `WorkspaceMembership`;
  header absent → `require_default_workspace_membership_for_user`.
- Invitations (`apps/api/models/workspace.py:112-171`): `token_hash` only (no
  plaintext stored, no `status` column — state derived from
  `accepted_at`/`expires_at`; helpers `is_valid` L141, `verify_raw_token`
  L156). Partial unique pending index per `(workspace_id, email)` L163; email
  lookup index `ix_workspace_invitations_email_workspace` L171.
- `services/workspaces/invitations/create_invitation.py:33` — MANAGER_ROLES
  only; returns the **raw token exactly once**
  (`WorkspaceInvitationCreateResponse{invitation, token}`,
  `services/workspaces/schemas.py:154`).
- `services/workspaces/invitations/accept_invitation_utils.py:51` — shared
  `accept_invitation(db, *, actor, invitation, request)`: **enforces
  `actor.email == invitation.email`** (L67-72), handles already-member /
  already-accepted / expired, creates or restores membership, sets
  `accepted_at`, writes audit + security events
  (`SecurityEventType.WORKSPACE_INVITATION_ACCEPTED`). `record_failed_accept`
  at L29. Token route: `POST /workspaces/invitations/accept`
  (`routes/workspaces/invitations/accept_invitation_by_token.py:19`).
- Sign-in hook point: `services/auth/password/login_with_password.py:82-83`
  already runs a post-auth step (`provision_personal_workspace` when
  `default_workspace_id is None`) before `issue_auth_response` (L90).
  Register: `register_with_password.py:84`. OAuth:
  `complete_oauth_login.py:94` → `issue_auth_response`. All flows converge on
  `services/auth/utils.py:78` `issue_auth_response(..., require_twofa=False)`,
  which issues either a full session or a partial 2FA session.

Frontend:

- `apps/web/src/features/workspaces/components/active-workspace-provider.tsx`
  — selection order `chooseWorkspace`: stored slug → `user.default_workspace_id`
  → first workspace (L28-39); `setWorkspaceBySlug` is plain React state
  (L45,69); persistence is localStorage key `"praxis.activeWorkspaceSlug"`
  (L12,22-26). **No API call on switch; `default_workspace_id` is read, never
  written.**
- `apps/web/src/components/shell/workspace-switcher.tsx` — flat dropdown,
  `onClick={() => setWorkspaceBySlug(item.slug)}` (L44-46). `is_personal` is
  already on the workspace type (badge used in `workspaces-table.tsx:91,138`).
- `apps/web/src/features/workspaces/components/create-invitation-dialog.tsx`
  — shows the raw token in a read-only `<Input>` (L98) with no copy button;
  role hardcoded `"member"` (L52).
- **No frontend accept-invite route exists.** Clipboard hook ready to reuse:
  `apps/web/src/hooks/use-clipboard-copy.ts` (`useClipboardCopy` L38).
- API conventions: one module per endpoint under `features/<feature>/api/`;
  `features/auth/api/update-current-user.ts` already wraps `PATCH /auth/me`
  and writes back `currentUserQueryKey` (L22). Auth-gated pages hang off
  `appRoute` in `src/app/router.tsx` with `lazyRouteComponent` named exports.

## Commands you will need

| Purpose  | Command | Expected on success |
|----------|---------|---------------------|
| API lint | `cd apps/api && uv run ruff check .` | exit 0 |
| API schema sanity | `cd apps/api && uv run alembic check` | "No new upgrade operations detected" (no migration in this plan) |
| API tests | `cd apps/api && uv run pytest tests/routes/auth tests/services/workspaces tests/services/auth -q` | all pass |
| Web lint | `cd apps/web && pnpm lint` | exit 0 |
| Web build | `cd apps/web && pnpm build` | exit 0 |

## Scope

**In scope:**

- `apps/api/services/auth/schemas.py` (extend `CurrentUserUpdateRequest`)
- `apps/api/services/auth/update_current_user.py` (handle
  `default_workspace_id`)
- `apps/api/services/workspaces/invitations/accept_pending_invitations_for_user.py` (create)
- `apps/api/services/workspaces/invitations/__init__.py` (re-export)
- `apps/api/services/auth/utils.py` (hook auto-accept into full-session
  issuance) — or the individual login/register/oauth/2FA services if Step 3's
  call-site check says so
- `apps/api/tests/...` (see Step 7)
- `apps/web/src/features/auth/types.ts`, `features/auth/api/update-current-user.ts`
- `apps/web/src/features/workspaces/components/active-workspace-provider.tsx`
- `apps/web/src/components/shell/workspace-switcher.tsx`
- `apps/web/src/features/workspaces/components/create-invitation-dialog.tsx`
- `apps/web/src/features/workspaces/api/accept-invitation.ts` (create)
- `apps/web/src/features/workspaces/routes/accept-invitation-route.tsx` (create)
- `apps/web/src/app/router.tsx` (register the accept route)

**Out of scope (do NOT touch):**

- No migration: `users.default_workspace_id` and all invitation columns exist.
- Invitation email delivery — tokens are still shared manually.
- Redirect-back-to-invite-URL after login (follow-up; decision 4 makes the
  flow work without it).
- A per-user "my pending invitations" list API/UI — auto-accept removes the
  need for v1.
- Workspace switcher visual polish beyond grouping (rework plan 014 already
  landed).
- `X-Workspace` header semantics and `get_current_workspace` — unchanged.

## Git workflow

- Branch: `advisor/024-workspace-default-invite-ux`
- Commit style: `API - Persist Default Workspace & Auto-Accept Invites`,
  `Web - Invite Links & Workspace Switch Persistence`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Extend `PATCH /auth/me` to set the default workspace

In `services/auth/schemas.py`, add to `CurrentUserUpdateRequest`:
`default_workspace_id: UUID | None = None`. In
`services/auth/update_current_user.py`, when the field is in
`payload.model_fields_set`:

- Reject explicit `null` with `AppValidationError(field="default_workspace_id")`
  (clearing is a system concern, not a user action).
- Validate the user has a live membership: query `WorkspaceMembership` for
  `(user_id, workspace_id, deleted == False)` joined to a non-deleted
  workspace; missing → `AppValidationError` naming the field (do not leak
  other workspaces' existence via a distinct error shape).
- Set `user.default_workspace_id`; include the field in the existing audit
  `details` changed-fields (the route already audits via
  `record_user_audit_event`).

**Verify**: `uv run ruff check .` → exit 0.

### Step 2: Create `accept_pending_invitations_for_user`

New file
`services/workspaces/invitations/accept_pending_invitations_for_user.py`:

```python
async def accept_pending_invitations_for_user(db, *, user, request=None) -> int:
```

- Select `WorkspaceInvitation` where `email == user.email`,
  `accepted_at IS NULL`, `deleted == False`, `expires_at > now()` (use the
  model's validity semantics; the email lookup rides
  `ix_workspace_invitations_email_workspace`).
- For each, call the existing `accept_invitation(db, actor=user,
  invitation=invitation, request=request)` inside `try/except Exception`:
  log a warning and continue on failure (mirror how
  `safe_record_operation_audit_event` isolates failures — a bad invite must
  not break sign-in). Return the count accepted.
- Re-export from `services/workspaces/invitations/__init__.py`.

This keeps all audit/security event behavior of the acceptance path (the
service already writes `WORKSPACE_INVITATION_ACCEPTED` security events and
audit rows).

**Verify**: `uv run ruff check .` → exit 0.

### Step 3: Hook it into full-session issuance

First **read `services/auth/utils.py` `issue_auth_response`** (L78) and list
its callers (`grep -rn "issue_auth_response" services/`). Expected callers:
password login, password register, OAuth completion, and the 2FA completion
service.

- If all full-session issuances flow through `issue_auth_response`: call
  `accept_pending_invitations_for_user(db, user=user, request=request)`
  there, **only when `require_twofa` is False** (a partial 2FA session is not
  an authenticated user yet). Place it before the response is built so the
  new memberships are queryable immediately after login.
- If the 2FA completion path does NOT go through `issue_auth_response` with
  `require_twofa=False`, add the call to that completion service as well and
  note both call sites in a short comment.

Session **refresh** must not trigger acceptance — confirm the refresh path
does not call `issue_auth_response` (if it does, gate on event type and
record that in the plan-completion note).

**Verify**: `uv run ruff check .` → exit 0.

### Step 4: Frontend — persist the switch

- Add `default_workspace_id?: string | null` to `UpdateCurrentUserRequest`
  in `features/auth/types.ts`.
- In `active-workspace-provider.tsx`, wrap `setWorkspaceBySlug`: resolve the
  workspace by slug from the loaded list, set local state + localStorage
  exactly as today, and fire the `PATCH /auth/me` mutation with the
  workspace's id **fire-and-forget** (`.catch(() => {})` semantics — a
  persistence failure must not block or revert the local switch). Reuse
  `features/auth/api/update-current-user.ts`; it already writes back
  `currentUserQueryKey`.

**Verify**: `pnpm lint` → exit 0.

### Step 5: Frontend — switcher grouping + invite dialog

- `workspace-switcher.tsx`: partition items into personal
  (`workspace.is_personal`) and team groups; render personal first under a
  small "Personal" group label, teams under "Teams" (skip labels when a group
  is empty). Keep `setWorkspaceBySlug` wiring untouched.
- `create-invitation-dialog.tsx`:
  - Add a role `<Select>` (admin / member / read_only; default member) wired
    into the create payload — display labels in Title Case per copy
    conventions.
  - On success, keep the token input and add two buttons using
    `useClipboardCopy`: **Copy code** (raw token) and **Copy link**
    (`` `${window.location.origin}/invitations/accept?token=${token}` ``).
    Show the copied state the way `message-markdown.tsx` does.

**Verify**: `pnpm lint` → exit 0.

### Step 6: Frontend — accept-invitation route

- `features/workspaces/api/accept-invitation.ts`: mutation posting
  `{ token }` to `/workspaces/invitations/accept`; on success invalidate the
  workspaces list query so the switcher refreshes.
- `features/workspaces/routes/accept-invitation-route.tsx` (named export
  `AcceptInvitationRoute`): read `token` from search params (TanStack
  `validateSearch`), auto-submit on mount, then render success (workspace
  name + a "Switch to this workspace" button calling `setWorkspaceBySlug`)
  or the error state via `getErrorMessage` in an `<Alert variant="destructive">`.
  Handle the `already accepted` / `already a member` service statuses as
  success-tier messaging, not errors.
- Register in `src/app/router.tsx` under `appRoute` as path
  `/invitations/accept` with `lazyRouteComponent`; no nav item, no breadcrumb
  branch needed (leave `getBreadcrumbs` fallback behavior as-is).

**Verify**: `pnpm lint` → exit 0 and `pnpm build` → exit 0.

### Step 7: Backend tests

- `tests/services/workspaces/test_workspace_management_services.py` (extend,
  or a sibling file if it is getting long — follow existing file intent):
  - `accept_pending_invitations_for_user` accepts a valid matching invite,
    skips expired and non-matching-email invites, and survives one invite
    raising (still accepts the rest, returns the right count).
- `tests/routes/auth/` (model on `test_registration.py` auth setup):
  - Login with a pending valid invitation → membership exists afterwards;
    security event `WORKSPACE_INVITATION_ACCEPTED` recorded.
  - Login with `require_twofa` pending → invitation NOT accepted until 2FA
    completes (only if the 2FA flow is testable with existing fixtures;
    otherwise cover the `require_twofa` guard at the unit level).
  - `PATCH /auth/me` with a workspace the user belongs to → 200,
    `default_workspace_id` persisted, audit row updated; with a workspace
    they don't belong to → 400/422 problem+json; with explicit null → 400.

**Verify**: `uv run pytest tests/routes/auth tests/services/workspaces tests/services/auth -q` → all pass.

## Test plan

Covered by Step 7 (~8–10 backend tests). Frontend has no test harness; rely
on `pnpm lint` + `pnpm build` and a manual pass: create invite → copy link →
open in a second browser/profile → login as invited email → membership
appears; switch workspace → reload on another profile with cleared
localStorage → same workspace selected.

## Done criteria

- [ ] `cd apps/api && uv run ruff check .` exits 0
- [ ] `cd apps/api && uv run alembic check` reports no new operations
- [ ] `cd apps/api && uv run pytest tests/routes/auth tests/services/workspaces tests/services/auth -q` exits 0
- [ ] `cd apps/web && pnpm lint && pnpm build` exits 0
- [ ] Switching workspace in the UI issues `PATCH /auth/me` (verify in
      devtools/network) and survives a cleared localStorage on next login
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `issue_auth_response` callers don't match Step 3's expectation (e.g. session
  refresh flows through it without a distinguishing flag).
- `CurrentUserUpdateRequest` already has `default_workspace_id` or a
  competing default-workspace route exists (someone got here first).
- The invitation model has grown a `status` column or plaintext token since
  `f83d210` (the "Current state" section is stale).
- `accept_invitation` semantics changed (email-match enforcement removed or
  membership-restore behavior different from the excerpt).
- The workspaces list or auth `me` frontend queries have moved off the
  documented query keys.

## Maintenance notes

- Plan 040 (active integration context) later attaches per-user-per-workspace
  context selections; it assumes the persisted default workspace from this
  plan. Keep the `PATCH /auth/me` membership validation authoritative.
- Follow-up (not planned): preserve the intended `/invitations/accept?token=…`
  URL through the login redirect so logged-out recipients land back on the
  accept page (today decision 2 makes the invite work anyway; the redirect is
  pure UX).
- Follow-up (not planned): invitation emails; when they arrive, the link
  format from decision 4 is the contract.
- Reviewers should scrutinize: the `require_twofa` guard (no acceptance on
  partial sessions), per-invite failure isolation in the sign-in path, and
  that the membership check in Step 1 cannot be used to probe workspace
  existence.
