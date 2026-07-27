# Plan 069: Memory block ordering determinism — decay must not bust the prompt cache (amendment to 049)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is the amendment block in Step 2, appended verbatim to
> `docs/plans/049-memory-injection-ui.md`, plus the README row. No code.
> The code lands through the amended 049. When done, update the status row
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/049-memory-injection-ui.md docs/plans/048-agent-memory-model-tools.md`
> Re-verify the "Current state" quotes below against 049/048's live text.
> If 049's status row is DONE, or `apps/api/services/memories/core_block.py`
> exists, 049 has executed — STOP (see STOP conditions).

## Status

- **Priority**: P1
- **Effort**: S (one amendment block + README row; the code delta inside
  049 is roughly neutral — a different sort key and one more test)
- **Risk**: LOW as a doc — it fixes a cache-busting design bug before any
  memory code exists
- **Depends on**: 049 (written, TODO; reads 048's decay model). **Binds
  before 049 executes.**
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **Rank and select on stored (undecayed) confidence with stable
   tiebreakers** — the primary fix. The injection sort key becomes
   `(-importance, -confidence, -(last_reinforced_at or created_at), id)`.
   Every component changes only when a row is written (048's reinforcement
   and `update_memory` are the only confidence/recency writers), so the
   rendered block — ordering, budget-clamp selection, and the omitted-count
   footer — is byte-stable between memory writes by construction.
2. **Effective confidence stays read-path and display only.** 048
   decision 7 (decay is a pure read-time function, mirrored in the search
   SQL ordering) and 049 decision 11 (responses carry
   `effective_confidence`) are untouched: decay still governs retrieval
   ranking and the UI; it just never orders the prompt block.
3. **The formatter keeps `now` as an explicitly inert parameter** so the
   invariance contract is testable: output must be a pure function of rows
   and budget, and the strengthened test fails the moment anyone
   reintroduces time-dependence.
4. **The determinism test gains a time axis.** 049's planned test fixes
   `now` and cannot see this bug; the amended test renders identical rows
   at two `now` values at least six weeks apart (spanning the ≈35-day
   episode half-life) and asserts byte-identical output.
5. **Rejected: quantize decay into coarse buckets** (e.g. weekly steps in
   the rank key). Ordering still changes with zero writes — just on a
   clock schedule — so the cache still busts, merely less often and
   predictably, and the bucket width becomes one more Gate G4 tuning knob.
6. **Rejected: recompute-and-persist confidence on writes only.** A
   stored decay mutation contradicts 048 decision 7 ("decay ... never
   writes") and the Gate G4 pinned invariant "decay is read-only math";
   writes rippling recomputes across unrelated rows is churn with no
   consumer.

## Why this matters

049's formatting design exists to keep the system-prompt prefix
byte-stable between memory writes — decisions 3/4 say so, plan 013's
trimming relies on it, 048's maintenance notes bind 049 to it. But the
plan's own sort key is a function of wall-clock time: `effective_confidence`
decays at different per-type rates (048 decision 7), so two runs days apart
with zero memory writes can flip ordering — or change which lines survive
the greedy budget clamp — as decay curves cross. Concretely: equal
importance, an episode at confidence 0.95 (rate 0.02/day) and a fact at
0.80 (0.005/day) — the episode ranks first on day 0, the fact by day 12,
no writes in between. Every crossing silently busts the provider
prompt-cache prefix for that agent, and the planned determinism test
cannot catch it because it fixes `now`. Fixing this is free today: 049 is
written but not executed, so the fix is one appended block, not a
migration of landed behavior.

## Current state

All quotes verified against the working tree at `c770a1c` (2026-07-07);
049 and 048 are both TODO in `docs/plans/000_README.md`.

- **The contradiction, in 049 decision 3**: "Sort key: `importance` desc,
  `effective_confidence` desc, `last_reinforced_at` (fallback
  `created_at`) desc, `id` asc as the final tiebreak — fully deterministic
  so the rendered block (and the provider prompt-cache prefix) only
  changes when memories actually change." The tiebreak makes the ordering
  *total*, but the second key is time-varying, so the block changes when
  nothing changed.
- **049 Step 1 rendering algorithm, point 1**: "Rank by `(-importance,
  -effective_confidence(memory, now=now), -(last_reinforced_at or
  created_at), id)`". Point 3 clamps greedily in that rank order, so
  selection and the omitted footer inherit the time-dependence.
- **049 decision 4** renders no volatile values but explicitly allows the
  hole: "decay-derived ordering may use them".
- **049 Step 2** feeds live wall-clock into the render:
  `render_core_memory_block(core_memories, now=datetime.now(UTC), ...)`.
- **049 Step 4 determinism test**: "determinism — same rows in shuffled
  input order render byte-identical output" — one fixed `now`; blind to
  decay crossings.
- **048 decision 7** (the decay model 049 consumes):
  `effective_confidence = confidence * exp(-rate_per_day[type] *
  age_days)`, floored at 0.05; per-type rates fact `0.005`, preference
  `0.002`, episode `0.02`, outcome `0.01` — four half-lives, so crossings
  between types (and between same-type rows of different base confidence
  and age) are the normal case, not an edge case.

## Scope

**In scope:**

- `docs/plans/049-memory-injection-ui.md` (append the Step 2 amendment
  block verbatim; no other edits to the file)
- `docs/plans/000_README.md` (069 row; note the amendment in 049's
  dependency cell)

**Out of scope:**

- Any code. The sort-key change and the new test land inside 049's
  execution per the amendment.
- 048's decay math, rates, settings, or search-path ordering (decision 2).
- Injection quotas, rerankers, budget tuning — still eval-gated (Gate G4).

## Git workflow

- Branch: `advisor/069-memory-block-determinism`
- Commit: `Docs - Memory Block Determinism Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Verify the anchors

