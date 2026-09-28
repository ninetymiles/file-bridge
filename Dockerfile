# syntax=docker/dockerfile:1
FROM python:3.14-slim
ARG UV_INDEX

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN uv sync --no-dev --no-cache

COPY app/ ./app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]