# Plan 060: Durable run event log and live stream replay

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c2f08cc..HEAD -- apps/api/services/agents/runtime/sinks.py apps/api/services/agents/runtime/streaming.py apps/api/services/conversations/ apps/web/src/features/conversations/stream/`
> This plan is scheduled **last** in the Lane H additions and is expected
> to be executed long after `c2f08cc` — the drift check is mandatory and
> the "Current state" section must be re-verified wholesale before any
> step runs. Treat any sink/protocol drift as a STOP condition.

## Status

- **Priority**: P3 — operator decision 2026-07-07: roadmapped, "literally
  last in the list". Do not execute before the rest of Lane H and the
  Phase 4-6 spine unless reconnect pain becomes acute.
- **Effort**: L
- **Risk**: MED (write amplification on the hot streaming path; a
  replay/live seam with off-by-one gaps duplicates or drops events)
- **Depends on**: 030 (jobs, for retention sweep). Soft: 053 (cancelled
  terminals must replay correctly), 056 (long runs are why this exists).
- **Category**: Lane H — harness hardening (post-roadmap additions
  053–060, added 2026-07-07)
- **Planned at**: working tree at commit `c2f08cc`, 2026-07-07

## Product intent

`StreamSink` is an in-memory `asyncio.Queue`; when the HTTP client
disconnects, events are dropped (`detach()`) and a refreshing client heals
from *persisted messages* only (`use-conversation-heal-loop.ts`). The
architecture doc records this as an explicit v1 non-goal: "reconnect heals
from DB-persisted messages … true live resume would need an addressable
per-run event buffer — out of scope but not precluded"
(`docs/architecture/agent-turn-streaming-plan.md`).

This plan un-defers that, Postgres-only (no Redis, per the standing
decision): a durable per-run event log plus a replay-then-live tail, so a
refresh mid-5-minute-run resumes token flow instead of waiting for the
next persistence commit. It supersedes the non-goal note in the
architecture doc when it ships.

## Decisions taken

1. **Events persist to one append-only table.** `agent_run_events`
   (core branch): `run_id`, `seq` (the existing `SequencedSink` sequence),
   `event`, `data` JSONB, `created_at`; PK `(run_id, seq)`. A `TeeSink`
   wraps the live `StreamSink`: emit → buffer → batched insert on its own
   short-lived session (never the run's session — the streaming-session
   ownership rule in the architecture doc stands). Batching: flush every
   N events or T ms (settings; defaults 20 events / 250 ms) — token
   deltas dominate volume and must not become row-per-token inserts.
   `NullSink` runs (scheduled/delegated) also tee — replay is exactly how
   a user later "watches" a scheduled run — behind a setting if write
   volume proves it needs one.
2. **Replay is `Last-Event-ID`-shaped but explicit.** New endpoint
   `GET /conversations/{id}/runs/{run_id}/events?after_seq=N` streaming
   SSE: first the persisted rows `> N` in order, then — if the run is
   still live — bridge to the live feed. The bridge is the hard part:
   subscribe to the live sink *before* reading the tail of the table,
   then dedupe by `seq` (emit-once guarantee comes from the monotonic
   seq, not from timing). Live subscription fan-out: a per-process
   in-memory multi-subscriber wrapper over the existing sink (one run is
   hosted by exactly one process — the lease guarantees it), **plus**
   Postgres `LISTEN/NOTIFY` only as the cross-instance wake-up ("new rows
   exist for run X"), with the table as the source of truth. NOTIFY
   payloads carry no event data.
3. **The primary turn stream stays exactly as it is.** The POST
   turn/create/resume streams and their protocol are untouched; replay is
   a second read-only surface the client uses on reconnect. The stream
   protocol version header applies to both.
4. **Client behavior: heal, then replay.** On mount with an active run,
   the client keeps the existing heal (persisted messages) and then opens
   the replay stream from the last sequenced event it saw (or 0),
   folding events through the same reducer. The reducer must be
   idempotent against events it already applied from the original live
   stream (seq gives it the tool to be).
5. **Retention: short.** Events are a transport convenience, not a
   record — audit rows and messages are the record. Sweep terminal runs'
   events after `AGENT_RUN_EVENTS_RETENTION_HOURS` (default 24) via a
   `030` jobs sweep kind. No export, no UI history surface built on the
   raw event log.
6. **Thinking deltas replay too** (they ride the same protocol since
   012); no special-casing — whatever the live stream carried, the log
   carries.

## Why this matters (when it does)

Long runs are the product's trajectory: compaction (056) makes long
conversations viable, fan-out (057) makes turns do more, scheduled runs
(NullSink) already produce results nobody watched being made. The
in-memory-only stream is the last place where a refresh loses live
signal. It is deliberately last because the heal loop is a decent
fallback and every other Lane H item changes what agents can *do* — this
one only changes what users *see* mid-run.

## Current state

Anchors from `c2f08cc` (2026-07-07) — **re-verify all of these at
execution time; this plan expects drift**:

- **Sinks**: `services/agents/runtime/sinks.py` — `SequencedSink` owns
  `run_id`/`conversation_id`/monotonic `_seq` (33-49); `StreamSink`
  queue/detach/close (76-123); `NullSink` discards (52-59);
  `format_sse_event` (126-129). The tee point is `SequencedSink._event`
  — every emitted event passes through it with its final seq.
- **Drain**: `services/agents/runtime/streaming.py` — keepalive comments,
  `X-Praxis-Stream-Version: 1` on turn streams.
- **Heal**: `apps/web/src/features/conversations/hooks/
  use-conversation-heal-loop.ts` + `get_active_run` route — refresh
  re-fetches persisted state; no event replay.
- **Protocol**: `stream/protocol.ts` mirrors `events.py`; parser throws
  on unknown event names — replay must emit only existing names (it
  does — it replays them verbatim).
- **Non-goal note**: `docs/architecture/agent-turn-streaming-plan.md` —
  superseded by this plan when it ships.
- **Lease/ownership**: one process hosts a run (lease +
  `owner_instance_id`) — decision 2's single-writer assumption.
- **Jobs**: 030 sweep-kind pattern (`jobs.sweep_terminal`,
  `files.sweep_deleted`, `rate_limits.sweep_attempts` precedents).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `cd apps/api && uv run ruff check . && uv run ruff format --check .` | exit 0 |
| Migration | `cd apps/api && DATABASE_URL=... uv run alembic check` + round-trip | clean |
| Focused tests | `cd apps/api && TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/routes/conversations tests/services/jobs -q` | all pass |
| Frontend gate | `cd apps/web && pnpm check` | all gates pass |
| Manual smoke | `make dev`; refresh mid-long-turn | token flow resumes within ~1s, no duplicated rows |

## Scope

**In scope:**

- `models/agent_run_event.py` + core migration; retention sweep job
- `services/agents/runtime/sinks.py` (TeeSink; batching; settings)
- Replay service + route (`services/conversations/replay_run_events.py`,
  `routes/conversations/stream_run_events.py`) with the
  subscribe-then-read-dedupe bridge (decision 2)
- LISTEN/NOTIFY wake-up helper (cross-instance case only)
- `apps/web` `stream/`: replay client + reducer idempotency by seq;
  heal-loop integration (decision 4)
- Settings: batch size/interval, retention hours, NullSink tee toggle
- `docs/architecture/agent-turn-streaming-plan.md` supersession note
- Tests: tee batching/ordering, replay-only (terminal run), replay-bridge
  (live run, seam dedupe), cross-instance wake-up, sweep; scenario
  addition (055); frontend Vitest for reducer idempotency (the C01 lane
  covers the stream parser/reducer — extend it)

**Out of scope (do NOT touch):**

- The primary POST turn-stream contract and event vocabulary.
- Redis/brokers (standing decision), any event-sourcing ambitions (audit
  rows and messages remain the record), event log UI surfaces.
- Multi-region concerns.

## Git workflow

- Branch: `advisor/060-durable-stream-replay`
- Commits: `API - Run Event Log & Replay` / `Web - Stream Replay On
  Reconnect`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

1. **Model + migration + sweep** (decision 1/5). *Verify*: round-trip;
   sweep test.
2. **TeeSink** with batched own-session writes; wire into the three
   spawn sites' sink construction; flush-on-close guarantees the
   terminal `done` row lands. *Verify*: unit tests — ordering, batching
   boundaries, close-flush, failure isolation (a DB hiccup in the tee
   must not kill the run: log + drop batch + keep streaming live).
3. **Replay route** with the bridge (decision 2): terminal-run replay;
   live-run replay joining mid-stream with zero dup/zero gap across the
   seam (test seeds a controlled race). Workspace/actor scoping mirrors
   `get_active_run`. *Verify*: route tests incl. the seam race.
4. **Cross-instance wake-up** via LISTEN/NOTIFY polling fallback
   (interval setting) — the replay host may not host the run. *Verify*:
   two-session test simulating the remote case (writer session +
   listener session).
5. **Client** (decision 4) + Vitest reducer idempotency. *Verify*:
   `pnpm check`; manual refresh smoke; delegated/scheduled run "watch
   later" smoke if NullSink tee is enabled.
6. **Docs**: supersede the non-goal note; agent-runtime.md streaming
   section update.

## Test plan

~14-18 tests across tee (4-5), replay/bridge (4-5, the seam race is the
centerpiece), wake-up (2), sweep (1-2), reducer idempotency (2-3
Vitest). Plus one scenario: cancelled run (053) replays to a `done
{cancelled}` terminal.

## Done criteria

- [ ] Every live-streamed event of a run is durably readable in order by
      `(run_id, seq)` until retention; terminal events always flushed
- [ ] Reconnect mid-run resumes live token flow via replay+bridge with
      no duplicates and no gaps (raced test proves the seam)
- [ ] Streaming hot path adds only batched fire-and-forget writes; a tee
      failure never degrades the live stream
- [ ] Event rows sweep on the jobs harness; no new event names; protocol
      version honored on the replay surface
- [ ] Architecture doc non-goal superseded;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The sink/protocol layer has drifted from the excerpts (expected — this
  plan runs last): re-verify and re-anchor before writing code; report
  if the tee point (`SequencedSink._event`) no longer exists.
- Write volume measurements show token-delta batching cannot keep p95
  turn latency flat — bring numbers; options (coarser deltas in the log,
  sampling) are product decisions.
- The bridge cannot be made gap-free without holding the run's own
  session or blocking emit — the design requires neither; report the
  constraint.
- You are tempted to widen this into event sourcing, a notification
  transport, or an audit substitute.

## Maintenance notes

- If a future notifications transport wants server push, it gets its own
  design — this log is run-scoped transport, deliberately swept.
- The NullSink tee toggle is the cost lever: if scheduled-run write
  volume is noise, disable and lose only the "watch a scheduled run
  live-after-the-fact" nicety.
- Reviewers should scrutinize: the seam dedupe under a seeded race, the
  close-flush guarantee for terminal events, and tee failure isolation.
