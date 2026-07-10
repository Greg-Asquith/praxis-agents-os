# Plan 056: Context compaction — watermark summaries and token-aware budgets

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/history.py apps/api/services/agents/runtime/capabilities.py apps/api/services/agents/runtime/prompt.py apps/api/services/agents/models/registry.py apps/api/services/jobs/ apps/api/core/settings/agents.py`
> Compare the "Current state" excerpts against live code; treat a mismatch
> in the trim-watermark math, the `ProcessHistory` mounting, or the jobs
> harness contract as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED-HIGH (touches what the model sees; a bad summary silently
  degrades every long conversation, and a cache-unstable injection
  quietly doubles token spend)
- **Depends on**: 013 (trimming, DONE), 018 (assembler, DONE), 030 (jobs,
  DONE). **Hard ordering: before 048/049 land** — memory injection and
  the 040 context block will compete for the same window; the token-aware
  budget seam must exist first. Soft: 055 (compaction scenarios go in the
  scenario suite).
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

Plan 013 bounded context by *truncation*: `trim_history` drops everything
before a chunked user-turn watermark, preserving only re-synthesized
`LoadCapability` pairs. Nothing summarizes what was dropped — a
40-turn-old decision is simply gone. Prompt-block budgets are character
counts (`prompt.py:80-92`), only `available_files` sets one, and the
per-run total token cap ships disabled
(`AGENT_RUN_TOTAL_TOKENS_LIMIT` default `None`). This was the right v1;
it stops being right when scheduled agents accumulate daily context and
Phases 4/5 add context/memory blocks to the same window.

Decision taken with the operator (2026-07-07): keep the cache-first
design — the trim watermark exists *because* provider prompt caching
rewards a stable prefix — and extend it with summarization that is
**cache-stable by construction**: summarize only the span *below* the
watermark, generate the summary **out-of-band** (jobs harness), key it to
the watermark position so it only changes when the watermark advances,
and inject the stored summary at trim time. Trigger compaction by token
estimate against the model's catalog `context_window`, not turn counts
alone.

## Decisions taken

1. **Summaries are generated out-of-band, never in the turn path.** When
   a turn's trim drops messages at watermark W and no summary exists for
   (conversation, W), the runtime enqueues a
   `conversations.summarize_history` job (030 harness; subject =
   conversation id, content-hash = watermark key — the harness's
   kind × subject × hash dedup gives idempotency for free) and this turn
   proceeds with the plain 013 trim. The next turn at the same watermark
   injects the stored summary. Zero added latency; graceful absence.
2. **Summary storage: one row per (conversation, watermark).**
   New core-branch table `conversation_summaries`: `conversation_id`,
   `watermark_key` (a stable identifier of the cut — the message id of
   the first *kept* boundary message, not an index, so DB-window changes
   don't shift it), `content` (text, hard cap
   `AGENT_HISTORY_SUMMARY_MAX_CHARS`, default 2000), `source_message_count`,
   `model_name`, timestamps. Prior-watermark rows for the conversation
   are superseded (kept for debugging, swept with the conversation).
   Summaries are derived data — deleting them is always safe.
3. **Injection shape mirrors the capability-pair re-synthesis.** The
   trimmer inserts the summary immediately after `kept[0]` (alongside the
   synthetic capability messages, before `kept[1:]`) as a synthetic
   history message framed as prior-conversation context, marked so it is
   never persisted back and never mistaken for user authority
   ("Summary of earlier conversation (automatic):" prefix; data, not
   instructions). Chained compaction (summarizing a span that itself
   starts with a summary) folds the prior summary into the new job's
   input — summaries never stack in the prompt; at most one is present.
4. **The summarizer is the cheap-model seam, not the agent's model.**
   Follow the conversation-naming pattern
   (`services/conversations/naming.py`): settings-pinned provider/model
   (`AGENT_HISTORY_SUMMARY_MODEL_PROVIDER`/`_MODEL`, defaulting to the
   naming model's class of cheap model), resolved through the normal
   catalog/factory seam. The job prompt asks for: decisions taken, open
   threads, user preferences/facts stated, artifacts/files touched —
   bounded to the char cap. Live-LLM blocking in tests stays: job handler
   tests script the model with `FunctionModel`/`TestModel`.
5. **Token-aware triggering, character-approximate accounting.** A new
   `estimate_tokens(text) -> int` helper (`utils/`, chars//4 heuristic —
   no tokenizer dependency; recorded as approximate) plus
   `registry.py`'s `context_window` drive a second trim trigger: when the
   estimated prompt (system blocks + history) exceeds
   `AGENT_HISTORY_CONTEXT_FRACTION` (default 0.6) of the resolved model's
   window, trimming tightens (drop to the *next* watermark even if
   `max_turns` is satisfied). Turn-count limits remain as the floor;
   token pressure only ever trims more, preserving watermark chunking
   (never a mid-chunk cut, which would thrash the cache).
6. **The per-run token cap gets a real default.**
   `AGENT_RUN_TOTAL_TOKENS_LIMIT` flips from `None` to a default sized
   generously against the largest catalog window (proposed: 2_000_000
   total tokens per run — a runaway-loop backstop, not a usage quota;
   workspace-level LLM budgets are a separate governance §4 follow-up,
   noted, not implemented here). Local/dev envs may override to `None`.
   `UsageLimitExceeded` handling (011) already persists capped runs.
7. **Prompt-block budgets stay character-based but become uniformly
   settings-driven**, and `build_system_prompt` logs one aggregate
   estimated-token figure per assembly (observability for 014's spans to
   pick up). Making every block token-budgeted with a real tokenizer was
   considered and rejected: a tokenizer dependency per provider buys
   little while the injected blocks are bounded and small; revisit if 040/
   049 blocks blow past their budgets in practice.

## Amendment (plan 076, 2026-07-10): consume the calibrated estimator

Plan 076 implements `utils/tokens.py::estimate_tokens` before this plan
runs and adds `ModelInfo.chars_per_token` to the model catalog. Decision 5
must consume that shared helper with the resolved model's catalog value;
do not recreate the earlier `chars//4` sketch in this plan. The helper
counts non-ASCII characters conservatively and keeps provider-specific
recalibration offline, without adding a tokenizer or a provider round-trip
to the turn path. Plan 076 also bounds oversized free-text tool results at
dispatch production time, so this plan continues to own multi-turn pressure
and summaries only; it must not retroactively edit stored tool results.

