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

## Platform Knowledge processing

`kb.platform_ingest_document` and `kb.platform_embed_chunks` use the initiating
super admin's concurrency ownership. They reject workspace-owned, unowned, and
malformed jobs before deliberate maintenance access. Each attempt rechecks the
active actor and the document's expected ingestion version. Provider calls run
outside document transactions; locked rechecks discard stale results after an
edit, withdrawal, or deletion. Successful processing never publishes content.
Retries retain the existing job leases and bounded attempts. See the
[Knowledge source reference](knowledge-sources.md#platform-authoring-and-ingestion)
for publication and pinned File retention.

## Platform Artifact maintenance

Startup ensures the unowned `platform.artifacts.sweep_deleted` job. Each pass
purges at most 100 expired platform revisions and their copy stages, removing
restored versions before their sources. It shares the private File retention
period and sweep interval. Failed deletions retain database ownership for retry.

Edit and restore requests independently reserve one
`platform.artifacts.cleanup_object` system job before writing bytes. After a
five-minute grace period, the handler locks the parent, waits for its transaction
to finish, and removes the object only if its revision did not commit. A lost
commit response cannot make the cleanup remove committed content. Both job kinds
require explicit maintenance access and reject workspace or user concurrency
ownership before storage work.

Failed or cancelled orphan-cleanup jobs remain outside ordinary terminal-job
retention. Their payload retains the object identity after automatic retries are
exhausted. Successful cleanup jobs follow normal job retention.

Workspace Artifact copies reserve their immutable destination through
`artifacts.cleanup_copy`. The workspace-owned job waits five minutes before
checking whether the exact local revision committed. It deletes only missing
revision output and the deterministic copy stage. Copy saves hold the pending
job row through commit, so cleanup cannot race the destination write. Failed
or cancelled cleanup jobs stay outside terminal retention.
