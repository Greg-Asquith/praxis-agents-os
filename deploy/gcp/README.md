# GCP deployment runbook

Checklist for standing up and deploying one Praxis environment on Cloud Run.
Every command is explicit about project and region; nothing selects a project
implicitly. Real env files and secret payloads stay outside git (`.local/` is
gitignored and suitable). `bootstrap.sh` is interactive by design: it prints
each mutation and requires a typed `yes`; never run it from CI. It never
accepts or prints secret values. It generates database credentials and core
application secrets in memory and writes them directly to Cloud SQL and Secret
Manager without storing them on disk.

Set these once per shell session; the commands below use them:

```bash
ENV_FILE=.local/praxis-staging.env
PROJECT=praxis-example-staging   # = GCP_PROJECT_ID in the env file
REGION=europe-west2              # = GCP_REGION
```

## One-time per machine

- [ ] Install Docker, `gcloud`, and Python 3.12+.
- [ ] `gcloud auth login` as a human operator. Never download a
      service-account JSON key; never use the default Compute Engine SA.
- [ ] Helper syntax was verified against Google Cloud SDK 578.0.0. On a newer
      SDK, spot-check the leaf commands you are about to run with
      `gcloud help <command>` first.

## New environment (once per GCP project)

### 1. Project and env file

- [ ] Create the GCP project and link billing (console or `gcloud` — outside
      bootstrap by design). One project per customer production deployment.
- [ ] `cp deploy/gcp/.env.example $ENV_FILE` and fill **every** value. The
      example file documents each variable, including the model/provider
      settings and public URLs the manifests are rendered from.
- [ ] Keep `ALLOW_SIGNUP=false` for a closed environment and set
      `SUPER_ADMIN_EMAILS` to the email address of the first operator.
- [ ] For OAuth-only access, set `EMAIL_AUTH_ENABLED=false`, enable at least
      one login provider, and fill its client ID and `/oauth/callback` redirect
      URI. Add its client secret to `RUNTIME_SECRET_BINDINGS`; for example,
      `GOOGLE_OAUTH_CLIENT_SECRET=praxis-google-oauth-client-secret`.

### 2. Bootstrap

- [ ] `make gcp-bootstrap ENV_FILE=$ENV_FILE` — creates Artifact Registry,
      Cloud SQL (instance, database, and password-backed users), the
      public-assets bucket with explicit-origin browser-upload CORS, Secret
      Manager resources, service accounts and custom roles, the Scheduler
      trigger, and log/audit config.
      It generates and stores the database credentials, database URLs,
      `SECRET_KEY`, and `METRICS_TOKEN`; generated values are redacted from
      previews and never written to disk. Provider and application key-ring
      secrets remain empty for the next step.
      Re-running is safe: unchanged sections are skipped without a prompt.

### 3. Remaining secret versions

- [ ] LLM provider keys (created in the provider consoles) for every
      provider bound in `RUNTIME_SECRET_BINDINGS` — paste the key at the
      silent prompt:

```bash
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-openai-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-anthropic-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-google-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-google-oauth-client-secret --data-file=- --project=$PROJECT --quiet; unset KEY; echo
# repeat for praxis-anthropic-api-key, praxis-google-api-key, ...
# also seed each enabled login provider's OAuth client-secret binding
```

- [ ] The two application key rings live under hashed secret ids the
      application derives from their logical names (`helpers.py secret-id`
      mirrors that mapping). From anywhere inside the repository, return to
      its root and seed each with one fresh Fernet key. Key generation uses
      only the Python standard library, so the API virtualenv is not required:

```bash
FERNET_KEY=$(python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())') && printf '%s' "$FERNET_KEY" | gcloud secrets versions add "$(python3 deploy/gcp/helpers.py secret-id application-encryption-keys)" --data-file=- --project=$PROJECT --quiet; unset FERNET_KEY
FERNET_KEY=$(python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())') && printf '%s' "$FERNET_KEY" | gcloud secrets versions add "$(python3 deploy/gcp/helpers.py secret-id credential-master-key)" --data-file=- --project=$PROJECT --quiet; unset FERNET_KEY
```

      At rotation time the payload becomes a newest-first, comma-separated
      key list (`new,old`) — see the rotation section below.

### 4. First deploy

- [ ] Optional local preview:
      `deploy/gcp/deploy.sh --render-only /tmp/praxis-render $ENV_FILE`
- [ ] `make gcp-deploy ENV_FILE=$ENV_FILE`
- [ ] Until this first deploy completes, the Scheduler trigger fails every
      minute with NOT_FOUND (the `praxis-worker` job does not exist yet).
      That is expected and stops on its own.

### 4a. First super admin

With `ALLOW_SIGNUP=false`, sign in using the configured Google or Microsoft
provider and the exact verified email in `SUPER_ADMIN_EMAILS`. That OAuth login
creates the first user and personal workspace; every other unknown OAuth user
remains rejected. No password or temporary public-signup window is required.

