# Plan 071: Memory dedup must not reinforce contradictions (amendment to 048)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is the amendment block in "Amendment text" below,
> appended verbatim to `docs/plans/048-agent-memory-model-tools.md`, plus
> the README row. No code changes. The code lands through the amended 048.
> When done, update the status row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/048-agent-memory-model-tools.md docs/plans/000_README.md`
> Re-verify the "Current state" quotes below against 048's live text. If
> 048's status row is no longer TODO, if the file has moved to
> `docs/plans/complete/`, or if `services/memories/` exists in the tree,
> 048 has started or finished executing — STOP and reconcile with the
> landed code instead of amending a plan that no longer binds anyone.

## Status

- **Priority**: P1
- **Effort**: S-M (one amendment block + README row; the code cost is
  absorbed into 048 and is small — a tool-response branch instead of a
  silent write, plus test deltas)
- **Risk**: LOW-MED as a doc — it changes 048's write-path semantics on
  paper before any code exists, but a wrong resolution design degrades
  memory quality for every agent that writes memories
- **Depends on**: 048 (written, TODO). **Binds before 048 executes** —
  after execution this becomes a code-change plan, not an amendment
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **Near-duplicates get an explicit resolution step; silent reinforce is
   removed.** 048 decision 6 treats cosine ≥ 0.92 as "same memory" and
   reinforces the existing row. But a correction ("user no longer wants
   weekly reports") is a near-duplicate of the stale fact it corrects
   ("user prefers weekly reports") with the opposite meaning — the design
   reinforces the stale row and drops the correction. Mature memory
   systems (Mem0, Zep-class) classify each near-duplicate pair as
   ADD (distinct) / UPDATE-supersede (correction) / NOOP (true duplicate)
   before touching confidence. 048 already owns a supersession mechanism
   (decision 9); contradictions route to it — no new lifecycle.
2. **v1 resolver: the writing agent, via the tool response.** On a dedup
   hit, `save_memory` writes nothing and returns the near-duplicate
   (existing row + similarity) with instructions to choose: true duplicate
   → re-call with `duplicate_of=<id>` (reinforce); correction →
   `update_memory(<id>, content=...)` (048 decision 9 supersedes on
   content change); distinct → re-call with `save_as_new=true`. No extra
   model call, no new dependency, and the agent that has the conversation
   context makes the semantic call. This is the honest v1.
3. **Cheap-model classifier deferred, eval-gated.** Option (a) — classify
   the pair with a settings-pinned helper model through the seam 028's
   `web_search` and 056's summarizer use — saves a round-trip but adds an
   LLM call and a failure mode inside every dedup hit. It is the
   designated upgrade *if* Gate G4 evals show agents resolving badly, and
   may not ship without those evals first. Recorded, not built.
4. **Lexical negation heuristics rejected.** Detecting "no longer" /
   "not" / "stopped" patterns is brittle across phrasings and languages
   and gives false confidence exactly where precision matters. Rejected
   permanently, not deferred.
5. **The 0.92 threshold is declared uncalibrated and gets a calibration
   fixture.** A constant deciding whether writes are silently absorbed
   must be measured against the actual default embedding model. 048's
   Step 8 gains a labeled pair set (true duplicates, contradictions,
   distinct pairs) and a gated live-embedding check in the 045
   eval-harness mold. Expected finding, worth pinning: contradiction
   pairs score *above* any usable threshold — proof the resolution step,
   not threshold tuning, handles them. Any future
   `MEMORY_DEDUP_SIMILARITY` change must cite calibration output (G4).
6. **Job-time dedup fails open to sprawl, never to absorption.** 048's
   `memory.embed` job reinforces-and-supersedes on a dedup hit with no
   agent in the loop — the silent-absorption bug in its worst form.
   Amended: the job stamps the vector, leaves both rows active, and
   records a memory-resource audit event naming the pair. A duplicated row
   is recoverable; an absorbed correction is not.
7. **Decay half-lives are provisional constants; core memories stop
   decaying.** 048 decision 7's rates (fact 0.005/day ≈ 139 d half-life,
   preference 0.002 ≈ 347 d, episode 0.02 ≈ 35 d, outcome 0.01 ≈ 69 d)
   have no empirical basis, and stable identity facts (name, timezone)
   share a curve with volatile ones. Amended: the settings descriptions
   mark all four provisional pending Gate G4 eval evidence, and
   `effective_confidence` exempts `kind='core'` rows — 048 already
   defines core as identity-level facts, so kind is the stable/volatile
   signal we have. A per-row no-decay flag is rejected as schema churn
   duplicating what `kind` expresses. No other decay-model change.

## Why this matters

Corrections are the single most valuable memory write an agent makes,
and 048's current write path converts them into reinforcement of the
thing being corrected, invisibly, with an audit trail that says
`reinforced: true`. Fixing this costs one amendment now; after 048
executes it costs a migration of live memory semantics plus Gate G4
re-tuning. The threshold and decay items are the same shape: invented
constants become load-bearing the moment 049 injects memories into
prompts, so they must be labeled provisional and given a tuning
mechanism before that happens.

## Current state

Verified against `docs/plans/048-agent-memory-model-tools.md` on the
working tree at `c770a1c` (2026-07-07). 048 is written, TODO, unexecuted
(no `services/memories/`, no `agent_memories` model in the tree).

- **Dedup decision (048 decision 6)**: "Dedup-reinforce at write time,
  cosine ≥ 0.92 … Similarity ≥ `MEMORY_DEDUP_SIMILARITY` (0.92) →
  reinforce instead of insert: `confidence = min(1.0, confidence + 0.1)`,
  `last_reinforced_at = now()`, `reinforcement_count += 1`; return the
  existing row flagged `reinforced: true`." The job-time path: "the embed
  job re-runs the dedup check … and, on a hit, reinforces the existing
  row and marks the new row `superseded`→existing".
- **Decay decision (048 decision 7)**: "Rates: fact `0.005`/day
  (half-life ≈ 139 d), preference `0.002` (≈ 347 d), episode `0.02`
  (≈ 35 d), outcome `0.01` (≈ 69 d)", floored at 0.05, computed in
  `effective_confidence`. No rationale cited; no type or kind exempt.
- **Supersession exists (048 decision 9)**: `update_memory` on a content
  change "inserts a new row … and marks the old row
  `status='superseded'`, `superseded_by_id=<new>`" — the exact mechanism
  contradictions should route to.
- **Gate G4 (048 pre-flight + maintenance notes)**: "any change to
  `MEMORY_DEDUP_SIMILARITY`, decay rates, TTL defaults, or the
  core-approval rule must update the Step 8 eval tests in the same PR" —
  the enforcement hook this plan's calibration fixture plugs into.
- **Step 8 dedup test** pins the buggy behavior ("near-duplicate …
  reinforces — no new row"); the Step 6 prompt snippet says "forget stale
  memories instead of contradicting them" but the write path never gives
  the model the chance.
- **Helper-model seam** (deferred option a): 028's `web_search` helper
  model and 056's summarizer (`services/conversations/naming.py`
  pattern) both resolve a settings-pinned cheap model through the
  catalog/factory seam. 049 is TODO and structurally unaffected.

## Scope

**In scope:**

- `docs/plans/048-agent-memory-model-tools.md` — append the amendment
  block below verbatim; add one pointer line to its executor-instructions
  blockquote
- `docs/plans/000_README.md` — row for 071; note on 048's dependency line

**Out of scope:**

- Any code. All deltas land inside 048's execution.
- 049 and the memory UI; the 045 retrieval engine; consolidation jobs
  (still deferred per 048 decision 14).
- Re-litigating 048's approval, scope-isolation, or TTL decisions.

## Amendment text

Append to `docs/plans/048-agent-memory-model-tools.md` exactly:

```markdown
## Amendment (2026-07-07, plan 071): dedup resolution, calibration, decay