## Why this matters

Compaction is the difference between "agents with a 20-turn memory" and
"agents that hold long-running work". It is also a spend control: the
cache-stable design means long conversations keep >90% of their prompt
cached across turns, while the token-aware trigger prevents the
window-overflow failures that would otherwise appear exactly when a
conversation matters most (it got long because it was useful). Landing it
before memory injection (049) means the window's tenants — history,
summaries, memories, active context — are budgeted in one designed pass,
per the roadmap's Context pillar.

## Current state

All anchors verified on the working tree at `c2f08cc` (2026-07-07).

- **Trimming**: `services/agents/runtime/history.py` — `trim_history`
  (21-60): splits the current-run tail (91-102), finds clean user
  boundaries (79-88), chunked watermark math
  `((len(boundaries) - keep) // (max-keep)) * (max-keep)` (38-40),
  re-synthesizes dropped capability pairs as one synthetic
  response+request pair inserted after `kept[0]` (43-59) — decision 3
  deliberately mirrors this exact insertion point. Mounted via
  `ProcessHistory(history_trimmer())` (`capabilities.py:31`);
  `history_trimmer` reads live settings per call (63-76).
- **Settings**: `core/settings/agents.py` — `AGENT_HISTORY_MAX_TURNS=40`
  (nullable disables trimming), `AGENT_HISTORY_KEEP_TURNS=20`,
  `AGENT_HISTORY_DB_MAX_MESSAGES=500`, `AGENT_RUN_TOTAL_TOKENS_LIMIT`
  default `None` (line 69), `AGENT_PROMPT_CACHE_ENABLED=True`; validator
  cross-checks in `core/settings/__init__.py:76-79`.
- **Usage limits**: `loop.py:75-78` — `UsageLimits(request_limit=
  resolved_model.max_steps, total_tokens_limit=settings.AGENT_RUN_TOTAL_
  TOKENS_LIMIT)`.
- **Catalog**: `services/agents/models/registry.py` — every entry carries
  `context_window`; `resolution.py` resolves per-agent into
  `ResolvedModel` (available at `build_runtime_agent`, `loop.py:52`).
