# Reproducibility is the point (ADR-0002): the image installs from uv.lock,
# so the container holds the same pinned dependency set that was validated.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first so a source-only change does not re-resolve them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src/ ./src/
COPY data/reference/ ./data/reference/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Never run as root; the filesystem is read-only in the Helm chart.
RUN groupadd --gid 10001 drift \
    && useradd --uid 10001 --gid drift --create-home --shell /usr/sbin/nologin drift

WORKDIR /app
COPY --from=build --chown=drift:drift /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER drift
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "drift.api:app", "--host", "0.0.0.0", "--port", "8000"]
