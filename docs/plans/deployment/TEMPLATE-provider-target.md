<!-- docs/plans/deployment/TEMPLATE-provider-target.md -->

# 00X — <Provider>: <runtime choice>, scale to zero

Status: Template — copy this file to start a new cloud target plan.
Written: <date>
Depends on: 001 (health endpoints, migrate-before-serve, web build args),
worker drain mode (landed with 002), and the decisions recorded at the end
of `002-gcp-cloud-run.md`.

How to use: this is the GCP plan's skeleton with the provider column
blanked. The left column (the deployment target contract, cross-cutting
code, verification, STOP conditions) should barely change between
providers; fill in the right column and delete guidance comments. If you
find yourself changing app code for a provider, first check whether the
change belongs in the contract (all providers) instead.

## Provider mapping

Fill in the concrete service for each contract capability
(see `000_README.md` for what each row means):

| # | Capability | GCP (reference) | <Provider> |
| --- | --- | --- | --- |
| 1 | API container runtime (HTTP + SSE, `PORT`-aware) | Cloud Run service | e.g. Azure Container Apps / AWS App Runner or ECS Fargate |
| 2 | Web static hosting | Cloud Run service (nginx image) | e.g. ACA / S3+CloudFront / Cloudflare Pages (drop the nginx image if the host serves `dist/` natively) |
| 3 | Worker run-to-completion execution | Cloud Run Job (`WORKER_MODE=drain`) | e.g. ACA Jobs / ECS scheduled task |
| 4 | Cron trigger | Cloud Scheduler → jobs.run | e.g. ACA cron trigger / EventBridge Scheduler |
| 5 | Postgres 17 + pgvector | Cloud SQL (unix-socket connection) | e.g. Azure Flexible Server / RDS — note the async driver connection string shape |
| 6 | Secret store | Secret Manager (`SECRET_PROVIDER=gcp_secret_manager`) | `azure_key_vault` (needs `AZURE_KEY_VAULT_URL`) / `aws_secrets_manager` (needs `AWS_REGION`) — already implemented in `services/secrets/` |
| 7 | Object storage + signed URLs | GCS (`STORAGE_PROVIDER=gcs`) | `azure_blob` (needs user-delegation-key permissions — see `.env.example` note) / `s3` — already implemented in `services/storage/` |
| 8 | Email | SES/SendGrid (D10 of 002) | provider or keep the cross-cloud choice from 002 |
| 9 | DNS/TLS/same-site origins | Domain mappings, `COOKIE_DOMAIN` | provider TLS + the same subdomain/cookie shape (D1 of 002) |
| — | Build extra | `--build-arg CLOUD_EXTRA=gcp` | `CLOUD_EXTRA=azure` / `CLOUD_EXTRA=aws` (pyproject extras exist) |
| — | CI identity | Workload Identity Federation | e.g. Azure federated credentials / AWS OIDC role |

Cloudflare note: rows 1/3/5 have no native Cloudflare answer for a Python
container; a Cloudflare target is realistically "web on Pages/Workers +
API/worker elsewhere" — decide that split before copying this template.

## Design decisions

Copy D1–D10 from 002 and re-answer each for this provider. Keep the same
numbering so the plans stay comparable. Flag any decision where the
provider forces a different answer than GCP — those differences are the
whole content of this plan.

## Tasks

Mirror 002's stages; Stage 0 should be empty or near-empty (cross-cutting
code landed with 001/002). If Stage 0 grows, stop and move the work into
the shared contract.

- Stage 1 — provider foundation (one-time resources)
- Stage 2 — services and jobs, first manual deploy, domains/cookies/OAuth
- Stage 3 — CI/CD lane (build once, migrate, deploy; keyless auth)
- Stage 4 — fast-follows (event-driven job trigger, cost review, record
  decisions taken)

## Verification

Use 002's verification list verbatim — it is provider-independent by
design (SSE conversation with approval, drain-on-redeploy, failing
migration blocks deploy, overlapping worker runs process once, settings
validation boots with this provider's env shape).

## STOP conditions

Same as 002, plus: STOP if this provider requires loosening any
`validate_runtime_provider_config` rule or cookie/CSRF/CORS setting.
