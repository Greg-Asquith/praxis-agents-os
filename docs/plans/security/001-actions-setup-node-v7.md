# Plan 001: Upgrade `actions/setup-node` to v7

## Status

- **Priority:** P1
- **Risk:** LOW
- **Status:** TODO
- **Depends on:** Green CI on current `main`
- **Source:** Closed Dependabot PR #2

## Intent

Upgrade the two CI uses of `actions/setup-node` from 6.4.0 to 7.0.0 while
keeping the runtime on Node 24. This is first because the v7 branch passed the
web, audit, Docker, and CodeQL jobs and did not reproduce the pnpm cache-path
cleanup failure seen on several other dependency branches.

## Fixed decisions

- Keep `node-version: 24`; this is an action implementation upgrade, not a
  runtime upgrade.
- Change both the web and audit jobs together.
- Keep pnpm at the `packageManager` version declared in
  `apps/web/package.json`.

## Scope

- `.github/workflows/ci.yml`
- No application code or lockfile changes.

## STOP conditions

Stop and report if:

- current `main` is not green before this change;
- v7 requires changing Node 24, pnpm, cache paths, or workflow permissions;
- the action cannot remain pinned to a full SHA;
- the web production audit reports a real package vulnerability rather than an
  action cache-cleanup error.

## Steps

1. Confirm the baseline CI run on `main` is green.
2. Replace both v6.4.0 SHA references with the fixed v7.0.0 SHA.
3. Review the workflow diff and confirm no permissions, triggers, runtime
   versions, or cache inputs changed.
4. Run the local web gate and production audit.
5. After explicit approval to commit and push, confirm all remote CI jobs pass,
   especially `web` and `audit`.

## Verification

```bash
cd apps/web
pnpm check
pnpm audit --prod
```

Remote verification after an approved push:

```bash
gh pr checks <pr-number> --watch
```

## Completion criteria

- Both workflow references use the pinned v7.0.0 SHA.
- Node remains at 24.
- Local web checks and production audit pass.
- The pushed CI `audit` job completes without a cache path validation error.