Confirm the "Current state" quotes still match 049/048 and both plans are
still TODO (drift check above). A mismatch is a STOP condition.

### Step 2: Append the amendment block to 049

Append the following to the end of `049-memory-injection-ui.md`, verbatim:

```markdown
## Amendment (plan 069, 2026-07-07): cache-stable ranking

Binding on execution. Where this section conflicts with decisions 3/4,
Steps 1/2/4, or the Test plan above, this section wins.

1. **Rank and select on stored confidence, never effective confidence.**
   The Step 1 sort key becomes `(-importance, -confidence,
   -(last_reinforced_at or created_at), id)`. Decision 3's
   `effective_confidence desc` key is replaced by `confidence desc`
   (stored, undecayed). Every key component changes only on a write, so
   ordering, budget-clamp selection, and the omitted-count footer are
   byte-stable between memory writes — the determinism claim in decision 3
   now holds by construction instead of only at a frozen `now`.
2. **Decision 4's allowance "decay-derived ordering may use them" is
   revoked.** Neither the rendered text nor the ordering/selection/
   clamping may depend on wall-clock time. `effective_confidence` remains
   read-path only: list/detail responses (decision 11) and search ranking
   (048 decision 7) keep it; the prompt block never computes it.
3. **`render_core_memory_block(memories, *, now, budget)` keeps `now` as
   an explicitly inert parameter.** Its docstring must state the
   invariance contract: output is a pure function of the rows and the
   budget; `now` exists so the contract is testable. Step 2's
   `execute_run` call site is unchanged.
4. **Step 4's determinism test gains a time axis**: render the block with
   identical rows at two `now` values at least six weeks apart and assert
   byte-identical output. This joins the shuffled-input test as part of
   the prompt-cache contract; the Test plan's "rendering is deterministic"
   invariant now means invariant across both input order and time.
5. The maintenance note "the determinism test is the tripwire" now covers
   time-invariance: reintroducing any wall-clock-derived value into
   ranking or selection (including quantized decay buckets) is an
   eval-gated decision that must update both tests first (Gate G4).
```

### Step 3: README

Add the 069 row to the `docs/plans/000_README.md` table (P1 / S / depends
049; mark DONE on completion) and note "069 amendment" in 049's dependency
cell so 049's executor cannot miss it.

## Done criteria

- [ ] `grep -c "Amendment (plan 069" docs/plans/049-memory-injection-ui.md`
      → 1; the block matches Step 2 verbatim
- [ ] `git diff docs/plans/049-memory-injection-ui.md` shows an append-only
      change (no lines removed)
- [ ] README row for 069 added; 049's dependency cell names the amendment
- [ ] No code changed: `git status` shows only the two doc files

## STOP conditions

- 049 has started or finished executing (status row not TODO, or
  `apps/api/services/memories/core_block.py` / `apps/api/routes/memories/`
  exists) — the fix is then a code-change plan against the landed
  formatter, not a plan amendment; reconcile first.
- 049's decision 3 / Step 1 text no longer matches the Current state
  quotes (already amended or rewritten) — re-verify whether any
  wall-clock dependence remains before appending anything.
- 048's decay model changed (per-type rates removed, or decay made a
  write-time mutation) — the finding's premise moved; re-derive.

## Maintenance notes

- If Gate G4 eval evidence ever shows stored-confidence ranking injecting
  stale memories, the revisit path is decision 5's quantized buckets —
  taken deliberately, both determinism tests updated in the same PR —
  never a quiet return to raw `effective_confidence`.
- Reviewers of 049's eventual PR should scrutinize: no
  `effective_confidence` call in `core_block.py`, and the two-`now` test
  actually spanning weeks (a two-second gap proves nothing).
