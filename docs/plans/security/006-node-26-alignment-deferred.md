# Plan 006: Defer Node 26 types until the runtime moves

## Status

- **Priority:** P3
- **Risk:** MEDIUM
- **Status:** DEFERRED
- **Depends on:** An explicit Node 26 runtime decision
- **Source:** Closed Dependabot PR #6

## Decision

Do not upgrade `@types/node` from 24.x to 26.x while CI and supported local
development use Node 24. Type definitions must describe the deployed runtime;
otherwise the compiler can permit APIs that fail in production.

This plan is intentionally not executable yet.

## Revisit trigger

Reopen this plan only when all of the following are true:

- Node 26 is selected as the supported runtime;
- the runtime's release/LTS posture is acceptable for production;
- CI, Docker images, local setup documentation, and deployment targets can move
  together;
- Vite, TypeScript, pnpm, and native/transitive tooling support Node 26.

## Future scope

When the trigger is met, update as one runtime-alignment slice:

- CI `node-version`;
- production and development container base images;
- local-development documentation and any version files;
- `@types/node`;
- package engine constraints if adopted;
- cache keys or build assumptions coupled to the Node major.

## STOP conditions

Stop and report if:

- only type definitions are being changed;
- any deployed environment remains on Node 24;
- the upgrade requires weakening tests or build checks;
- package-manager or framework support for Node 26 is incomplete.

## Future verification

```bash
cd apps/web
node --version
pnpm check
pnpm audit --prod
cd ../..
make check
docker compose build api worker web
```

Also run the normal local quickstart and exercise login, SSE conversation
streaming, file upload, and a production web build.

## Completion criteria

- Node runtime, types, CI, containers, and documentation all target 26.
- No Node 24 deployment remains.
- Local and remote full gates pass.