**Changed decisions.**

- **Decision 6 (amended)**: a dedup hit (cosine ≥
  `MEMORY_DEDUP_SIMILARITY`) never writes silently. `save_memory` returns
  `{"status": "near_duplicate", "existing_memory": {...}, "similarity":
  ...}` plus instructions: true duplicate → re-call with
  `duplicate_of=<existing id>` (service verifies the id is the current
  nearest neighbour in-scope, then reinforces: confidence step,
  `last_reinforced_at`, `reinforcement_count`); correction/contradiction
  → call `update_memory(<existing id>, content=...)` (decision 9
  supersedes); genuinely distinct → re-call with `save_as_new=true`
  (plain insert). Reinforcement only ever happens through an explicit
  `duplicate_of`. Job-time (`memory.embed`) dedup hits do NOT reinforce
  or supersede — no agent is present to resolve; stamp the vector, leave
  both rows active, record a memory-resource audit event naming both ids.
- **Decision 7 (amended)**: the four decay rates are provisional
  constants with no empirical basis — say so in their settings `Field`
  descriptions ("provisional; tune only with Gate G4 eval evidence").
  `effective_confidence` returns `confidence` unchanged for
  `kind='core'` rows (identity-level facts do not decay). No per-row
  flag, no new column.
- **Rejected**: lexical negation heuristics (brittle); a cheap-model
  pair classifier at write time (deferred — the 028/056 helper-model
  seam is the designated shape *if* G4 evals show agents resolving
  near-duplicates badly; may not ship without those evals).

