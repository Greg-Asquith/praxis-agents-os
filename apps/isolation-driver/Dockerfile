# apps/isolation-driver/Dockerfile
# Tests only; services copy the driver through a named build context.
# docker build --target test -f apps/isolation-driver/Dockerfile apps/isolation-driver

FROM python:3.12.16-slim-trixie AS test

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RENDERER_TEST_CONTAINER=1

RUN useradd --create-home --uid 1001 renderer \
    && pip install --no-cache-dir pytest==8.4.2
WORKDIR /app
COPY driver ./driver
COPY driver_testing ./driver_testing
COPY tests ./tests

USER 1001:1001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