- **Prompt budgets**: `prompt.py:38-92` — `PromptBlock.budget` optional
  char cap, `_render_block` truncates with `[truncated]` + warning; only
  `available_files` sets one (`AVAILABLE_FILES_PROMPT_BUDGET`,
  `core/settings/scratch.py:34`).
- **Jobs harness (030)**: registered async handlers, workspace-scoped
  kind × subject × content_hash in-flight dedup, bounded retries, stale
  reclaim, `jobs.sweep_terminal` retention — see
  `services/jobs/`; enqueue seams used by 033 (`files.extract`) are the
  pattern to copy.
- **Cheap-model precedent**: `services/conversations/naming.py` builds a
  settings-pinned agent per call through the same catalog/factory seam.
- **History loading**: `persistence.load_message_history` windows DB rows
  through `AGENT_HISTORY_DB_MAX_MESSAGES` and backfills capability pairs
  (C03) — the watermark key must therefore be a message identifier, not a
  list index (decision 2's rationale).
- **Prompt caching**: Anthropic cache settings enabled at the factory
  (`factory.py:83-92`); the watermark chunking exists to keep the cached
  prefix stable — any injection that changes per-turn breaks it.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Migration | `cd apps/api && DATABASE_URL=... uv run alembic check` + `core@head` revision round-trip | clean |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/services/jobs tests/scenarios -q` | all pass |
| Job smoke | `cd apps/api && DATABASE_URL=... uv run python -m workers.job_runner --once` | exits clean |
| Full suite | `cd apps/api && TEST_DATABASE_URL=... uv run pytest -q` | all pass |

## Scope

**In scope:**

- `models/conversation_summary.py` (create) + `core`-branch migration
- `services/agents/runtime/history.py` (summary injection + token-pressure
  trigger; keep `trim_history` pure — it gains a
  `summary: str | None` / `pressure` input rather than DB access)
- `services/agents/runtime/capabilities.py` /
  `services/agents/runtime/loop.py` (thread the resolved model's
  `context_window` and the loaded summary into the trimmer — the
  `ProcessHistory` callable closure is built per turn; verify whether it
  can be async or must receive pre-loaded data, and record the probe)
- `services/conversations/summarize_history.py` (job handler) +
  registration; enqueue seam where `execute_run`/persistence detects a
  fresh watermark
- `utils/tokens.py` (`estimate_tokens`)
- `core/settings/agents.py` (new settings per decisions 1-6, incl. the
  token-cap default flip)
- Sweeper wiring: conversation deletion cascades summaries (ride the
  existing conversation deletion path; summaries are derived data)
- `tests/`: trimming/injection units, job handler tests, scenario
  additions (055 suite), settings validator tests
- `docs/architecture/governance.md` §3 row for summaries (derived data,
  swept with conversation)

**Out of scope (do NOT touch):**

- Workspace-level LLM spend quotas (recorded follow-up for governance §4).
- Real tokenizers or per-provider token counting (decision 7).
- The 040/049 prompt blocks themselves (they consume the budget seam
  later; do not pre-build their blocks).
- Redaction/PII filtering of summaries (summaries stay workspace-internal
  derived data; revisit with retention/export work).
- SSE protocol, frontend (summaries are not user-visible in v1 — a
  follow-up may surface "conversation summary" in the UI).

## Git workflow

- Branch: `advisor/056-context-compaction`
- Commits: `API - Conversation Summary Model & Job` /
  `API - Cache-Stable Summary Injection & Token Pressure`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: model + migration

`conversation_summaries` per decision 2 (unique on
`(conversation_id, watermark_key)`), core branch, downgrade/upgrade
round-trip on a fresh temp database (031's verification pattern).

### Step 2: summarize job

Handler: load the dropped span (messages before the watermark key, via
the persistence seams — not raw SQL duplication), fold any prior summary
(decision 3), run the cheap-model prompt (decision 4), upsert the row,
supersede older watermarks. Enqueue seam: after a successful turn whose
trim reported a fresh watermark, enqueue with subject/hash idempotency.
Handler tests script the model; no live calls.

**Verify**: jobs tests pass; `job_runner --once` processes a seeded job;
re-enqueueing the same watermark dedups.

### Step 3: injection + pressure trigger

Extend `trim_history(messages, *, max_turns, keep_turns, summary=None,
token_pressure=False)`: pressure advances the cut one extra chunk;
summary injects per decision 3. The per-turn closure
(`history_trimmer`) is built with the conversation's stored summary and
the pressure flag computed before the run (estimate over system prompt +
loaded history vs `context_window × AGENT_HISTORY_CONTEXT_FRACTION`) —
loading happens where `build_runtime_agent` inputs are gathered
(`execute_run.py:111-119` context loading), keeping the trimmer pure.

**Verify**: unit tests — summary present ⇒ injected once after `kept[0]`
alongside capability pairs; watermark unchanged across two turns ⇒
byte-identical trimmed prefix (cache-stability pin, extend the 013
tests); pressure ⇒ cut advances exactly one chunk; no summary ⇒ 013
behavior byte-identical.

### Step 4: token-cap default + settings

Flip `AGENT_RUN_TOTAL_TOKENS_LIMIT` default per decision 6; add the new
settings + validator guards (fraction ∈ (0,1], summary cap > 0). Confirm
`.local/` env examples mention the override knob for dev.

### Step 5: scenarios + docs

Scenario-suite additions (055): a long scripted conversation crosses the
watermark twice — asserts summary job enqueued, injected on the following
turn, prefix stability, and chained-summary folding. Governance §3 row;
`docs/architecture/agent-runtime.md` context paragraph updated to describe
trim+summarize.

## Test plan

~14-18 tests: migration round-trip, job handler (fold/supersede/dedup/cap),
trimmer units (injection, stability, pressure, no-summary parity),
settings validators, and 2-3 scenarios. The cache-stability pin
(byte-identical prefix across turns at a fixed watermark) is the test
that guards the whole design — treat it as the review centerpiece.

## Done criteria

- [ ] Long conversations get an automatic, bounded, out-of-band summary
      injected exactly once, keyed to the trim watermark
- [ ] Trimmed prefix is byte-stable across turns between watermark
      advances (pinned by test)
- [ ] Token pressure tightens trimming chunk-wise against the catalog
      `context_window`; turn floors unchanged
- [ ] `AGENT_RUN_TOTAL_TOKENS_LIMIT` has a non-null default; capped runs
      persist as before
- [ ] Summaries are swept with their conversation; governance §3 updated
- [ ] Full suite + scenarios green; `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `ProcessHistory` in the installed 2.1.0 cannot receive per-turn
  pre-loaded data through a closure the way `history_trimmer` assumes, or
  requires async and the closure pattern breaks — probe, record, and
  adapt the threading (e.g., stash on `RuntimeDeps`) without making the
  trimmer itself do I/O.
- The watermark key cannot be made stable under `AGENT_HISTORY_DB_MAX_
  MESSAGES` windowing (C03) — the message-id keying is the contract; if
  ids are absent from loaded history rows, report before inventing a
  different key.
- Summary injection breaks provider validity (some providers reject
  synthetic message shapes) — the capability-pair re-synthesis already
  navigates this; mirror its exact message construction and STOP if that
  is insufficient.
- The naming-model seam is unsuitable (e.g., no cheap model configured in
  an env) — degrade to plain trimming, never block the turn.
- You are tempted to summarize in the request path "just for the first
  time" — that is the latency this design exists to avoid.

## Maintenance notes

- **Plans 040/049** must register their prompt blocks with explicit
  budgets and participate in the same estimated-token assembly log —
  the window's tenants stay visible in one place.
- **Summary quality** is a Gate G5 concern: when graded evals (055) grow
  a long-conversation case, the summary prompt is tunable content — tune
  against evals, not vibes.
- If estimates drift for a provider (systematic over/under trim), recalibrate
  that model's `chars_per_token` catalog value offline; the fraction setting
  absorbs calibration meanwhile.
- The workspace-level LLM budget follow-up (governance §4) should reuse
  the hot usage columns on `agent_runs` — counters exist; only the quota
  surface is missing.
- Reviewers should scrutinize: the byte-stability test, the
  supersede-not-stack rule (at most one summary in any prompt), and the
  enqueue idempotency under concurrent turns.
