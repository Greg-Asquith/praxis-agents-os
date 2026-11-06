# apps/data-science/Dockerfile
# The driver comes from a named build context:
# docker build --build-context driver=apps/isolation-driver -f apps/data-science/Dockerfile apps/data-science

# --- Builder: locked CPU-only PyTorch, Timestral, and holidays in /opt/venv ---
FROM python:3.12.16-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/

# Timestral isn't on PyPI; uv.lock pins it to a Git commit.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# --- Weights: Timestral-123M at a pinned revision, checked by hash, with its licence ---
FROM python:3.12.16-slim-trixie AS weights

ARG TIMESTRAL_REPO=https://huggingface.co/mistralai/Timestral-123M/resolve/5a147287addda85f6acd8da3fb8858fe9af7e8f7
ARG TIMESTRAL_WEIGHTS_SHA256=599fafa73cadbbc800b5a346ca900fa741ee3e5fd22e3b4a4430e151e74f4bc2
ARG TIMESTRAL_CONFIG_SHA256=7bb4c042fb2d2ed6469b6758ba380dfeda3ab32df47690a87aec1527bdae79bf
ARG TIMESTRAL_LICENSE_SHA256=648194727930df730890e9f9affdbcc5c930d406d6829559b25ca3d5a973fc8c

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/models/timestral-123m
RUN curl -fsSL --retry 5 --retry-all-errors -o model.safetensors "${TIMESTRAL_REPO}/model.safetensors" \
    && curl -fsSL --retry 5 --retry-all-errors -o config.json "${TIMESTRAL_REPO}/config.json" \
    && curl -fsSL --retry 5 --retry-all-errors -o LICENSE "${TIMESTRAL_REPO}/LICENSE" \
    && printf '%s  %s\n' \
        "${TIMESTRAL_WEIGHTS_SHA256}" model.safetensors \
        "${TIMESTRAL_CONFIG_SHA256}" config.json \
        "${TIMESTRAL_LICENSE_SHA256}" LICENSE \
    | sha256sum -c -

# --- Runtime: driver, venv, and weights; non-root, read-only code, no application secrets ---
FROM python:3.12.16-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HUB_OFFLINE=1

RUN useradd --create-home --uid 1001 renderer

COPY --from=builder /opt/venv /opt/venv
COPY --from=weights /opt/models /opt/models
WORKDIR /app
COPY --from=driver driver ./driver
COPY datascience ./datascience

USER 1001:1001
EXPOSE 8080

# --- Tests: run on Linux in Docker (make datascience-check) ---
FROM builder AS test-builder

RUN uv sync --locked

FROM runtime AS test

COPY --from=test-builder /opt/venv /opt/venv
COPY --from=driver driver_testing ./driver_testing
COPY tests ./tests
ENV RENDERER_TEST_CONTAINER=1
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

# --- Production ---
FROM runtime AS production

CMD ["python", "-m", "datascience"]
