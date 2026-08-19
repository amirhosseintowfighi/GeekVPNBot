# syntax=docker/dockerfile:1.7
# --------------------------------------------------------------------------
# One image definition, both front-ends. admin/ and miniapp/ are the same
# shape - Next.js 14, same toolchain, same scripts - so they differ only by
# build context and the port they listen on. A second near-identical
# Dockerfile would be two files to keep in step instead of one.
#
# Build context is the app directory itself, not the repository root:
#   docker build -f docker/frontend/Dockerfile ./admin
# --------------------------------------------------------------------------
ARG NODE_VERSION=20

FROM node:${NODE_VERSION}-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

# ---- dependencies ---------------------------------------------------------
FROM base AS deps
COPY package.json package-lock.json ./
# `npm ci`, so the image is built from the committed lockfile and two builds a
# month apart install the same tree. It also fails loudly if package.json and
# the lockfile have drifted, which `npm install` would quietly paper over.
RUN npm ci --no-audit --no-fund

# ---- build ----------------------------------------------------------------
FROM base AS build
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Public values are compiled into the bundle, so they are build arguments
# rather than runtime environment: setting them in compose would have no
# effect on an already-built page.
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_ADMIN_API_URL=""
ARG NEXT_PUBLIC_BOT_USERNAME=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_ADMIN_API_URL=${NEXT_PUBLIC_ADMIN_API_URL} \
    NEXT_PUBLIC_BOT_USERNAME=${NEXT_PUBLIC_BOT_USERNAME}
RUN npm run build

# ---- runtime --------------------------------------------------------------
FROM base AS runtime
ENV NODE_ENV=production
ARG PORT=3000
ENV PORT=${PORT} HOSTNAME=0.0.0.0
RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home app

# The standalone output already contains the traced subset of node_modules and
# a server.js. .next/static is not traced and has to come separately. Neither
# app has a public/ directory; add a COPY for it when one appears.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static

USER app
EXPOSE ${PORT}
# No shell: server.js reads PORT and HOSTNAME from the environment itself.
CMD ["node", "server.js"]