**Step deltas.** Step 1: no new settings; amend the decay-rate
descriptions. Step 4 (`save_memory`): implement the resolution flow;
`duplicate_of` and `save_as_new` are mutually exclusive
(`AppValidationError`). Step 5 (`memory.embed`): replace
reinforce-and-supersede with stamp-and-audit per amended decision 6.
Step 6: `save_memory` tool schema gains `duplicate_of: str | None` and
`save_as_new: bool = False`; extend `MEMORY_INSTRUCTIONS`: on a
near-duplicate response, reinforce true duplicates, `update_memory` the
existing row for corrections, save distinct facts as new. Step 8
(`test_save_memory_dedup.py`): near-dup first call writes nothing and
returns the pair; `duplicate_of` reinforces; a contradiction resolved via
`update_memory` supersedes the stale row (chain intact); `save_as_new`
inserts; job-time hit leaves both rows active and audits. Step 8 also
gains `test_dedup_calibration.py`: a labeled fixture of duplicate /
contradiction / distinct pairs, run through the deterministic fake
provider for the invariants and, gated like the 045 live-eval harness
(skip without opt-in env), through the real default embedding model to
report score distributions. Pin the finding that contradiction pairs
score above the threshold. Gate G4 now additionally requires calibration
output for any `MEMORY_DEDUP_SIMILARITY` change.
```

Also insert into 048's executor-instructions blockquote (after the G4
bullet):

```markdown
> - **Amendment (plan 071)** — the amendment block at the end of this
>   plan modifies decisions 6/7 and Steps 1/4/5/6/8. Read it before
>   Step 0; where it conflicts with the body, the amendment wins.
```

## Git workflow

- Branch: `advisor/071-memory-dedup-contradictions`
- Commit: `Docs - Memory Dedup Contradiction Amendment`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

1. Run the drift check; confirm the "Current state" quotes still match
   048 verbatim and 048 is still TODO.
2. Append the amendment block and the blockquote pointer to 048 exactly
   as drafted above.
3. Update `docs/plans/000_README.md`: add the 071 row (depends on 048;
   binds before it) and append "071 amends" to 048's dependency notes.

## Done criteria

- [ ] `grep -c "Amendment (2026-07-07, plan 071)" docs/plans/048-*.md`
      → 1 (the appended block)
- [ ] `grep -c "Amendment (plan 071)" docs/plans/048-*.md` → 1 (the
      executor-blockquote pointer)
- [ ] 048's amendment covers: resolution flow, job-time stamp-and-audit,
      calibration fixture, provisional decay wording, core no-decay
- [ ] `git diff --stat` touches only the two docs in scope; no code changed
- [ ] `docs/plans/000_README.md` row for 071 added and 048's dependency
      note names it

## STOP conditions

- 048 has started or finished executing (README row not TODO, file in
  `complete/`, or `services/memories/` exists) — this becomes a
  code-change plan; report back instead of amending.
- 048's decision 6 or 7 text no longer matches the quotes in "Current
  state" — someone else amended it; reconcile before layering a second
  amendment.
- 049 has executed against unamended 048 semantics — the UI may render
  `reinforced` results; reconcile both plans together.

## Maintenance notes

- If the cheap-model classifier (decision 3) is ever promoted, it slots
  in front of the tool-response flow as a pre-classification, keeping the
  agent-facing resolution as the fallback — not replacing it wholesale.
- The calibration fixture doubles as the evidence base for embedding-
  model migrations (048 decision 11 records provider/model/dims per row
  for exactly this); recalibrate whenever the default model changes.
- Deferred consolidation (048 decision 14) inherits amended decision 6:
  a consolidation job must surface or supersede, never silently merge
  near-duplicates by similarity alone.
- Reviewers of 048's eventual PR should scrutinize: no code path
  reinforces without an explicit `duplicate_of`; the job path cannot
  supersede; the near-duplicate tool response cannot loop an agent
  forever (the instructions name all three exits).
