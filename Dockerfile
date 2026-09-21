# syntax=docker/dockerfile:1

# Use official Python image as base
FROM python:3.14-slim

ARG UV_INDEX

# Copy uv binary from official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files for layer caching
COPY uv.lock pyproject.toml ./

# Install dependencies using uv sync (creates .venv, excludes dev and train dependencies)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-group train

# Copy application code
COPY app/ ./app/
COPY lib/ ./lib/

EXPOSE 8000
ENV PATH=${PATH}:/app/.venv/bin

# Start command using the python/uvicorn binary inside the synchronized virtual environment.
# This bypasses 'uv run' and completely prevents any dynamic runtime package resolution or downloads.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
