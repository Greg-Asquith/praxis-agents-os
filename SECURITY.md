# Security policy

## Supported versions

Praxis Agents OS is in the `0.x` release series. Security fixes are
provided for the latest `0.x` minor release only.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Report a vulnerability

Don't open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting flow: open the repository's
**Security** tab, choose **Report a vulnerability**, and submit the report
privately. Include the affected version, reproduction details, likely impact,
and any suggested mitigation.

The maintainer aims to acknowledge reports within five working days. This is a
target, not a service-level agreement. The maintainer provides updates after
validating the issue and identifying a remediation path.

## Dependency audit policy

CI audits the locked production dependency sets for both applications. The API
audit exports hashed requirements from `apps/api/uv.lock` without development
dependencies and fails on every known advisory. The web audit reads
`apps/web/pnpm-lock.yaml`, includes only production dependencies, and fails on
high or critical advisories. Scanner or registry failures also fail the job.
Development-only and low or moderate web findings are reviewed through routine
dependency maintenance but are not release blockers.

The audit allowlist is
`.github/dependency-audit-allowlist.json` and should normally remain empty. A
temporary exception must identify the `ecosystem` (`python` or `npm`), affected
`package`, scanner `advisory` ID, specific `rationale`, accountable `owner`, and
an ISO `expires` date. npm exceptions use GHSA IDs. Expiry is exclusive: an
entry fails CI on its expiry date, before the scanner runs. Remove exceptions
when the dependency is fixed. Extending one requires a new risk review.

From the repository root, run the same audits locally:

```bash
python3 .github/scripts/dependency_audit.py api
python3 .github/scripts/dependency_audit.py web
```

## Harden a deployment

Do not leave registration open while claiming the first super-admin identity.
To claim the first super-admin identity safely:

1. Deploy with `ALLOW_SIGNUP=false`.
2. Register or provision the intended administrator through a controlled path.
3. Set `SUPER_ADMIN_EMAILS` only after that account exists and is under the
   operator's control.
4. Enable general signup only if the deployment intends to allow it.

Never use the public `.env.example` secret values outside
`ENVIRONMENT=local`. Production deployments must use secure cookies,
cloud-backed storage, and a cloud secret manager. The
[GCP deployment runbook](deploy/gcp/README.md) shows the supported production
setup, and the [threat model](docs/architecture/threat-model.md) records the
security boundaries maintainers must preserve.
