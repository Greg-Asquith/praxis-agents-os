# Google Cloud deployment runbook

Use this checklist to create and deploy one Praxis environment on Google Cloud
Run. Every command names its project and region. Keep real environment files
and secret payloads outside Git; the ignored `.local/` directory is suitable.

The `bootstrap.sh` script prints each change and requires you to enter `yes`.
Don't run it in continuous integration (CI). The script generates database
credentials and core application secrets in memory. It writes them directly
to Cloud SQL and Secret Manager without printing or storing them on disk.

For each shell session, set the variables that later commands use:

```bash
ENV_FILE=.local/praxis-staging.env
PROJECT=praxis-example-staging   # = GCP_PROJECT_ID in the env file
REGION=europe-west2              # = GCP_REGION
```

## Prepare each operator machine

- [ ] Install Docker, `gcloud`, and Python 3.12+.
- [ ] `gcloud auth login` as a human operator. Never download a
      service-account JSON key; never use the default Compute Engine SA.
- [ ] The helper syntax is verified against Google Cloud SDK 578.0.0. For a
      later SDK, check each command with `gcloud help COMMAND` before running
      it. Replace `COMMAND` with the `gcloud` command name.

## Create an environment

### 1. Create the project and environment file

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

### 3. Add the remaining secret versions

- [ ] LLM provider keys (created in the provider consoles) for every
      provider bound in `RUNTIME_SECRET_BINDINGS` — paste the key at the
      silent prompt:

```bash
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-openai-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-anthropic-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-google-api-key --data-file=- --project=$PROJECT --quiet; unset KEY; echo
printf 'API key: ' && read -rs KEY && printf '%s' "$KEY" | gcloud secrets versions add praxis-google-oauth-client-secret --data-file=- --project=$PROJECT --quiet; unset KEY; echo
# seed only the secrets bound in RUNTIME_SECRET_BINDINGS, including each
# enabled login provider's OAuth client-secret binding
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

### 4. Complete the first deployment

- [ ] Optional local preview:
      `deploy/gcp/deploy.sh --render-only /tmp/praxis-render $ENV_FILE`
- [ ] `make gcp-deploy ENV_FILE=$ENV_FILE`
- [ ] Until this first deployment completes, the Scheduler trigger fails every
      minute with `NOT_FOUND` because the deployment creates the
      `praxis-worker` job. These expected failures stop after deployment.

### 5. Create the first super admin

With `ALLOW_SIGNUP=false`, sign in using the configured Google or Microsoft
provider and the exact verified email in `SUPER_ADMIN_EMAILS`. That OAuth login
creates the first user and personal workspace; every other unknown OAuth user
remains rejected. No password or temporary public-signup window is required.

### 6. Configure public access, domains, and external platforms

The scripts stop after creating private Cloud Run services. Complete these
public access steps manually:

- [ ] Allow unauthenticated invocation of both services:

```bash
gcloud run services add-iam-policy-binding praxis-api --member=allUsers --role=roles/run.invoker --project=$PROJECT --region=$REGION --quiet
gcloud run services add-iam-policy-binding praxis-web --member=allUsers --role=roles/run.invoker --project=$PROJECT --region=$REGION --quiet
```

- [ ] Map the custom domains from the env file (`APP_BASE_URL`,
      `FRONTEND_URL`) and create the DNS records each mapping prints:

```bash
gcloud beta run domain-mappings create --service=praxis-api --domain=api.DOMAIN --project=$PROJECT --region=$REGION
gcloud beta run domain-mappings create --service=praxis-web --domain=app.DOMAIN --project=$PROJECT --region=$REGION
```

Replace `DOMAIN` with your deployment's domain, such as `example.com`.

- [ ] Register the login OAuth redirect URI (`https://app.DOMAIN/oauth/callback`)
      and integration redirect URI (`INTEGRATIONS_OAUTH_REDIRECT_URI`) in each
      enabled provider's console.

There is no CI deploy workflow; deploys run from an authenticated operator
machine with `make gcp-deploy ENV_FILE=$ENV_FILE`.

### 7. Verify the environment

- [ ] API healthy: `curl -fsS https://api.DOMAIN/healthz`
      (`/readyz` checks the database; never wire it as a Cloud Run probe).
- [ ] Worker drains cleanly:
      `gcloud run jobs execute praxis-worker --wait --project=$PROJECT --region=$REGION --quiet`
- [ ] Scheduler executions run each minute and exit 0.
- [ ] Public-assets bucket: a representative object is anonymously readable
      while listing and anonymous writes fail. (The bucket holds only
      application-owned avatars/icons under `users/` and `workspaces/`;
      workspace buckets are separate and private.)

## Deploy a change

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

## Rotate secrets and keys

Rotate application and credential root keys annually. Rotate provider
credentials at least every 90 days where supported. Rotate any credential
immediately if you suspect exposure. Adding a Secret Manager version alone
doesn't complete rotation. Each value has a convergence path:

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
  pass before removing the old key. The
  [backend rotation guide](../../apps/api/README.md#rotate-application-encryption-keys)
  explains the complete converge, check, remove, and re-check sequence.

## Test backup restoration

Each quarter and before production use, restore into an isolated, approved
rehearsal instance. An enabled backup doesn't prove that you can recover data:

```bash
gcloud sql backups list --instance=praxis-postgres --limit=20 --project=$PROJECT --format=json --quiet
gcloud sql backups restore BACKUP_ID --backup-instance=praxis-postgres --restore-instance=ISOLATED_RESTORE_INSTANCE --project=$PROJECT --quiet
```

Record the backup id/time, achieved RPO/RTO, migration result, and a
representative conversation/file flow. Customer offboarding is intentionally
not automated: require a separately approved, two-person procedure before
destroying an environment or its backups.

## Verify local helpers

From the repository root, run the deployment checks and ShellCheck:

```bash
make gcp-check
shellcheck deploy/gcp/bootstrap.sh deploy/gcp/deploy.sh deploy/gcp/tests/test.sh
```

`make gcp-check` runs Bash syntax checks, helper tests, a render-only pass,
manifest type assertions, and a missing-variable failure test. Shellcheck is
an operator/CI tool, not a repository dependency.
