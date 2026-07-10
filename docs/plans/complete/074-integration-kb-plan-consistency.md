# Plan 074: Integration & KB plan consistency sweep — five pre-execution corrections (amendments to 039/042/043/044/045)

> **Executor instructions**: This is an amendment plan in the 061/067 mold —
> its deliverable is five clearly-marked amendment blocks appended to
> `docs/plans/{039,042,043,044,045}-*.md` (plus one companion block in
> 038), not code. The code lands when those plans execute. The full
> amendment texts are drafted verbatim below; paste them, add the one-line
> pointers, and reconcile — do not redesign. When done, update the status
> row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/038-integration-oauth-connect-flows.md docs/plans/039-integration-resource-discovery.md docs/plans/042-integrations-ui.md docs/plans/043-embeddings-provider-service.md docs/plans/044-kb-models-ingestion.md docs/plans/045-hybrid-search-eval-harness.md`
> plus the execution probes
> `ls apps/api/services/integrations/discovery apps/api/services/embeddings apps/api/services/kb apps/api/routes/kb apps/web/src/features/integrations 2>/dev/null`
> (all must be absent) and the five README rows (all TODO). If a target's
> text drifted, re-verify the "Current state" quotes before pasting its
> block. If a target has started executing, STOP **for that amendment
> only** — the rest still land (see STOP conditions).

## Status

- **Priority**: P1
- **Effort**: S-M (plan amendments; the code cost is absorbed into the
  five targets and is small in each)
- **Risk**: LOW as a doc — it removes a security-staleness hole, an SSRF
  TOCTOU, a settings contradiction, a dead-by-omission registry entry,
  and a phantom route from Phase 4a/4b before any of that code exists
- **Depends on**: 039/042/043/044/045 (all written, TODO). **Binds before
  any of them executes** (Phase 4a/4b).
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `6be5491`, 2026-07-07

## Decisions taken

The full normative text lives in the amendments; summarized here:

1. **039 gains a periodic re-discovery sweep**
   (`integrations.rediscover_stale`, 030 harness). Discovery runs only at
   connect time and on manual trigger, so `writable`/
   `permissions_metadata`/`availability`/`last_seen_at` go stale
   indefinitely — while 040 gates write fan-out on exactly that metadata
   (fail-closed) and 041 derives it from provider role checks. An
   upstream permission revoke staying `writable=true` until a human
   re-runs discovery is security staleness, not a freshness nicety.
2. **042's connection-rename route becomes real by amending 038.** 042's
   endpoint table lists `PATCH /integrations/connections/{id}` owned by
   038; 038 ships nine routes and no PATCH. Roadmap D3 makes user-set
   labels a v1 requirement and 042 builds inline rename UI — the honest
   fix is a small 038 addition, composed with plan 067's amendment.
3. **043 keeps `text-embedding-3-large`, explicitly truncate-only.**
   Verified nuance: the entry declares `supports_dimensions=True`, so
   vectors ARE storable (API-truncated to ≤1024) — "unstorable" does not
   hold. What holds: its native 3072 dims are unreachable by construction
   (settings `le=1024`; 044's fixed `HALFVEC(1024)` collection) and
   nothing says so. Document the posture; add a registry-bounds test.
4. **044's URL fetch must pin connects to vetted IPs.** 044 validates
   resolved addresses pre-flight only; the OS resolver can re-resolve to
   a private IP at connect time (DNS-rebinding TOCTOU). 046 already
   requires connect-time re-checks; 044 is aligned to it with a concrete
   pinned-transport mechanism.
5. **045's `KB_SEARCH_TOP_K_MAX` (50) vs `KB_SEARCH_CTE_LIMIT` (40) gets
   a validator.** Verified nuance: in hybrid mode two 40-candidate CTEs
   can union to 80 distinct ids, so top_k=50 is *sometimes* satisfiable —
   but in `lexical_fallback` mode the pool is one CTE, so any top_k in
   (40, 50] silently under-fills. Raise the CTE limit to 50; add a
   settings cross-check so the pair can never regress silently.

## Why this matters

All five targets are written and unexecuted, so every correction is free —
a few lines of plan text now versus a migration, a security advisory, or
a mid-execution STOP later. Three are security-grade: stale `writable`
metadata silently authorizes external writes 040 was designed to block,
the fetch TOCTOU is a real SSRF class 044's own test plan thinks it
covers, and the top-k contradiction turns a documented request cap into a
silent under-fill. The other two are the kind of cross-plan drift that
becomes an executor STOP condition if left until execution day.

## Current state

All quotes verified against the plan files at `c770a1c` (2026-07-07). All
five targets plus 038 are TODO in `000_README.md`; no execution probe
exists.

- **039**: discovery is enqueued only from 038's connect seams
  (decision 1) and the manual
  `POST /integrations/connections/{connection_id}/discover` route
  (Step 6); the sole periodic kind, `integrations.sweep_stale`
  (decision 7), only hard-deletes stale rows. Downstream anchors: 040
  Step 5 "Compute `write_allowed` from the resource's discovered
  write-permission metadata"; 041 decision 7 "Write-permission metadata
  feeds 040's gate, fail-closed".
- **042**: endpoint table row "Rename connection label |
  `PATCH /integrations/connections/{id}` | 038"; decision 4 "Label rename
  is inline"; Step 2 ships `rename-connection.ts`. 038 Step 4's route
  table lists nine routes — no PATCH ("route smoke command lists all nine
  paths"). 038 has decisions 1–12; plan 067's amendment adds 13–17.
- **043**: Step 1 `EMBEDDINGS_DIMENSIONS: int = Field(default=1024,
  ge=512, le=1024)`; Step 3 catalog includes
  `EmbeddingModelInfo("openai", "text-embedding-3-large", 3072, True, 2048)`;
  Step 4 sends the `dimensions` kwarg only for Matryoshka models. 044
  decision 2 pins the collection at `HALFVEC(1024)`.
- **044**: decision 9's fetch spec "resolves DNS and rejects loopback,
  private, link-local, and unique-local addresses (`ipaddress` checks on
  every resolved address) … redirect cap re-validating each hop" —
  resolution-time validation only; nothing binds the connect to a vetted
  address. 046 decision 4: the fetcher "re-checks resolved IPs at fetch
  time against the private-range blocklist to defeat DNS rebinding"; 046
  Step 2: "the fetch path to re-check resolved addresses at connect time
  (DNS rebinding), which lives with the fetcher".
- **045**: Step 2 `KB_SEARCH_TOP_K_MAX: int = 50` and
  `KB_SEARCH_CTE_LIMIT: int = 40`; Step 3 clamps top_k to
  `[1, KB_SEARCH_TOP_K_MAX]`; decision 3's fallback runs the lexical CTE
  alone. No cross-field settings check exists.

## Scope

**In scope:**

- `docs/plans/{039,042,043,044,045}-*.md` — append the amendment blocks;
  add one pointer line each to the executor-instructions blockquote
- `docs/plans/038-integration-oauth-connect-flows.md` — the companion
  rename-route block (decision 2) + pointer line
- `docs/plans/000_README.md` — add the 074 row; note the amendments

**Out of scope:**

- Any code, migration, settings, or test file — all of it lands inside
  the targets' execution per the amendments
- Rewriting any target's existing body text (amendments supersede by
  reference; inline edits would hide the history)
- Plan 067's amendment to 038 — untouched (see Maintenance notes)
- Plans 040/041/046 — anchors here, not targets

## Git workflow

- Branch: `advisor/074-integration-kb-plan-consistency`
- Commit: `Docs - Integration & KB Plan Consistency Amendments`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Pointer lines

After the drift check, add to each target's (and 038's)
executor-instructions blockquote:

> **Amendment (plan 074) pre-flight**: the "Amendment (plan 074,
> 2026-07-07)" block at the end of this file amends this plan; where it
> conflicts with the body above, the amendment wins.

**Verify**: each blockquote renders as one quote; no other body line
touched.

### Step 2: Append the amendment blocks

Paste each block below verbatim at the end of its target file (for 038,
after plan 067's block if present). **Verify**:
`for p in 038 039 042 043 044 045; do grep -c "Amendment (plan 074" docs/plans/$p-*.md; done`
prints `2` six times (pointer + block per file).

### Step 3: Update the README

Add the 074 row and a dated note that 038/039/042/043/044/045 carry 074
amendments; the six target rows stay TODO. **Verify**: table renders;
`git status --porcelain` shows only the plan docs.

## Amendment texts

### 039 — scheduled re-discovery for permission staleness

Paste into 039 verbatim:

```markdown
## Amendment (plan 074, 2026-07-07): periodic re-discovery

