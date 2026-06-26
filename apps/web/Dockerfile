# apps/web/Dockerfile

# --- Base Image ---
FROM node:22-alpine AS base

ENV NEXT_TELEMETRY_DISABLED=1

# --- Dependencies ---
FROM base AS deps

WORKDIR /app

RUN apk add --no-cache libc6-compat

COPY package.json package-lock.json ./

RUN npm ci

RUN find . -name "._*" -type f -delete

# --- Local Development ---
FROM deps AS dev

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0 \
    WATCHPACK_POLLING=true \
    CHOKIDAR_USEPOLLING=true

EXPOSE 8080

CMD ["pnpm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "8080"]

# --- Builder ---
FROM base AS builder

WORKDIR /app

ARG NEXT_PUBLIC_SITE_NAME=""
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_URL=""
ARG NEXT_PUBLIC_ASSETS_HOST=""

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN find . -name "._*" -type f -delete

ENV NEXT_PUBLIC_SITE_NAME="$NEXT_PUBLIC_SITE_NAME" \
    NEXT_PUBLIC_API_BASE_URL="$NEXT_PUBLIC_API_BASE_URL" \
    NEXT_PUBLIC_URL="$NEXT_PUBLIC_URL" \
    NEXT_PUBLIC_ASSETS_HOST="$NEXT_PUBLIC_ASSETS_HOST"

# Fail fast if required build args are missing — prevents silent builds with wrong config
RUN if [ -z "$NEXT_PUBLIC_API_BASE_URL" ] || [ -z "$NEXT_PUBLIC_URL" ]; then \
      echo "ERROR: Required build args missing. Pass --build-arg NEXT_PUBLIC_API_BASE_URL=... and --build-arg NEXT_PUBLIC_URL=..." >&2; \
      exit 1; \
    fi

RUN pnpm run build

RUN rm -rf .next/cache

# --- Runner ---
FROM base AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

RUN mkdir .next
RUN chown nextjs:nodejs .next

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

EXPOSE 8080

USER nextjs

CMD ["node", "server.js"]