# apps/api/Dockerfile

# --- Builder: install locked uv deps with build tools, then discard tools ---
FROM python:3.12.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

WORKDIR /app

# Install only what's needed to build any native wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

# Install Python deps first to maximize layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# --- Runtime: minimal image + non-root user ---
FROM python:3.12.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create an unprivileged user first so we can copy with ownership
RUN useradd --create-home --uid 1001 appuser

# Copy only the virtualenv and app code with correct ownership
COPY --from=builder --chown=1001:1001 /opt/venv /opt/venv
COPY --chown=1001:1001 . .

USER 1001:1001

EXPOSE 8080

# --- Local Development ---
FROM runtime AS dev

ENV WATCHFILES_FORCE_POLLING=true

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --reload --reload-dir /app"]

# --- Production ---
FROM runtime AS production

# TCP-level liveness probe using only stdlib; upgrade to an HTTP /healthz
# check once a health endpoint exists (curl is not present in slim images).
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import socket, os; s=socket.create_connection(('localhost', int(os.getenv('PORT','8080'))), timeout=5); s.close()"

# Respect Cloud Run's PORT and bind to all interfaces.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