### 5. Public access, domains, external platforms

None of this is automated; the scripts stop at private Cloud Run services.

- [ ] Allow unauthenticated invocation of both services:

```bash
gcloud run services add-iam-policy-binding praxis-api --member=allUsers --role=roles/run.invoker --project=$PROJECT --region=$REGION --quiet
gcloud run services add-iam-policy-binding praxis-web --member=allUsers --role=roles/run.invoker --project=$PROJECT --region=$REGION --quiet
```

- [ ] Map the custom domains from the env file (`APP_BASE_URL`,
      `FRONTEND_URL`) and create the DNS records each mapping prints:

```bash
gcloud beta run domain-mappings create --service=praxis-api --domain=api.<your-domain> --project=$PROJECT --region=$REGION
gcloud beta run domain-mappings create --service=praxis-web --domain=app.<your-domain> --project=$PROJECT --region=$REGION
```

- [ ] Register the login OAuth redirect URI (`https://app.<your-domain>/oauth/callback`)
      and integration redirect URI (`INTEGRATIONS_OAUTH_REDIRECT_URI`) in each
      enabled provider's console.
      
There is no CI deploy workflow; deploys run from an authenticated operator
machine with `make gcp-deploy ENV_FILE=$ENV_FILE`.

### 6. Verify

- [ ] API healthy: `curl -fsS https://api.<your-domain>/healthz`
      (`/readyz` checks the database; never wire it as a Cloud Run probe).
- [ ] Worker drains cleanly:
      `gcloud run jobs execute praxis-worker --wait --project=$PROJECT --region=$REGION --quiet`
- [ ] Scheduler executions run each minute and exit 0.
- [ ] Public-assets bucket: a representative object is anonymously readable
      while listing and anonymous writes fail. (The bucket holds only
      application-owned avatars/icons under `users/` and `workspaces/`;
      workspace buckets are separate and private.)

## Every deploy

- [ ] `make gcp-deploy ENV_FILE=$ENV_FILE` — builds and pushes both images
      tagged with the git SHA (override via `GIT_SHA=...`), replaces and
      waits for the migration job, then replaces the API, web, and worker.
      A failed migration stops the script before any serving revision
      changes. Re-running the same SHA is safe.
- [ ] If the migration failed: do not deploy the services. Inspect the
      failed execution, fix the forward migration, rerun the same SHA.
      Never roll the shared schema backward to match an old container.
- [ ] Rollback: the deploy prints the prior ready revisions and literal
      rollback commands, equivalent to:

```bash
gcloud run services update-traffic praxis-api --to-revisions=PREVIOUS_REVISION=100 --project=$PROJECT --region=$REGION --quiet
gcloud run services update-traffic praxis-web --to-revisions=PREVIOUS_REVISION=100 --project=$PROJECT --region=$REGION --quiet
```

- [ ] Crash-on-boot triage:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="praxis-api"' --limit=20 --project=$PROJECT --format=json --quiet
```

## Rotation schedule

Application and credential root keys annually, provider credentials at least
every 90 days where supported, anything suspected exposed immediately.
Adding a Secret Manager version alone is **not** rotation — each value has a
convergence path:

- `SECRET_KEY`: add the new version and deploy; signed transient/CSRF tokens
  are invalidated. In an emergency rotation, also purge database-backed
  sessions as part of the incident procedure.
- Credential root: publish `new,old`, deploy, run
  `integrations.rotate_credential_encryption`, prove no live stale
  `encryption_key_id`, then publish only `new` and deploy again.
- Application encryption: publish `new,old`, run
  `python -m bin.application_encryption converge`, then
  `python -m bin.application_encryption check` until `stale` and
  `undecryptable` are both zero. Remove `old`, redeploy, check again.
  OAuth browser-binding cookies are not rewritten; let their normal expiry
  pass before removing the old key. Full procedure:
  `docs/plans/deployment/002.4-encryption-key-ring.md`.

## Backup restore rehearsal (quarterly and before production)

Restore into an isolated, already-approved rehearsal instance — the
backup-enabled flag is not proof of recoverability:

```bash
gcloud sql backups list --instance=praxis-postgres --limit=20 --project=$PROJECT --format=json --quiet
gcloud sql backups restore BACKUP_ID --backup-instance=praxis-postgres --restore-instance=ISOLATED_RESTORE_INSTANCE --project=$PROJECT --quiet
```

Record the backup id/time, achieved RPO/RTO, migration result, and a
representative conversation/file flow. Customer offboarding is a separately
approved two-person operation — follow D11 in the deployment plan; it is
intentionally not automated.

## Local verification of these helpers

```bash
make gcp-check
shellcheck deploy/gcp/bootstrap.sh deploy/gcp/deploy.sh deploy/gcp/tests/test.sh
```

`make gcp-check` runs Bash syntax checks, helper tests, a render-only pass,
manifest type assertions, and a missing-variable failure test. Shellcheck is
an operator/CI tool, not a repository dependency.
