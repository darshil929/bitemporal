FROM python:3.12-slim AS engine-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /src
COPY engine engine
# The wheel build compiles the library and the nanobind module only, so it needs no vcpkg.
RUN uv build --wheel engine --out-dir /wheels

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY api api
COPY pipelines pipelines
RUN uv sync --no-dev --frozen

COPY --from=engine-build /wheels /wheels
RUN uv pip install /wheels/*.whl

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
