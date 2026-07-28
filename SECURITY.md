# Security Policy

## Supported versions

Praxis Agents OS is currently in the `0.x` release series. Security fixes are
provided for the latest `0.x` minor release only.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting flow: open the repository's
**Security** tab, choose **Report a vulnerability**, and submit the report
privately. Include the affected version, reproduction details, likely impact,
and any suggested mitigation.

The maintainer aims to acknowledge reports within five working days. This is a
target, not a service-level agreement. Updates will follow as the issue is
validated and a remediation path is established.

## Deployment hardening

Do not leave registration open while claiming the first super-admin identity.
For a new deployment:

1. Deploy with `ALLOW_SIGNUP=false`.
2. Register or provision the intended administrator through a controlled path.
3. Set `SUPER_ADMIN_EMAILS` only after that account exists and is under the
   operator's control.
4. Enable general signup only if the deployment intends to allow it.

Never use the public `.env.example` secret values outside
`ENVIRONMENT=local`. Production deployments must use secure cookies,
cloud-backed storage, and a cloud secret manager. See the
[completed deployment security review](docs/plans/complete/deployment-000-security-review.md)
for the deployment-hardening decisions and accepted-risk process.
