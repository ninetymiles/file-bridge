# syntax=docker/dockerfile:1
FROM python:3.14-slim
ARG UV_INDEX

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN uv sync --no-dev --no-cache

# pymediainfo runtime dependency (shared library only, far lighter than ffmpeg).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*

COPY app/ ./app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]