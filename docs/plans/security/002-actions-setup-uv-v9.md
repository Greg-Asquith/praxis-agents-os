# Plan 002: Upgrade `astral-sh/setup-uv` to v9

## Status

- **Priority:** P1
- **Risk:** LOW–MEDIUM
- **Status:** TODO
- **Depends on:** Plan 001
- **Source:** Closed Dependabot PR #1

## Intent

Upgrade both CI uses of `astral-sh/setup-uv` from 8.2.0 to 9.0.0 without
silently changing cache-retention behaviour.

## Fixed decisions

- Pin v9.0.0 to full commit
  `c771a70e6277c0a99b617c7a806ffedaca235ff9`.
- Preserve the v8 behaviour explicitly with `prune-cache: true`. Version 9
  changed its default to `false`; relying on the new default would increase
  retained cache size.
- Retain `python-version: "3.12"` and `enable-cache: true`.
- Change both the API and Docker-build jobs together.

## Scope

- `.github/workflows/ci.yml`
- No Python dependency or lockfile changes.

## STOP conditions

Stop and report if:

- plan 001 is not green remotely;
- `prune-cache` is no longer a valid v9 input;
- restoring pruning causes cache corruption or removes data needed by a later
  job;
- v9 requires a Python or uv version change.

## Steps

1. Replace both setup-uv v8 SHA references with the fixed v9 SHA.
2. Add `prune-cache: true` to both existing `with` blocks.
3. Confirm that workflow permissions and all other inputs are unchanged.
4. Run YAML/static checks available in the repository and the full local gate.
5. After an approved push, inspect both setup-uv post-job cleanup logs and
   confirm the API and Docker jobs pass.

## Verification

```bash
make check
git diff --check
```

Remote verification after an approved push:

```bash
gh pr checks <pr-number> --watch
```

## Completion criteria

- Both jobs use the pinned v9.0.0 SHA.
- Cache pruning is explicit and remains enabled.
- The full local gate passes.
- Remote API, Docker, audit, and CodeQL checks pass.
