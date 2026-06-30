# Praxis Agents OS Web

Vite SPA for the Praxis Agents OS control plane.

## Stack

- React 19
- TypeScript
- Vite
- Tailwind CSS 4
- shadcn/base-nova components
- TanStack Router
- TanStack Query

## Development

```bash
pnpm install
pnpm dev
```

The local dev server runs at `http://localhost:3000`. The API base URL is read
from `VITE_API_BASE_URL` and defaults to `http://localhost:8000/api/v1`.

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

The API uses cookie sessions and CSRF protection. Keep requests credentialed and
keep `ALLOWED_CORS_ORIGINS` / `FRONTEND_URL` explicit in the API environment.

## Checks

```bash
pnpm typecheck
pnpm lint
pnpm format:check
pnpm deadcode
pnpm arch
pnpm build
```

Run the full local gate with:

```bash
pnpm check
```
