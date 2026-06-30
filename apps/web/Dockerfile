# apps/web/Dockerfile

# --- Base: Node with pnpm via corepack ---
FROM node:24-slim AS base

ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:$PATH" \
    PORT=8080

RUN corepack enable

WORKDIR /app

# --- Deps: install locked deps first to maximize layer cache ---
FROM base AS deps

COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile

# --- Build: compile the static SPA bundle ---
FROM deps AS build

COPY . .
RUN pnpm build

# --- Local Development: Vite dev server with HMR ---
FROM deps AS dev

COPY . .
EXPOSE 8080
# Source is bind-mounted in compose; node_modules comes from the image via a named volume.
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "8080"]

# --- Production: non-root nginx serving the static bundle ---
FROM nginxinc/nginx-unprivileged:1.27-alpine AS production

ENV PORT=8080

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:8080/ >/dev/null 2>&1 || exit 1