Where this block conflicts with the body above, this block wins.

**New decision 11.** One new self-rescheduling kind,
`integrations.rediscover_stale` (the `integrations.sweep_stale` pattern):
each pass calls `enqueue_discovery` for every non-deleted
`requires_discovery` connection in
`{active, needs_resource_selection, degraded}` whose newest **succeeded**
discovery run is older than `INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS`
(new decision-10 setting, default 86400). `needs_reauth`/`revoked`/
`auth_pending` are skipped (auth first); `error` stays manual-retry-only.
030's in-flight dedup prevents double-enqueue; the decision-3 diff makes
re-runs idempotent. Rationale: 040 gates write fan-out on
`writable`/`permissions_metadata` fail-closed and 041 derives those from
provider role checks — an upstream permission revoke must flip
`writable=false` without a human pressing re-discover. Notification
semantics unchanged: decision 6 applies as written (`needs_reauth` on
transition only; `discovery_failed` only after the final retry; no
`initiated_by_user_id` on the enqueue).

**Step deltas**: Step 1 adds the setting; Step 4 adds the handler beside
`sweep_stale.py`, bootstrapped at the same `ensure_integrations_sweep_job`
call site; the kind smoke (and its done criterion) becomes
`['integrations.discover_resources', 'integrations.rediscover_stale',
'integrations.sweep_stale']`. **Test-plan delta**
(`test_rediscover_stale.py`, DB): a connection with a `writable=true`
resource and a succeeded run aged past the interval, fake provider now
reporting `writable=false` → one sweep pass enqueues discovery (no
initiator) and the run flips the resource row to `writable=false` — the
value 040's `write_allowed` computation reads at resolution time (040
owns the gate-side test). Also pin: fresh-run connections not enqueued;
`needs_reauth`/`revoked` skipped; an in-flight discovery not duplicated.
```

### 042 — rename route reconciled (with the 038 companion)

Paste into 042 verbatim:

```markdown
## Amendment (plan 074, 2026-07-07): rename route is real

