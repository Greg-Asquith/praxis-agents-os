# Praxis Agents OS web app

This React app is the user-facing side of Praxis Agents OS: conversations,
approvals, schedules, agents, integrations, files, knowledge, and audit views.
For the Docker quickstart and full-project setup, start with the
[repository README](../../README.md).

## Stack

- React 19
- TypeScript
- Vite
- Tailwind CSS 4
- shadcn/base-nova components
- TanStack Router
- TanStack Query

## Run the app locally

From the `apps/web` directory, install dependencies and start the development
server:

```bash
pnpm install
pnpm dev
```

The local development server runs at `http://localhost:3000`. The app reads
the API base URL from `VITE_API_BASE_URL`. It defaults to
`http://localhost:8000/api/v1`.

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

The API uses cookie sessions and CSRF protection. Keep requests credentialed and
set explicit `ALLOWED_CORS_ORIGINS` and `FRONTEND_URL` values in the API
environment.

## Run checks

Run an individual check when you need focused feedback:

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm format:check
pnpm deadcode
pnpm arch
pnpm build
```

Before opening a pull request, run the full local gate:

```bash
pnpm check
```
