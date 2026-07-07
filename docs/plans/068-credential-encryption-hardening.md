# Plan 068: Credential encryption posture — envelope encryption, key rotation, and key separation (amendments to 037/041/050)

> **Executor instructions**: This is an amendment plan in the 061 mold —
> its deliverable is the three amendment blocks drafted verbatim in Steps
> 1–3, appended to plans 037, 041, and 050. No code lands here; the code
> cost is absorbed into those plans' execution. When done, update the
> status row in `docs/plans/000_README.md`.
>
> **Drift check (run first)**:
> `git diff --stat c770a1c..HEAD -- docs/plans/037-integration-core-models-credentials.md docs/plans/041-first-integration-providers.md docs/plans/050-artifacts-model-serving.md apps/api/core/settings/ apps/api/utils/security.py`
> Compare the "Current state" quotes below against the live plan texts and
> code; a mismatch is a STOP condition. If 037 has started executing
> (`apps/api/services/integrations/`, `apps/api/services/secrets/`, or
> `apps/api/models/integrations.py` exists, or the 037 row in
> `docs/plans/000_README.md` is no longer TODO), STOP — reconcile with the
> landed code instead of amending a plan that already ran.

## Status

- **Priority**: P1
- **Effort**: S-M (plan amendments; the code cost is absorbed into
  037/041/050 execution)
- **Risk**: LOW as a doc — it *removes* a key-compromise blast-radius
  risk before any credential code exists
- **Depends on**: 037/041/050 (written, TODO). **Binds before 037
  executes** — the encryption seams change shape, and retrofitting them
  after credential rows exist is a data migration with security
  implications
- **Category**: Lane B — best-practice amendments (067–074, added
  2026-07-07)
- **Planned at**: working tree at commit `c770a1c`, 2026-07-07

## Decisions taken

1. **Middle path, not full KMS envelope encryption — explicit call.**
   Industry end-state for a credential vault is per-credential
   data-encryption keys wrapped by a KMS-held key-encryption key.
   Rejected for v1: a KMS unwrap per token decrypt adds latency and a
   hard runtime dependency on KMS availability to every integration
   call, and per-credential DEK wrapping is a materially larger schema
   and code change than Phase 4a needs. The middle path below removes
   the two actual defects (master key as a plain env var; rotation that
   never retires a key) at a fraction of the cost. **Full KMS envelope
   encryption (GCP Cloud KMS KEK wrapping per-credential DEKs) is the
   named end-state.** Revisit triggers: an external compliance demand
   (SOC 2 crypto controls, a customer security review requiring
   HSM-backed keys), multi-region key residency, or credential volume
   making single-master-key sweeps impractical.
