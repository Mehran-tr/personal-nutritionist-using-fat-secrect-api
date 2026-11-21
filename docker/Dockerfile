# syntax=docker/dockerfile:1.7
# ---------- build: resolve and install dependencies into a venv ----------
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first: this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- runtime: slim image, non-root user ----------
FROM python:3.13-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    # Trust X-Forwarded-For only from the reverse proxy's network (compose default
    # bridge). Set to the proxy's address in other environments.
    FORWARDED_ALLOW_IPS="172.16.0.0/12"
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health/live'); sys.exit(0)"
# --no-server-header: don't advertise the server software (fingerprinting).
# One worker per container; scale with replicas (simple metrics, clean shutdowns).
# Keep-alive (75 s) outlives the proxy's idle upstream connections, so the proxy
# never reuses a socket the app just closed (avoids sporadic 502s).
CMD ["uvicorn", "nutritionist.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--no-server-header", "--proxy-headers", "--timeout-keep-alive", "75", \
     "--timeout-graceful-shutdown", "20"]
