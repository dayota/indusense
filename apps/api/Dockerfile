FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.15-slim AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/workspace/.venv/bin:$PATH" \
    INDUSENSE_PROJECT_ROOT=/workspace
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY packages/ingestion packages/ingestion
COPY apps/api apps/api
COPY config config

FROM base AS development
RUN uv sync --locked --package indusense-api --no-dev
EXPOSE 8000
CMD ["uvicorn", "indusense_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "apps/api/src", "--reload-dir", "packages/ingestion/src"]

FROM base AS production
RUN uv sync --locked --package indusense-api --no-dev --no-editable
EXPOSE 8000
CMD ["uvicorn", "indusense_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