2. **The credential master key lives in the secrets provider 037 itself
   builds, not an env var.** 037 ships `services/secrets/` with a GCP
   Secret Manager provider and a validator forcing it outside local —
   then leaves the highest-value secrets in the system (every
   customer's OAuth tokens) under an env-var Fernet key. Amendment:
   outside `ENVIRONMENT=local`, the credential root key resolves
   through the `services/secrets` seam at first use (cached per
   process, never at import time); the env-var form is a local-only
   fallback rejected by the same validator law that gates
   `SECRET_PROVIDER=local`. No circularity: the GCP provider
   authenticates via ADC and needs no Fernet key of its own.
3. **Purpose-specific subkeys via HKDF — auth keys never touch non-auth
   material.** A single `derive_purpose_key(root, purpose)` helper
   (HKDF-SHA256; `cryptography` is already a dependency; ~3 lines)
   yields: `praxis:credential-tokens:v1` (Fernet keys for OAuth token
   columns, from the credential root), `praxis:principal-fingerprint:v1`
   (HMAC key for 037's fingerprints, from the credential root — not
   `SECRET_KEY`), and `praxis:artifact-view-url:v1` (HMAC key for 050's
   view URLs, from `SECRET_KEY` — decision 6). Rotating the session/CSRF
   `SECRET_KEY` no longer orphans integration fingerprints — a coupling
   037's own maintenance note admits today.
4. **Rotation means a re-encryption sweep, not decrypt-compat forever.**
   037's rotation story is MultiFernet-style decrypt-with-old-keys only,
   so a compromised key can never actually be dropped while rows
   encrypted under it exist. The amendment adds an `encryption_key_id`
   column on `external_credentials` (making rotation progress queryable)
   and a job kind `integrations.rotate_credential_encryption` on the
   plan-030 jobs harness (DONE) that re-encrypts every live row under
   the newest key. Done criterion: after a sweep, all live rows decrypt
   with only the newest key — old keys droppable, proven by a test.
5. **Fingerprints cannot be re-derived by the sweep — recorded
   honestly.** The plaintext `external_principal_id` is deliberately not
   stored (only its HMAC), so a credential-root rotation leaves old
   fingerprints stale for dedup until connections re-authenticate. That
   is 037's already-accepted graceful-degradation posture — the
   amendment merely moves the trigger from every `SECRET_KEY` rotation
   (frequent, auth-driven) to credential-root rotation (rare,
   deliberate).
6. **050's view-URL key stays rooted in `SECRET_KEY`, but derived and
   versioned.** Artifact serving must not take a request-time (or
   boot-order) dependency on the secrets provider, and with a 300 s TTL
   a root rotation merely invalidates in-flight URLs — harmless. The
   actual defects are cross-protocol key reuse (the key signing sessions
   and CSRF also signing anonymous capability URLs) and an unversioned
   scheme that cannot rotate. Fix: HKDF purpose derivation plus a
   version prefix in the signed payload and the `sig` parameter, so a
   future scheme change (or a move to its own root) is additive.
7. **`GOOGLE_ADS_DEVELOPER_TOKEN` is a secret and gets `SecretStr`.**
   041 types it plain `str | None`; the codebase precedent is
   `ANTHROPIC_API_KEY: SecretStr | None` (`core/settings/models.py:69`)
   and the OAuth client secrets (`core/settings/auth.py:29-46`).
8. **`UserAuth` login tokens and TOTP secrets stay on `ENCRYPTION_KEY`.**
   Migrating existing encrypted auth rows is a data migration outside
   this posture change; the split (auth secrets on `ENCRYPTION_KEY`,
   integration credentials on the credential root) is itself key
   separation. Recorded as a future hardening pass, not implied.

## Why this matters

Integration OAuth tokens are the highest-value secrets the platform will
hold: one key decrypts every customer's tokens for every provider. Plan
037 gets the schema right, then anchors that entire class of secret to
`ENCRYPTION_KEY` — a plain env var in app memory — while simultaneously
building the GCP Secret Manager provider it declines to use for them.
And its rotation story cannot retire a key: `decrypt_data` tries old
keys forever, so "rotation" after a suspected compromise leaves every
existing row encrypted under the compromised key. These are exactly the
decisions that are free to change before 037 executes and a security
data migration afterward. The key-separation items (037 fingerprints,
050 view URLs) are the same class of cheap-now fix: three uses of one
`SECRET_KEY` means one rotation event breaks three unrelated features.

## Current state

All quotes verified against the working tree at `c770a1c` (2026-07-07).
Plans 037, 041, and 050 are written and TODO (`docs/plans/000_README.md`
rows 123, 127, 136); plan 030 (jobs harness) is DONE (row 111).

- **037 decision 3**: "Only OAuth tokens are stored in Postgres,
  Fernet-encrypted — the exact `UserAuth` precedent ... encrypt/decrypt
  property pairs over `utils/security.py::encrypt_data/decrypt_data`."
  `ENCRYPTION_KEY` is a `SecretStr` env setting validated as a Fernet
  key (`core/settings/security.py:19,85-94`) — settings-held, not
  provider-held.
- **037 decisions 4/5** build `services/secrets/` with a
  `GcpSecretManagerProvider` and a validator making the real secret
  manager mandatory outside local ("prod requires the real secret
  manager by construction") — but apply it only to api-key *references*,
  never to the token-encryption master key.
- **Rotation is decrypt-only today**: `utils/security.py:31-34` —
  `_encryption_keys = [_primary_fernet]` under the comment "For key
  rotation, we could have multiple keys (future enhancement)";
  `encrypt_data` uses `_primary_fernet` only, `decrypt_data` loops the
  list (lines 103-158). Nothing anywhere re-encrypts rows. 037's
  maintenance note confirms the posture: "rotating `ENCRYPTION_KEY`
  requires the multi-key decrypt path there, not anything
  integration-specific."
- **037 Step 5 keys fingerprints with the auth key**:
  `compute_principal_fingerprint(...)` → `create_hmac_signature(...,
  settings.SECRET_KEY.get_secret_value())`. The maintenance note admits
  the cost: "rotating `SECRET_KEY` orphans existing fingerprints ...
  Record any SECRET_KEY rotation as requiring a fingerprint backfill
  script." `SECRET_KEY` is "Secret key for session signing"
  (`core/settings/security.py:16`) and signs CSRF tokens
  (`utils/security.py:270,332`).
- **050 decision 3 reuses it again**: "HMAC-SHA256 over
  `artifact-view:{artifact_id}:{version_id}:{expires}` with
  `SECRET_KEY`" — anonymous capability URLs signed by the session/CSRF
  key, with no version identifier in the scheme.
- **041 Step 1 / decision 9**: "`GOOGLE_ADS_DEVELOPER_TOKEN: str | None
  = None` (secret value — document that production should supply it via
  the 037 secrets provider...)" — typed plain `str` despite the
  parenthetical, against the `SecretStr` precedent cited in decision 7.
- **041's tool-name table `google_ads_developer_token` never reaches
  audit details** by 041's own rules; the `SecretStr` change is
  defense in depth (masked repr/logs), not a behavior change.

## Scope

**In scope:**

- Amendment block appended to
  `docs/plans/037-integration-core-models-credentials.md` (Step 1 text)
- Amendment block appended to
  `docs/plans/041-first-integration-providers.md` (Step 2 text)
- Amendment block appended to
  `docs/plans/050-artifacts-model-serving.md` (Step 3 text)
- `docs/plans/000_README.md` row for 068

**Out of scope:**

- Any code — settings, HKDF helper, column, sweep job, and signature
  scheme all land inside 037/041/050 execution per their amendments.
- Migrating `UserAuth`/TOTP encryption off `ENCRYPTION_KEY` (decision 8).
- Full KMS envelope encryption (decision 1 — named end-state, recorded
  triggers).
- Session, CSRF, or login-OAuth key handling — unchanged.

## Git workflow

- Branch: `advisor/068-credential-encryption-hardening`
- Commit: `Docs - Credential Encryption Hardening Amendments`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Append the 037 amendment

Append the following block to
`docs/plans/037-integration-core-models-credentials.md`, directly after
the existing plan-061 amendment blockquote, verbatim:

> **Amendment (2026-07-07, plan 068 — credential encryption posture)**:
> this amendment wins over decision 3's key sourcing, the Step 5
> fingerprint recipe, and the key-rotation maintenance note where they
> diverge:
>
> 1. **Dedicated credential root key, sourced through the secrets
>    provider.** OAuth token columns are NOT encrypted with the app-wide
>    `ENCRYPTION_KEY`. Outside `ENVIRONMENT=local`, the root key
>    material resolves at first use through `services/secrets`
>    (reference name from a new setting
>    `CREDENTIAL_MASTER_KEY_SECRET_NAME`, default
>    `credential-master-key`, version `latest`); the new env setting
>    `CREDENTIAL_MASTER_KEYS` (comma-separated Fernet keys, newest
>    first — the secret value uses the same format) is a local-only
>    fallback, rejected outside local by the Step 1 validator (same law
>    as `SECRET_PROVIDER=local`). Resolution is an async cached
>    accessor — once per process, never at import time.
> 2. **HKDF purpose subkeys.** Add `derive_purpose_key(root: bytes,
>    purpose: str) -> bytes` (HKDF-SHA256; `cryptography` is already a
>    dep) to `utils/security.py`. Token columns encrypt/decrypt through
>    a `MultiFernet` over keys derived with purpose
>    `praxis:credential-tokens:v1` (one per root key, newest first;
>    Fernet key = urlsafe-b64 of the 32-byte HKDF output).
>    `compute_principal_fingerprint` keys its HMAC with the newest key
>    derived with purpose `praxis:principal-fingerprint:v1` — NOT
>    `SECRET_KEY`. The encrypt/decrypt property pairs on
>    `ExternalCredential` route through this seam instead of
>    `encrypt_data`/`decrypt_data`; `UserAuth`/TOTP stay on
>    `ENCRYPTION_KEY` unchanged.
> 3. **`encryption_key_id` column.** Table 1 gains `encryption_key_id`
>    String(16) nullable — the first 16 hex chars of SHA-256 over the
>    root key string that encrypted the row; null when both token
>    columns are null. `store_oauth_credential`, every refresh, and
>    `crypto_shred` keep it accurate. Rotation progress is thereby a
>    SQL query, not a guess.
> 4. **Re-encryption sweep job.** Register job kind
>    `integrations.rotate_credential_encryption` on the plan-030 jobs
>    harness (DONE) — an explicit exception to this plan's "no job
>    handlers" out-of-scope line. It walks live `external_credentials`
>    rows whose `encryption_key_id` differs from the newest root key
>    id, re-encrypts under the newest key with per-row
>    `SELECT ... FOR UPDATE` (the `ensure_fresh_credential` lock
>    discipline), and restamps the id. Enqueued manually (document the
>    command); no schedule. One summary audit event (`UPDATE` on
>    `INTEGRATION_CREDENTIAL`, count-only details). Fingerprints are
>    NOT recomputed — the plaintext principal id is not stored; on root
>    rotation, dedup detection degrades gracefully for pre-rotation
>    rows and heals at reconnect. Replace the maintenance note's
>    `SECRET_KEY`-orphaning sentence with this posture.
> 5. **Tests and done criteria grow**: after a sweep, every live row
>    decrypts with ONLY the newest key (old keys droppable — proven
>    with a two-key fixture); fingerprints are unchanged by a
>    `SECRET_KEY` change; the local-only `CREDENTIAL_MASTER_KEYS`
>    fallback is rejected outside local. Add done criteria: "sweep
>    leaves no live row with a stale `encryption_key_id`" and "grep
>    confirms no code under `services/integrations/` or
>    `services/secrets/` reads `settings.ENCRYPTION_KEY` or signs with
>    raw `SECRET_KEY`".
> 6. Full envelope encryption (per-credential DEKs wrapped by a KMS
>    KEK) is the recorded end-state with revisit triggers in plan 068 —
>    do not build it here.

### Step 2: Append the 041 amendment

Append to `docs/plans/041-first-integration-providers.md`, directly
after the existing plan-061 amendment blockquote, verbatim:

> **Amendment (2026-07-07, plan 068 — credential encryption posture)**:
> in Step 1 / decision 9, type the developer token as a secret —
> `GOOGLE_ADS_DEVELOPER_TOKEN: SecretStr | None = None` — matching the
> `ANTHROPIC_API_KEY: SecretStr | None` precedent
> (`core/settings/models.py:69`) and the OAuth client secrets
> (`core/settings/auth.py:29-46`). The Google Ads client reads it via
> `.get_secret_value()` when building the `developer-token` header; the
> value must never appear in logs, audit details, or exception context
> (`SecretStr` masks repr; the availability gate in decision 9 checks
> truthiness, which is unaffected).

### Step 3: Append the 050 amendment

Append to `docs/plans/050-artifacts-model-serving.md`, directly after
the drift-check blockquote, verbatim:

> **Amendment (2026-07-07, plan 068 — credential encryption posture)**:
> decision 3's view-URL signature changes in two ways:
>
> 1. **Purpose-derived key.** The HMAC key is
>    `derive_purpose_key(SECRET_KEY, "praxis:artifact-view-url:v1")`
>    (helper landed by 037's plan-068 amendment; if executing before
>    037, land the helper here — it is ~3 lines on `cryptography`),
>    never raw `SECRET_KEY`: the key that signs sessions and CSRF must
>    not also sign anonymous capability URLs. `SECRET_KEY` remains the
>    root deliberately — serving takes no request-time dependency on
>    the secrets provider, and with a 300 s TTL a root rotation merely
>    invalidates in-flight URLs.
> 2. **Versioned scheme.** The signed payload becomes
>    `artifact-view:v1:{artifact_id}:{version_id}:{expires}` and the
>    query parameter becomes `sig=v1.{hex}`; the route rejects unknown
>    version prefixes with the same uniform 404. Step 5's recipe, the
>    Step 7 tampering tests, and the 051 share-route reuse note inherit
>    this shape.

### Step 4: README row

Add the 068 row to the `docs/plans/000_README.md` status table (Lane B,
depends on "037/041/050 (binds before 037 executes)") and mark it DONE
when Steps 1–3 are committed.

## Done criteria

- [ ] `grep -c "plan 068" docs/plans/037-integration-core-models-credentials.md`
      ≥ 1, and the block matches Step 1 verbatim
- [ ] `grep -c "plan 068" docs/plans/041-first-integration-providers.md`
      ≥ 1, and the block matches Step 2 verbatim
- [ ] `grep -c "plan 068" docs/plans/050-artifacts-model-serving.md`
      ≥ 1, and the block matches Step 3 verbatim
- [ ] `git diff --stat -- apps/` is empty (no code changed)
- [ ] `docs/plans/000_README.md` row for 068 added and updated

## STOP conditions

Stop and report back (do not improvise) if:

- 037 has started executing (drift-check test above) — reconcile with
  landed credential code first; amending an executed plan is fiction.
- Any of the three target plans' quoted text in "Current state" no
  longer matches (another amendment may have claimed the same seams —
  check for a sibling encryption-posture amendment before adding a
  second).
- `utils/security.py` no longer has the `_encryption_keys` decrypt loop
  or the `SecretStr`-typed `SECRET_KEY`/`ENCRYPTION_KEY` settings — the
  premises of decisions 2–4 need re-verification.
- Plan 030's jobs harness row is no longer DONE — the sweep job has no
  home; re-plan its carrier before amending 037.

## Maintenance notes

- **037's executor** owns the settings names, the accessor module
  placement, and sweep batching details within the amendment's
  constraints; deviations get recorded back into the amendment block in
  the same PR (the 029/061 rule).
- **038** (OAuth connect flows) writes credentials through 037's
  service ops and inherits the new seam for free; it must not read
  `ENCRYPTION_KEY` for integration material.
- **The KMS end-state** (decision 1): when a revisit trigger fires, the
  `encryption_key_id` column and the sweep job are the migration
  vehicle — wrap per-row DEKs, sweep once, drop the master key. That is
  why both exist even in the middle path.
- Reviewers of 037's execution should scrutinize: the accessor never
  resolving through the local file store outside local, the sweep's
  FOR UPDATE discipline against a concurrent refresh, and that no test
  fixture hardcodes a production-shaped root key.
