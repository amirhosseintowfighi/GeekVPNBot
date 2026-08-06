# syntax=docker/dockerfile:1.7
# --------------------------------------------------------------------------
# One image, three targets. api / bot / worker all run from `runtime`;
# they differ only by the command in docker-compose.
# --------------------------------------------------------------------------
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN python -m venv "$VIRTUAL_ENV"

# ---- dependency layer (cached independently of source) --------------------
FROM base AS deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
# Hatchling needs the package dir to exist to resolve the project metadata.
RUN mkdir -p src/geekvpn && touch src/geekvpn/__init__.py
RUN pip install --upgrade pip && pip install "."

FROM deps AS deps-dev
RUN pip install ".[dev]"

# ---- production runtime ---------------------------------------------------
FROM base AS runtime
RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home app
COPY --from=deps ${VIRTUAL_ENV} ${VIRTUAL_ENV}
COPY --chown=app:app pyproject.toml alembic.ini README.md ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app src ./src
ENV PYTHONPATH=/app/src
USER app
EXPOSE 8000
CMD ["uvicorn", "geekvpn.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- development runtime (hot reload, dev tooling, source is bind-mounted) -
FROM base AS development
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
COPY --from=deps-dev ${VIRTUAL_ENV} ${VIRTUAL_ENV}
COPY pyproject.toml alembic.ini README.md ./
COPY migrations ./migrations
COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "geekvpn.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
