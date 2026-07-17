# REVIEW.md

Focus areas for reviewing draft code in this repository — use this when
reviewing a PR or agent-produced change, and for self-review before finishing
work. Ordered roughly by risk: a tenancy leak matters more than a naming nit.

## Scope And Intent

- The change does what the task or plan asked, and no more. Flag drive-by
  refactors, new abstractions, speculative generality, and unrelated
  formatting churn.
- If a numbered plan drove the work: STOP conditions were honored, the status
  row was updated, and no plan numbers leaked into code, comments, or
  docstrings.
- Docs (README, AGENTS.md files) were updated in the same change when
  commands, routes, env vars, or architecture moved.

## Security And Tenancy

- Every new query and mutation is scoped to the active workspace, and every
  new route carries the right RBAC dependency (`require_role`/
  `require_owner`/`require_editor`/`require_read`). This is the highest-risk
  class of defect in the codebase.
- Nothing loosens CORS, cookie, CSRF, rate-limit, or provider validation, and
  no exempt lists were widened, even "temporarily" or for local convenience.
- No secrets committed or logged. Credentials resolve through the established
  seams (`provider_api_key`, the secrets provider, secret references) — never
  implicit env pickup or plaintext storage.
- Sensitive operations (workspace membership, security, approvals,
  credentials, schedules) write audit records with enough context to debug
  later.
- Any new source of untrusted content reaching model context (retrieval,
  integration-fetched data, file text) is registered in the threat model and
  exercised by adversarial fixtures before it ships.

## Agent Runtime Invariants

- All agent-callable tools go through the registry and the dispatch choke
  point — no tool execution around it, no unaudited side effects.
- External-effect tools respect run envelopes and approval policy; deferred
  approvals resume correctly, including for delegated runs.
- SSE protocol changes ship the client change first — the stream parser
  throws on unknown event names, so a new server event breaks stale clients.
- Long or free-text tool results stay bounded, and long-running work remains
  cancellable.

## Backend Conventions

- One operation per route file and per service file; package `__init__.py`
  files only compose or re-export.
- Errors raise the typed exceptions in `core/exceptions`, not ad-hoc
  `HTTPException`.
- Schema changes are Alembic migrations on the correct branch (`core` for
  platform infrastructure, `app` for verticals); nothing mutates schema at
  startup.
- Request paths stay async with no blocking calls; runtime HTTP uses
  `httpx2`, with plain `httpx` confined to dev and tests.
- New middleware respects the ordering comment in `apps/api/main.py`.

## Frontend Conventions

- All requests go through `src/lib/api/client.ts`; no direct `fetch` in
  features. Query keys are workspace-scoped and mutations invalidate or seed
  the cache correctly.
- Layering violations are fixed by restructuring, not by editing
  `.dependency-cruiser.cjs`.
- Forms stay native HTML + `FormData` with `src/lib/forms.ts`; no form or
  schema-validation libraries. Types are hand-written `type` aliases in the
  feature's `types.ts`.
- UI uses shadcn primitives, stays dense and practical, and copy speaks to a
  non-technical operator in outcome language. Per-tool-call UI renders inline
  in the tool row. No scaffold copy or placeholder assets remain.

## Tests And Verification

- Test coverage is proportional to risk — auth, permissions, audit records,
  scheduling, migrations, approvals, and provider boundaries come first.
- Tests live in the right place: `apps/api/tests/<intent>/` on the backend,
  `apps/web/tests/` mirroring source paths on the frontend, never colocated
  under `src/`.
- Backend tests use the shared fixtures, factories, and support helpers
  rather than hand-rolled setup; nothing makes live LLM calls.
- The relevant checks were actually run (`make check`, or the focused
  subset), results are reported honestly, and anything skipped is called out.

## Code Quality

- No duplication. New code does not copy-paste logic that already exists, and
  does not re-implement it with slight variations — the drift between copies
  is where bugs breed. If similar logic already lives elsewhere, the change
  should call it, extract it, or explain why it genuinely differs.
- Helpers go in the shared home, not the bottom of the file. A two-or-three
  line utility appended to every file that needs it is duplication in
  disguise. Reusable logic belongs in the established shared locations —
  `apps/api/utils/` or the service's `utils.py` on the backend; `src/lib/`
  (forms, formatting, query-key factories) on the frontend — as a single
  generic, well-named function.
- Watch the per-feature scaffolding especially. Both apps are built as
  parallel vertical features, and their shared plumbing (query keys,
  pagination, validation helpers, formatters) has been deliberately
  consolidated; reject changes that fork a feature-local copy of it.
- The inverse also holds: do not force an abstraction over two things that
  merely look alike. Extract when the logic is genuinely the same and a third
  caller is plausible; a premature generic helper is its own maintenance
  burden.
- The change reads like the surrounding code: same patterns, naming, and
  comment density. Comments are terse and state only what the code cannot.
- No dead code, unused exports, or lint/typecheck warnings introduced.
- Failure paths are handled where they can be acted on and are observable —
  errors surface through the exception layer or UI states, not silent
  swallows.
