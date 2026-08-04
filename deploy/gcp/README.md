# GCP deployment runbook

The reusable GCP deployment helpers and the rest of this runbook land in
[deployment plan 002.5](../../docs/plans/deployment/002.5-deploy-gcp-helpers.md).
The application-encryption rotation procedure is available now because it is a
production-readiness prerequisite from plan 002.4.

## Key rotation paths

These three roots are independent and must not be rotated with the same
procedure:

- `SECRET_KEY` signs transient application tokens and CSRF tokens. Rotation
  invalidates those signatures; an emergency rotation also requires the
  session-purge procedure that will be documented with the deployment helpers.
- Credential-vault roots use the logical provider reference in
  `CREDENTIAL_MASTER_KEY_SECRET_NAME`. Deploy `new,old`, run
  `integrations.rotate_credential_encryption`, prove that no live credential
  has a stale `encryption_key_id`, then remove `old`.
- Application encryption keys use the logical provider reference in
  `ENCRYPTION_KEYS_SECRET_NAME` and use the procedure below.

## Application encryption key ring

The Cloud Run API and worker service accounts resolve the key-ring secret
through their attached service identities and the configured
`gcp_secret_manager` provider. Do not use downloaded service-account key files.
The configured name is logical: the GCP provider maps it to the physical
Secret Manager ID `praxis-${sha256(logical_name)}`. Plan 002.5's bootstrap
helper must create and grant access to that mapped physical secret rather than
a literal secret named after the setting value. The secret value is a
newest-first comma-separated list or JSON array of Fernet keys.

1. Add the new key at the head of the secret value, keeping every current key,
   then redeploy or restart the API and worker so both load the new ring.
2. Run `python -m bin.application_encryption converge` as a one-off execution
   of the API/worker image with the worker service account and normal runtime
   configuration.
3. Run `python -m bin.application_encryption check`. Its JSON result must have
   `stale == 0` and `undecryptable == 0`. Stop and investigate any non-zero
   count.
4. Remove the old key from the secret, then redeploy or restart the API and
   worker.
5. Run the check command again and require zero stale and undecryptable values.

The convergence result reports stale values found before rewriting, so it is
not the removal proof. The dedicated checks in steps 3 and 5 are the gates.
Short-lived OAuth browser-binding cookies are not rewritten and should be given
their normal expiry window before removing a key.
