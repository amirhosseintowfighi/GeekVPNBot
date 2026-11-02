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
COPY pyproject.toml ./
# Hatchling needs the package dir to exist to resolve the project metadata.
RUN mkdir -p src/geekvpn && touch src/geekvpn/__init__.py
# The production server builds from inside Iran, where the route to PyPI runs
# at tens of KB/s and stalls mid-download. A single `pip install` there loses
# every wheel it had fetched the moment one read times out, so the build is
# made to finish on such a link rather than hope for a good one:
#
#  * the downloads live in a BuildKit cache mount, which outlives the layer, a
#    failed attempt and a failed deploy - every attempt resumes where the last
#    one stopped instead of starting over;
#  * the install is retried up to six times inside the build;
#  * `sharing=locked`: the API and the bot are built from this file in
#    parallel, and the second waits for the first and installs from its cache
#    rather than racing it for the same slow link;
#  * a long read timeout, pip's own retries, a mirror when one is configured
#    (PIP_INDEX_URL in .env), and no pip self-upgrade - the runtime image
#    deletes pip anyway.
#
# The cache is the build host's, never the image's: the venv is what is copied
# on, so the image is the same size as before.
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    for attempt in 1 2 3 4 5 6; do \
      env -u PIP_NO_CACHE_DIR pip install --cache-dir /root/.cache/pip "." && exit 0; \
      echo "pip install: attempt $attempt failed; resuming from the download cache" >&2; \
      sleep 10; \
    done; \
    exit 1

FROM deps AS deps-dev
RUN pip install ".[dev]"

# ---- production runtime ---------------------------------------------------
FROM base AS runtime
RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home app
COPY --from=deps ${VIRTUAL_ENV} ${VIRTUAL_ENV}
# Nothing installs packages at runtime, and pip is the image's only source of
# HIGH findings: its bundled SBOM lists the msgpack, urllib3 and setuptools it
# vendors, none of which the application imports. Remove it rather than chase
# pip's vendoring schedule.
RUN rm -rf "${VIRTUAL_ENV}"/bin/pip* "${VIRTUAL_ENV}"/lib/python*/site-packages/pip \
    "${VIRTUAL_ENV}"/lib/python*/site-packages/pip-*.dist-info
COPY --chown=app:app pyproject.toml alembic.ini ./
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
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "geekvpn.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
