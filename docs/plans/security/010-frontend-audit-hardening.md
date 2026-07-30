<!-- docs/plans/security/010-frontend-audit-hardening.md -->

# Frontend Security Audit — Hardening Tasks

Written 2026-07-30 from an external discovery-stage audit of the frontend
(28 raw candidate rows). Every row was re-verified against the working tree at
HEAD `b11cc61` before landing here: findings that turned out to be already
fixed, or weaker than reported, are recorded as such rather than dropped.

This is a defect-remediation list, separate from the dependency-maintenance
runbook in this directory's `README.md`. It is not a roadmap lane; do not add
these numbers to `docs/plans/000_MASTER_ROADMAP.md`.

The 28 candidates collapse to **8 distinct defects, 1 rejected finding, and 1
already-fixed finding**. Twelve of the raw rows were the same root cause
reported once per reachable sink; they are S1 below.

| # | Task | Severity | Effort | Area | Raw rows |
| --- | --- | --- | --- | --- | --- |
| [S1](#s1--oauth-callback-provider-is-injected-into-an-api-path) | OAuth callback `provider` is injected into an API path | **Critical** | S | web | 4–15 |
| [S2](#s2--safe_next_path-accepts-a-backslash-open-redirect) | `safe_next_path` accepts a backslash open redirect | **High** | S | api | 23 |
| [S3](#s3--concurrent-turns-can-start-two-runs-on-one-conversation) | Concurrent turns can start two runs on one conversation | **High** | M | api | 16 |
| [S4](#s4--logout-leaves-user-private-data-in-the-query-cache) | Logout leaves user-private data in the query cache | **High** | S | web | 1, 20, 21, 22 |
| [S5](#s5--approval-cards-hide-arguments-that-approval-executes) | Approval cards hide arguments that approval executes | **High** | M | cross | 17, 18, 19 |
| [S6](#s6--read-only-context-selection-is-intended) | Read-only context selection is intended — **rejected** | — | S | cross | 26 |
| [S7](#s7--inline-html-previews-ship-without-their-own-csp) | Inline HTML previews ship without their own CSP | **Medium** | S | web | 24, 25 |
| [S8](#s8--approval-controls-bind-to-tool-calls-by-id-alone) | Approval controls bind to tool calls by id alone | **Medium** | S | web | 3 |
| [S9](#s9--totp-cannot-be-completed-at-sign-in) | TOTP cannot be completed at sign-in | **Medium** | M | web | 27 |
| [—](#closed--pending-invitation-survives-membership-revocation) | Pending invitation survives revocation — **already fixed** | — | — | — | 2 |

Suggested order: S1 and S2 first (both are small and both are externally
reachable), then S4, then S3 and S5. S7–S9 are follow-up work.

---

## S1 — OAuth callback `provider` is injected into an API path

**Severity: Critical. Effort: S.**

### What is wrong

`providerFromState` base64-decodes the middle segment of the OAuth `state`
parameter and returns `payload.provider` with no validation
(`apps/web/src/features/auth/oauth-callback.ts:56-72`). The state is never
signature-checked on the client, so an attacker controls that string outright.
`readOauthCallback` uses it whenever the `sessionStorage` provider key is
absent (`oauth-callback.ts:46`) — which is the normal condition for any tab
that did not itself start the OAuth flow.

Both callback loaders interpolate the result straight into an API path:

- `apps/web/src/features/auth/api/oauth-link.ts:26` — `` `/auth/oauth/${provider}/link/callback` ``
- `apps/web/src/features/auth/api/oauth-login.ts:37` — `` `/auth/oauth/${provider}/callback` ``

`buildUrl` then resolves that with `new URL()`
(`apps/web/src/lib/api/client.ts:24-27`), which performs RFC 3986 dot-segment
removal. A provider of `../../files/<file-id>/purge?x=` becomes
`POST {apiBaseUrl}/files/<file-id>/purge`, with the intended `/link/callback`
suffix harmlessly absorbed into the query string.

The request carries the victim's cookies (`client.ts:67`) and a valid CSRF
token (`client.ts:58-62`). Double-submit CSRF does not help here: the forged
request originates *inside* the app's own origin, because the victim navigated
to the app's own callback route, so the SPA attaches a genuine token read from
the `csrf` cookie (`apps/web/src/lib/api/csrf.ts:17-20`).

### Why it matters

Every state-changing `POST` that takes no required body becomes reachable as
the victim. Confirmed targets include `files/{id}/purge` (hard delete —
`apps/api/routes/files/purge_file.py:16`), `schedules/{id}/{enable,pause,run-now}`,
`integrations/connections/{id}/{revoke,refresh,test,discover}`,
`artifacts/{id}/versions/{v}/restore`, `agent-runs/{id}/cancel`,
`kb/documents/{id}/reprocess`, and `workspaces/invitations/{id}/accept`.

Two preconditions are worth measuring before assigning a final severity,
because they split the target list in two:

- The route sits under `appRoute` (`apps/web/src/app/router.tsx:447-459`), so
  the victim must be signed in — unauthenticated visitors are redirected to
  `/login` by `appRoute.beforeLoad` (`router.tsx:99-106`).
- Workspace-scoped targets additionally need the `X-Workspace` header.
  `setActiveWorkspaceSlug` is called during `ActiveWorkspaceProvider`'s render
  (`apps/web/src/features/workspaces/components/active-workspace-provider.tsx:63`),
  which happens *after* route loaders run. On a cold navigation from an
  external link the module variable is still `null`, so those requests should
  be rejected; on an in-app navigation (the variable is never reset) they are
  not. **Verify this before downgrading anything** — it is the difference
  between "needs the victim already browsing" and "one click from an email".
  `workspaces/invitations/{id}/accept` needs no workspace header at all
  (`apps/api/routes/workspaces/invitations/accept_invitation_by_id.py:19-25`),
  so it is exploitable on a cold load regardless.

### What to do

1. Validate the provider in `readOauthCallback` before returning it — reject
   anything that is not `/^[a-z0-9_-]{1,64}$/`. Apply it to the
   `sessionStorage` value too, not just the state-derived one. Returning
   `null` makes both loaders fall into their existing "missing required
   information" branch, so no new error path is needed.
2. `encodeURIComponent(provider)` at both interpolation sites
   (`oauth-link.ts:14,26`, `oauth-login.ts:30,37`).
3. **Class fix — do this one regardless of 1 and 2.** In `buildUrl`, assert the
   resolved `url.pathname` still starts with the API base's pathname, and throw
   if not. Many `apiRequest` call sites interpolate values into template paths;
   this closes the whole category rather than this instance.

Also consider deleting the `providerFromState` fallback outright. The provider
is written to `sessionStorage` before every redirect
(`sign-in-methods.tsx:48`, `oauth-login-providers.tsx:39`) and `sessionStorage`
survives the round trip in the same tab, so the fallback only covers a
cross-tab landing — decide whether that case is worth an attacker-controlled
input path.

### Verify

Extend `apps/web/tests/features/auth/oauth-secondary-callback-loaders.test.ts`
and `oauth-login-callback-loader.test.ts` with a traversal state payload;
assert the loader returns the error branch and that `completeOauthLink` /
`completeOauthLogin` are never called. Add a unit test for `buildUrl` asserting
that a path escaping the API base throws.

---

## S2 — `safe_next_path` accepts a backslash open redirect

**Severity: High. Effort: S.**

### What is wrong

`safe_next_path` rejects a scheme, a netloc, or a missing leading slash using
Python's `urlparse` (`apps/api/services/integrations/oauth/utils.py:88-94`).
Python treats `/\attacker.example/x` as an ordinary relative path — empty
scheme, empty netloc, leading slash — so it passes all three checks and gets
signed into the OAuth state.

The browser disagrees. `fullDocumentRedirect` resolves it with
`new URL(path, window.location.origin)`
(`apps/web/src/lib/full-document-redirect.ts:7`), and the WHATWG URL parser
treats `\` as `/` for special schemes. The path enters the authority-ignore
state and `attacker.example` is parsed as the **host**, producing
`https://attacker.example/x`. The sink is
`apps/web/src/features/integrations/routes/oauth-callback-loader.ts:41`, which
passes `response.next_path` through unvalidated.

**There are two byte-identical copies of this helper** and both are vulnerable:
`services/integrations/oauth/utils.py:88` and
`services/auth/oauth/utils.py:332`.

Note for anyone reading the working tree: the uncommitted diff in
`services/auth/oauth/utils.py` is unrelated — it wraps the login binding cookie
in `encrypt_data`/`decrypt_data`. No backslash guard is in flight.

### Why it matters

The victim lands on an attacker-controlled origin immediately after a genuine
provider consent screen, which is about the highest-credibility phishing
context the product can produce.

### What to do

Collapse the two copies into one shared helper and have it reject `\` outright
(and any control or whitespace character) before the `urlparse` checks. Prefer
rejecting over sanitizing. Add a client-side guard at the redirect sink as
defense in depth: `fullDocumentRedirect` should refuse a resolved URL whose
origin differs from `window.location.origin`.

### Verify

`apps/api/tests/services/integrations/test_oauth_state.py:112` covers the
existing cases but not this one. Add `/\attacker.example/x`,
`/\\attacker.example/x`, and `//attacker.example/x` to that table, and mirror
it for the auth copy.

---

## S3 — Concurrent turns can start two runs on one conversation

**Severity: High. Effort: M.**

### What is wrong

The "one active run per conversation" rule is an unlocked check-then-insert.
`create_turn_stream` reaps abandoned runs, reads the active run, and raises
`ConflictError` if it finds one
(`apps/api/services/conversations/create_turn_stream.py:70-80`), but the read
takes no lock — `apps/api/services/conversations/utils.py:100-109` is a plain
`select(...).limit(1)`, and the conversation row is not locked either
(`utils.py:48-55`). The insert is an unconditional `db.add` + `flush`
(`apps/api/services/agent_runs/create.py:41-54`).

There is no uniqueness backstop. `apps/api/models/agent_run.py:99-131` defines
five constraints; the one with a non-terminal-status predicate
(`ix_agent_runs_lease_expiry`, `:120-124`) is non-unique and keyed on
`lease_expires_at`, not `conversation_id`.

Two concurrent `POST /conversations/{id}/turn` with distinct
`client_message_id` both pass the check, both commit at
`create_turn_stream.py:136`, and both spawn `run_turn_worker` (`:140-150`).
The client-message dedupe at `:82-99` is also an unlocked read and keys on the
message, not the run.

This was **not** fixed by `b7ba76e` "API - Job Concurrency" — that commit
touched only `models/jobs.py`, `services/jobs/`, and migration `0029`.

### Why it matters

Two workers interleave writes into one shared transcript, duplicate model and
tool spend, and race each other's approval state. The failure is silent.

### What to do

Take a `pg_advisory_xact_lock` on the conversation id around the
check-and-insert. The pattern is already in the codebase —
`services/kb/write_policy.py:60` and `services/memories/utils.py:202` — so
follow those rather than inventing a new one. Back it with a partial unique
index on `(conversation_id)` where `deleted = false AND status IN
('pending','running','awaiting_approval')` so the invariant survives a future
code path that forgets the lock.

### Verify

Add a concurrency test alongside
`apps/api/tests/services/conversations/test_create_turn_stream.py` that fires
two turn creations against one conversation and asserts exactly one succeeds
and the other raises `ConflictError`.

---

## S4 — Logout leaves user-private data in the query cache

**Severity: High. Effort: S.**

**Status: READY FOR REVIEW — implementation complete and the full frontend gate passes.**

### What is wrong

The `QueryClient` is created at module scope (`apps/web/src/app/App.tsx:9`) and
lives for the tab's lifetime. Logout removes exactly two keys — `["auth","me"]`
and `["workspaces","list"]` (`apps/web/src/features/auth/api/logout.ts:20-23`).
There is no `queryClient.clear()` anywhere in the codebase. Sign-out then does
an SPA navigation, not a reload (`app-shell.tsx:32-38`).

Query keys are scoped by workspace slug and never by user identity
(`apps/web/src/lib/workspace.ts:19-32`). `["auth","identities"]` is worse — it
is scoped by nothing at all (`get-identities.ts:8`) and holds linked-provider
emails.

The mechanism is stronger than "stale data renders briefly". Route loaders use
`queryClient.ensureQueryData` (`router.tsx:106, 175-200, 269-306, 347-420`),
which returns cached data with **no network request and no revalidation**
regardless of `staleTime`. So the second user's route load resolves
synchronously from the first user's entries.

Scope corrections against the raw report:

- **Password login is the vector** (`login-route.tsx:40` navigates in-SPA).
  **OAuth login is immune** — `oauth-login-callback-loader.ts:60` returns
  `fullDocumentRedirect("/")`, which reloads the document.
- The retention window is the default `gcTime` of 5 minutes, not the 5–60s
  `staleTime` values. `apps/web/src/app/query-client.ts:7-20` sets no
  `staleTime` and no `gcTime` default.
- `setActiveWorkspaceSlug` is never reset at logout either, so the module
  variable still holds the previous user's slug when the next user's loaders
  run — meaning their first requests can also carry the **previous user's
  `X-Workspace` header**. Worth checking what the backend does with that.

### Why it matters

On a shared browser, user B can be shown user A's conversation titles and
transcripts, integration connection lists, and linked-identity emails. The
backend is correct throughout — every conversation query is actor-scoped
(`apps/api/services/conversations/list_conversations.py:26-39`) — so this is
purely retained client state defeating a boundary the server enforces.

### What to do

Call `queryClient.clear()` on logout, clear `praxis.activeWorkspaceSlug` from
`localStorage`, and call `setActiveWorkspaceSlug(null)`. Then make the sign-out
navigation a full document reload so nothing survives in module state — that
also matches what the OAuth login path already does.

Belt and braces: add the user id to the workspace-scoped key factory in
`lib/workspace.ts` so a stale entry can never key-collide across accounts.

### Verify

Add a test asserting the logout mutation empties the cache and resets the
active workspace slug. A manual check is worth doing too: sign in as A, open a
conversation, sign out, sign in as B via password, and confirm nothing of A's
renders.

---

## S5 — Approval cards hide arguments that approval executes

**Severity: High. Effort: M.**

**Status: READY FOR REVIEW — implementation complete and the full frontend gate passes.**

### What is wrong

When a tool declares `arg_fields`, the approval card renders **only** those
fields. `ApprovalRequestFields` uses `fallbackFields` only when
`fields.length === 0` (`apps/web/src/components/tool-ui/approval-card.tsx:237-250`),
and `tool-call-row.tsx:76-78` picks the declared list over the show-everything
`autoUiFields` path. A declared `arg_fields` list is therefore a strict
whitelist of what a human sees.

Approving without editing sends `override_args: null`
(`apps/web/src/features/conversations/approval-decisions.ts:102-104`), and the
backend then replays the **full original argument set** —
`_effective_tool_args` returns `override_args if override_args is not None else
original_args` (`apps/api/services/agents/runtime/approval_events.py:337-339`).
So the hidden arguments execute exactly as the model emitted them.

Two concrete tools are affected:

- **`save_memory`** raises `ApprovalRequired` specifically when `kind ==
  "core"` (`apps/api/services/agents/runtime/tools/memory.py:114-115`) but
  declares only `title` and `content` (`:95-98`). The attribute that *caused*
  the approval is not shown, and neither are `scope`, `memory_type`,
  `importance`, `expires_in_days`, `duplicate_of`, or `save_as_new`.
- **`write_file`** declares only `name` and `content` (`write_file.py:66-74`),
  hiding `file_id` and `expected_current_revision_id`. On the edit branch
  `write_agent_file` never reads `name` at all — it is used only on the create
  path (`apps/api/services/files/write_agent_file.py:50-91`). So on an
  overwrite, the one field the human sees has no effect and the actual target
  is invisible. The prompt text reinforces the wrong model: *"The agent wants
  to save {name} to your workspace files"* (`write_file.py:64`), rendered even
  when the call overwrites a different existing file.

Compounding it, the registry falls back to the generic row while a decision is
pending: a presenter runs only if `approvalDecision === undefined ||
handlesApprovals === true`, and only `delegation` sets that flag
(`tool-call-row-registry.tsx:114, 193-198`). So the warning-styled **Core**
badge in `memory-tool-row.tsx:321-327` is unreachable at the decision point —
it appears only afterwards, on the result card.

The API is not the problem: `file_id`, `expected_current_revision_id`,
`content_bytes`, and `content_sha256` are all present in the display payload
(`staged_tool_content.py:200-204`). The UI whitelist drops them.

### Why it matters

`docs/architecture/threat-model.md:91-97` records the operator decision that
agent memory is a **trusted control surface**, with "approval for core writes"
named as one of the governing controls. That control is currently
approve-without-disclosure: a core write is the one memory operation that
becomes persistent runtime prompt state, and it is the one fact the card omits.
Tool arguments are model-authored and therefore untrusted, so complete display
of security-significant bound arguments is part of the approval boundary, not
cosmetics.

### Bonus defect found during verification (not in the audit)

Editing the file name on a staged `write_file` approval corrupts the replay.
`buildMergedArgs` spreads the **display** args
(`approval-decisions.ts:128`), which for a staged write are `{name, file_id?,
expected_current_revision_id?, content: "[staged for approval; content
omitted]", content_bytes, content_sha256}`. That replaces the correct staged
args — which carry `content_ref` and no `content` — with a payload that has no
`content_ref`, a `content` equal to the literal redaction marker, and two
kwargs that are not in the `write_file` signature (`write_file.py:81-88`).
Nothing on the resume path reconciles it (`resume_run_stream.py:200`). The
result is either a schema rejection or a durable file whose contents are the
string `[staged for approval; content omitted]`. No test covers an edited
`write_file` approval.

### What to do

1. Render undeclared arguments in a collapsed "other arguments" section rather
   than dropping them, so `arg_fields` becomes display *ordering* rather than a
   security whitelist.
2. Add `kind` and `scope` to `save_memory`'s declared fields, and `file_id` /
   `expected_current_revision_id` to `write_file`'s. Make the write_file
   approval sentence reflect create-vs-overwrite.
3. Let the memory and file presenters handle approvals (`handlesApprovals:
   true`) so the Core badge and file target survive to the decision point.
4. Fix `buildMergedArgs` to merge edits over the **staged replay args**, not
   the display projection.

### Verify

`apps/web/tests/components/tool-ui/approval-decision-fields.test.ts` and
`apps/web/tests/features/conversations/approval-decisions.test.ts` are the
right homes. Add a backend test for an edited `write_file` approval asserting
the staged bytes are what land on disk.

---

## S6 — Read-only context selection is intended

**Severity: Rejected. Effort: S.**

**Status: READY FOR REVIEW — the finding was rejected and inconsistent gates
were corrected.**

### Decision

The reported behavior is the intended policy, not a role-gate bypass. Every
active workspace member, including `read_only`, may select the integration
context available to their own conversation. Context selection narrows which
provider resources read-effect tools may use; it does not grant permission to
perform write effects. Tool dispatch continues to enforce the member's role
for each invocation.

The implementation was inconsistent with that policy: direct conversation
creation already allowed the selection, while the dedicated set/clear routes
required `EDITOR_ROLES` and the frontend disabled both pickers for
`read_only`. Those restrictions prevented read-only members from selecting
context after conversation creation even though they may use read-effect
integration tools.

### What changed

- The set and clear context services now require an active membership in
  `READ_ROLES`, covering every caller without excluding `read_only`.
- The dedicated set and clear routes use `require_read`.
- The existing- and new-conversation context pickers no longer disable
  themselves solely because the member is `read_only`.
- Conversation ownership and workspace resource/group validation remain
  unchanged.

### Verify

Tests assert that a `read_only` member can set and clear context on their own
existing conversation and can create a conversation with `active_context`
persisted.

---

## S7 — Inline HTML previews ship without their own CSP

**Severity: Medium. Effort: S.**

**Status: READY FOR REVIEW — implementation complete and the full frontend gate passes.**

### What is wrong

Two components inject untrusted HTML into an iframe `srcDoc` with
`sandbox="allow-scripts"` and no CSP of their own:

- `apps/web/src/features/artifacts/components/artifact-preview-frame.tsx:17-25`
- `apps/web/src/features/files/components/file-content-view.tsx:29-38`
  (triggered by `text/html` or an `.html`/`.htm` name, `:58` and `:65`;
  `text/html` is an agent-writable editable-text type per
  `apps/api/services/files/contract.py:67-74`)

The backend's dedicated artifact-serving path *does* set a real CSP with
`connect-src 'none'` (`apps/api/services/artifacts/domain.py:45-63`, applied at
`serve_artifact_version.py:42-53`) — but response headers cannot reach a
`srcdoc` document, so the inline path is strictly weaker than the served path.

The repo already has the right pattern. The Gmail preview injects a meta CSP
into its `srcDoc` (`apps/web/src/integrations/gmail/components/message-preview.tsx:18,90`)
with `default-src 'none'; img-src data: https: http: cid:; style-src
'unsafe-inline'` — tuned to keep images on, per the product decision to render
provider content faithfully. The artifact and file previews never got the same
treatment.

### Scope corrections against the raw report

- `allow-same-origin` is absent everywhere in `apps/web/src`, so the frames run
  on an opaque origin. Parent DOM, `localStorage`, and cookies are unreachable.
  The ceiling is script execution plus egress of data already inside the
  artifact or file — not session theft.
- `about:srcdoc` documents inherit the embedder's CSP. The shipped container
  serves the shell with `default-src 'self'; script-src 'self'; connect-src
  'self' <apiOrigin>` (`apps/web/docker/render-nginx-config.mjs:33-48`), and in
  an opaque origin `'self'` matches nothing — so both inline script and egress
  are already blocked there. `apps/web/index.html` has no meta CSP and
  `vite.config.ts` sets no dev headers, so **under `vite dev` and behind any
  other reverse proxy there is no inherited policy at all.** Treat this as a
  real defense-in-depth gap, not as unconditional egress.
- "Requires an explicit expand" is only true for the non-approval conversation
  row. The artifact detail page renders the frame unconditionally
  (`artifact-detail.tsx:118-122`), the file detail modal renders on open
  (`file-detail-modal.tsx:169`, `:347-348`, `:423-428`), and any tool row
  carrying an approval decision auto-expands
  (`tool-call-row.tsx:57-58`) — which is exactly the artifact and file writes.

### What to do

Extract the Gmail preview's document-wrapping helper into something shared and
use it for all three surfaces. Artifacts and files should get `connect-src
'none'` to match what the served path already guarantees.

### Verify

`apps/web/tests/features/artifacts/components/artifact-preview-frame.test.ts`
already asserts `sandbox="allow-scripts"` without `allow-same-origin`; add an
assertion that the injected document carries the CSP meta tag.

---

## S8 — Approval controls bind to tool calls by id alone

**Severity: Medium. Effort: S.**

**Status: READY FOR REVIEW — implementation complete and the full frontend gate passes.**

### What is wrong

Parsed messages carry `agentRunId` (`message-parts/parse.ts:158`,
`message-parts/types.ts:56`) but it is consumed **only** for visual turn
grouping (`group-render-items.ts:44, 65, 70, 84-85`). It participates in no
join. Every merge is `tool_call_id`-only:

- live results — `parse.ts:99`, map built at `message-list.tsx:92-93`
- pending delegations — `parse.ts:55`, read at `:69`
- approvals — `use-inline-approvals.ts:34-37`, gated at `:84` on
  `approvalsById.has(activity.id)`; `ToolActivity` carries no run identity at
  all, so no run comparison is even possible at that call site
- live-vs-transcript dedupe — `message-list.tsx:130`

Worse, the `awaiting_approval` transition is a single global flag rather than
per-run: `parse.ts:60` computes `runAwaitsApproval` from the active run's
status and applies it at `:107-112` to *any* unresolved call activity in *any*
message in the transcript.

Call-to-result pairing is safe — `pair-tool-results.ts:41-50` pairs
positionally by `${messageIndex}:${activityIndex}` — but that only covers
already-persisted results.

### Why it matters

A reused `tool_call_id` from an earlier unresolved call renders that call's
arguments above approval controls that resume the *current* invocation. The
wire payload stays correct (`buildResumeDecisions` is built from the server's
approvals list, `use-inline-approvals.ts:46`), so this is a display-integrity
defect: the human approves something other than what they were shown. Same
class as S5, different mechanism.

Ids are provider-assigned rather than attacker-chosen, so **how likely reuse
actually is under your provider needs a runtime check**. The missing guard is
definitively confirmed; the trigger rate is not.

### What to do

Include `agentRunId` in the approval and live-result joins, and scope
`runAwaitsApproval` to activities belonging to the active run. `ToolActivity`
will need to carry run identity for the `use-inline-approvals` gate to be able
to compare at all.

---

## S9 — TOTP cannot be completed at sign-in

**Severity: Medium (availability, not attacker-facing). Effort: M.**

### What is wrong

The backend endpoint exists and works: `POST /auth/totp/verify`
(`apps/api/routes/auth/totp/verify_totp.py:14`), consuming the partial session
and calling `upgrade_partial_session`
(`apps/api/services/auth/totp/verify_totp.py:34-46, 80`).

The SPA never calls it. `apps/web/src/features/auth/api/totp.ts` contains
exactly three endpoints — setup (`:10`), enable (`:14`), and delete (`:21`).
Greps for `auth/totp/verify`, `verifyTotp`, and `verify_totp` across
`apps/web/src` return nothing.

Both `requires_twofa` consumers dead-end in copy rather than a form.
`login-route.tsx:36-39` sets `twoFactorPending` and renders an alert at
`:71-79` reading *"Entering a verification code will be available with account
security settings."* The OAuth path does the same
(`oauth-login-callback-loader.ts:56-58` → `oauth-login-callback-route.tsx:35`).

### Why it matters

Any user who completes enrollment is stranded on a partial session at next
sign-in, on both the password and OAuth paths, with no in-product recovery.
The acknowledging copy suggests this is known-incomplete rather than a
regression — but TOTP is currently a lockout switch, and three commits
(`e136304`, `11f9b34`, `5d23e69`) have hardened a flow that cannot be
completed.

### What to do

Either build the verification form and wire it to `/auth/totp/verify`, or hide
enrollment behind a flag until it exists. Shipping an enable button whose
success condition is "you can no longer sign in" is the worse of the two.

---

## Closed — Pending invitation survives membership revocation

Raw row 2 claimed that inviting a user, adding them directly, then removing
them left the original invitation token live. **This was fixed in `b11cc61`
"API - Invitation Hardening", shortly before the audit ran.**

`create_membership` now selects matching non-accepted, non-deleted invitations
`.with_for_update()` and soft-deletes each
(`apps/api/services/workspaces/memberships/create_membership.py:49-79`), with
`revoked_invitation_ids` recorded in both the audit and security events
(`:113`, `:126`). Token acceptance requires `deleted.is_(False)`
(`accept_invitation_by_token.py:36-38`), so the revoked token now resolves to
"Invalid or expired invitation link".

The surrounding mechanism the row described is all still real — membership
deletion is a soft delete (`delete_membership.py:52`) and acceptance restores a
soft-deleted membership with the *invitation's* role
(`accept_invitation_utils.py:98-101`). Only the middle link was severed.

**One residual worth a follow-up:** the revocation join is an exact string
match on `WorkspaceInvitation.email == user.email`
(`create_membership.py:55`), whereas acceptance normalizes with
`.strip().lower()` (`accept_invitation_utils.py:67-68`). Both write paths
normalize today (`services/workspaces/schemas.py:134-137`), so it holds — but
it is a latent trap if any invitation email is ever persisted un-normalized.
Consider normalizing on both sides of that comparison.
