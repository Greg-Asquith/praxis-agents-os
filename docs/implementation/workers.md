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
