# Background workers

Read this before changing job admission, leases, drain mode, or shutdown.
Worker entry points live under `apps/api/workers/`.

## Execution and ownership

Background work runs in the worker process (`python -m workers.main`),
which supervises the scheduled-agent runner (croniter schedules, TTL leases
with heartbeats, terminal failure states) and the generic jobs runner over
the SKIP-LOCKED `jobs` table. `WORKER_MODE=forever` is the local/service
default; `WORKER_MODE=drain` runs both queues to empty without polling sleeps
and exits 0 when drained or when `WORKER_DRAIN_MAX_SECONDS` requests a clean
stop. Both queues share `WORKER_MAX_CONCURRENT_RUNS` execution slots. Generic
jobs renew their owner-bound leases while handlers run, and stale owners
cannot persist success or failure results. When a heartbeat confirms
ownership loss, the worker cancels that handler and rolls back its open
transaction. Handlers that commit intermediate work or call external systems
must remain idempotent because cancellation cannot undo completed effects.
Each admission reserves a shared
execution slot before claiming one row, so shutdown cannot strand claimed work
behind the concurrency bound. The supervisor repeats both runners until they
complete one jointly idle validation round. When the drain budget expires,
waiting admissions stop before claiming and admitted work finishes within the
platform task timeout. Ordinary service shutdown still bounds each in-flight
pass with its runner-specific grace setting. Generic jobs use mutually
exclusive workspace or user
concurrency ownership; authenticated work must use one of those buckets,
while `NULL` ownership is reserved for system work. Queue new background work
as jobs rather than inventing ad-hoc task mechanisms.

Abandoned agent executions use the recurring `agent_runs.sweep_abandoned` job.
Startup ensures a pending or running sweep, and each successful sweep queues
its successor after `AGENT_RUN_REAPER_INTERVAL_SECONDS`, which defaults to 30.
The job and lazy conversation recovery call the same root-first family service.
Local execution deadlines also stop healthy-heartbeat runs without a reader
or recovery job.

Agent execution owns its heartbeat through bounded finalisation. A committed
completion or approval suspension does not interrupt its own finaliser.
Shutdown failures remain distinct from human cancellation, and scheduled-run
settlement uses a bounded cleanup path.

## Platform File maintenance

Platform File extraction uses the actor-owned `files.extract_platform` kind.
It checks the initiating user's active super-admin authority and opens explicit
maintenance transactions for platform subjects. Conversion runs outside the
write transaction, followed by a locked version and lifecycle recheck.

Startup also ensures `platform.files.sweep_deleted` and
`platform.files.sweep_uploads`. These system jobs require an unowned maintenance
session and retain failed deletions for retry. Each pass handles at most 100
revisions or 100 upload grants. Workspace retention jobs exclude platform rows.
See the [storage reference](storage-and-files.md#platform-upload-and-maintenance-services)
for upload, extraction, and retention boundaries.