The endpoint-table row "Rename connection label |
`PATCH /integrations/connections/{id}` | 038" was a phantom — 038's route
table shipped no such operation. Plan 074's companion amendment to 038
adds it, so the row stands as written; reconcile it against 038's landed
route at pre-flight like every other row. Decision 4's inline rename and
Step 2's `rename-connection.ts` are unchanged. If 038 executed WITHOUT
its 074 amendment, this row is a structural gap — STOP per the existing
pre-flight rule rather than shipping rename UI against a missing route.
```

Paste into 038 verbatim (after plan 067's block when present):

```markdown
## Amendment (plan 074, 2026-07-07): connection label rename

Where this block conflicts with the body above, this block wins.

**New decision 18** (13–17 are plan 067's). D3 makes the per-connection
label a required, user-set value; 042 builds inline rename on it. Add
`rename_connection.py` (service op + route file):
`PATCH /integrations/connections/{connection_id}` with body `{label}`
(non-empty, same schema rule as connect), auth `require_editor` +
`require_connection_mutation_allowed` (the test/refresh ownership rule —
label surgery is not credential surgery). Audits one UPDATE on
`INTEGRATION_CONNECTION` with old/new label; no status transition, no
credential access.

**Step deltas**: Step 4's table gains the row and its verify line becomes
"lists all ten paths"; Step 6's audit sweep covers rename; Step 7 adds:
rename happy path + audit row, blank label 400, non-owner member 403 on a
user-scoped connection, read_only 403.
```

### 043 — `text-embedding-3-large` is truncate-only, on purpose

Paste into 043 verbatim:

```markdown
## Amendment (plan 074, 2026-07-07): 3-large registry posture

Where this block conflicts with the body above, this block wins.

**New decision 10.** `text-embedding-3-large` stays in the catalog, and
its entry gains a comment stating the posture: with
`EMBEDDINGS_DIMENSIONS` capped at `le=1024` and 044's collection fixed at
`HALFVEC(1024)`, its native 3072 dims are unreachable by design — it is
only ever used Matryoshka-truncated via the API `dimensions` param
(`supports_dimensions=True`; Step 4 already sends it), which is safe and
deliberate: 3-large truncated to 1024 outperforms 3-small at 1024, so
the entry is a quality knob needing no schema change. Kept rather than
dropped for exactly that reason. **Step 7 delta** (`test_registry.py`):
every catalog entry must be usable under the settings bounds —
`supports_dimensions is True` or `512 <= native_dimensions <= 1024` — so
a future non-Matryoshka large model cannot be registered unstorable.
```

### 044 — IP-pinned connects in the URL fetch

Paste into 044 verbatim:

```markdown
## Amendment (plan 074, 2026-07-07): pin connects to vetted IPs

Where this block conflicts with the body above, this block wins.

**New decision 13.** Decision 9's fetch validates resolved addresses
pre-flight, but nothing binds the connect to a vetted address — the OS
resolver can return a private IP at connect time (DNS-rebinding TOCTOU).
`fetch_url` must therefore **connect to an address it validated**:
resolve once, `ipaddress`-check every result, then open the connection to
one of those exact IPs (custom httpx transport pinning the resolved
address) while preserving the original hostname for the `Host` header and
TLS SNI — for the initial request AND every redirect hop (each hop
re-resolves, re-validates, re-pins). This matches 046's requirement that
the fetcher "re-checks resolved IPs at fetch time … to defeat DNS
rebinding" / "resolved addresses at connect time" — 044 ships the
fetcher, so the mechanism lands here.

**Step deltas**: Step 3's `fetch_url` spec gains the pinning clause.
**Test-plan delta** (`test_fetch_url.py`): assert via a recording
transport that the connected address is one the validator approved — for
the first request and after a redirect — so a resolver that flips public
→ private between validation and connect can never reach the private
address. The existing rejection cases stand unchanged.
```

### 045 — top_k / CTE-limit contradiction

Paste into 045 verbatim:

```markdown
## Amendment (plan 074, 2026-07-07): top_k vs CTE limit

Where this block conflicts with the body above, this block wins.

**New decision 12.** As written, `KB_SEARCH_TOP_K_MAX = 50` exceeds
`KB_SEARCH_CTE_LIMIT = 40`: in `lexical_fallback` mode the candidate pool
is exactly one CTE, so any accepted top_k in (40, 50] silently
under-fills; in hybrid mode 50 is reachable only when the two lists
overlap by fewer than 30 ids. The cap must never promise more than the
pool guarantees. Fix: Step 2's default becomes
`KB_SEARCH_CTE_LIMIT: int = 50`, and `KBSettingsMixin` gains a
`model_validator(mode="after")` requiring
`KB_SEARCH_CTE_LIMIT >= KB_SEARCH_TOP_K_MAX` so the pair can never
regress silently. **Step 6/test delta**: a settings test pins the
validator (49/50 rejected, 50/50 accepted); a harness case asserts a
`top_k = KB_SEARCH_TOP_K_MAX` lexical-fallback search over a >50-chunk
corpus returns `top_k` rows. Gate G4 note: this corrects a written
default before the harness exists — not ranking tuning; the tuning
protocol does not apply. Any FURTHER change to either value follows the
protocol as usual.
```

## Test plan

None here — doc-only. The behavioral tests (rediscovery sweep, rename
route, registry bounds, pinned-connect transport, settings cross-check)
are specified inside the amendments and land with their targets.

## Done criteria

- [ ] Each of `docs/plans/{038,039,042,043,044,045}-*.md` ends with its
      "Amendment (plan 074, 2026-07-07)" block, pasted verbatim
- [ ] `for p in 038 039 042 043 044 045; do grep -c "Amendment (plan 074" docs/plans/$p-*.md; done`
      prints `2` six times (pointer + block per file)
- [ ] `git diff docs/plans/03*.md docs/plans/04*.md` shows only pointer
      lines and appended blocks — no other body edits
- [ ] `docs/plans/000_README.md` row for 074 added; the six amended
      plans' rows stay TODO
- [ ] No code, migration, settings, or test files changed
      (`git status --porcelain` shows only the plan docs)

## STOP conditions

Stop and report back (do not improvise) if:

- **A target has started or finished executing** (its execution probe
  directory exists, or its README row is not TODO) — skip that target's
  amendment and report it as a code-hardening follow-up needing its own
  plan; **the remaining amendments still land**.
- A target's text has drifted such that a "Current state" quote no longer
  matches (e.g. 039 grew a rediscovery kind, 045's values changed) —
  reconcile that block before pasting; do not paste stale text.
- An "Amendment (plan 074" marker already exists in a target — a previous
  run landed; verify rather than duplicate.
- 067's row is REJECTED and 038 carries no 067 block — the 038 decision
  numbering here (18) assumed 13–17 are 067's; renumber before pasting.

## Maintenance notes

- **Composition with plan 067**: both plans amend 038. 067 owns decisions
  13–17 (PKCE, single-use state, one migration, https redirect URI); this
  plan owns decision 18 (rename route). The step deltas are disjoint
  (067: Steps 1/2/3/7 + a migration step; 074: Steps 4/6/7 route
  surface). 038's executor applies both; neither supersedes the other.
- **042's endpoint table** remains an assumption-to-reconcile (its
  decision 3); the 074 note only guarantees the rename row a backend
  owner. Path-level drift is still absorbed at pre-flight.
- Reviewers should scrutinize: the rediscovery status allowlist
  (auto-retrying `error`/`needs_reauth` would hammer broken or
  unauthenticated providers), the pinned-connect transport preserving SNI
  (a naive IP-in-URL rewrite breaks TLS validation), and that the 045
  validator compares the *configured* pair, not the defaults.
