FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DAGSTER_HOME=/app/.dagster_home

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY api api
COPY pipelines pipelines
RUN uv sync --no-dev --frozen

RUN useradd --create-home --uid 1000 app \
    && mkdir -p "$DAGSTER_HOME" \
    && chown -R app /app
USER app

EXPOSE 3000
CMD ["uv", "run", "--no-sync", "dagster", "dev", \
     "--host", "0.0.0.0", "--port", "3000", \
     "-m", "pipelines.definitions"]
