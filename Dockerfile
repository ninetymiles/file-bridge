# syntax=docker/dockerfile:1

# Use official Python image as base
FROM python:3.14-slim

ARG UV_INDEX

# Copy uv binary from official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files for layer caching
COPY uv.lock pyproject.toml ./

# Install dependencies using uv sync (creates .venv, excludes dev dependencies)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Copy application code
COPY app/ ./app/
COPY lib/ ./lib/

EXPOSE 8000
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
