# Plan 004: Refresh web minor and patch dependencies

## Status

- **Priority:** P2
- **Risk:** MEDIUM
- **Status:** TODO
- **Depends on:** Plan 003
- **Source:** Closed Dependabot PR #5

## Intent

Apply the web dependency refresh locally in attributable units instead of
accepting one 23-package lockfile change. Production pairs that must remain in
lockstep are updated together; tooling packages are updated individually.

## Target versions

Production/runtime:

- `@fontsource-variable/inter` 5.2.8 → 5.3.0
- `@tanstack/react-query` 5.101.2 → 5.101.4
- `@tanstack/react-router` 1.170.16 → 1.170.18
- `lucide-react` 1.22.0 → 1.27.0
- `marked` 18.0.5 → 18.0.7
- `react` and `react-dom` 19.2.7 → 19.2.8
- `recharts` 3.10.0 → 3.10.1
- `tailwindcss` 4.3.2 → 4.3.3

Development/tooling:

- `@tanstack/eslint-plugin-query` 5.101.2 → 5.101.4
- `@tailwindcss/vite` 4.3.2 → 4.3.3
- `@vitejs/plugin-react` 6.0.2 → 6.0.4
- `dependency-cruiser` 18.0.0 → 18.1.0
- `eslint` 10.5.0 → 10.8.0
- `eslint-plugin-react-dom` and `eslint-plugin-react-x` 5.10.0 → 5.18.0
- `globals` 17.6.0 → 17.8.0
- `knip` 6.23.0 → 6.29.0
- `prettier` 3.9.4 → 3.9.6
- `prettier-plugin-tailwindcss` 0.8.0 → 0.8.1
- `shadcn` 4.12.0 → 4.16.0
- `typescript-eslint` 8.61.0 → 8.65.0
- `vite` 8.1.0 → 8.1.5

If live `main` has already moved beyond a listed starting version, use the
smallest current minor/patch target and record the drift in the execution
notes.

## Update units

Apply and verify in this order:

1. React + React DOM.
2. TanStack Query + its ESLint plugin.
3. TanStack Router.
4. Tailwind CSS + its Vite plugin.
5. Remaining production packages, one at a time.
6. Vite + React plugin.
7. ESLint + TypeScript ESLint + React lint plugins.
8. Remaining development tools, one at a time.

Run `pnpm typecheck`, `pnpm lint`, and the relevant focused test after every
unit. Run the full web gate after units 4, 5, 7, and 8.

## STOP conditions

Stop and report if:

- an update requires application refactoring or configuration migration;
- the lockfile changes a package outside the active unit unexpectedly;
- lint rules are disabled to make the update pass;
- dependency-cruiser boundaries are weakened;
- screenshots reveal typography, spacing, icon, chart, markdown, or navigation
  regressions;
- `pnpm audit --prod` reports a production vulnerability.

## Scope

- `apps/web/package.json`
- `apps/web/pnpm-lock.yaml`
- Narrow compatibility fixes and tests only when required by an active update.

## Verification

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm check
pnpm audit --prod
```

Manual smoke:

- login and app shell typography;
- conversation markdown and tool rows;
- routing between Home, Conversations, Agents, Files, and Integrations;
- one chart-bearing artifact or dashboard;
- production build served through the normal preview path.

## Completion criteria

- Every target is updated or explicitly recorded as rejected.
- Each update unit has an attributable passing check.
- Full web checks, production audit, smoke test, and remote CI pass.
