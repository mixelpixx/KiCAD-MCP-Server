# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────
# kicad-mcp — self-contained image for KiCAD-MCP-Server
# Personal-use, amd64-only, Wayland-only.
# ─────────────────────────────────────────────────────────────
ARG UBUNTU_VERSION=24.04

# ─── base ─── shared KiCAD 10 + Node 22 + Python 3.12 + Java 21 runtime
FROM ubuntu:${UBUNTU_VERSION} AS base

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# System packages, KiCAD PPA, NodeSource
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        software-properties-common \
        tini \
    && add-apt-repository -y ppa:kicad/kicad-10.0-releases \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends \
        kicad \
        kicad-libraries \
        kicad-symbols \
        kicad-footprints \
        kicad-packages3d \
        nodejs \
        python3 \
        python3-pip \
        python3-venv \
        openjdk-21-jre-headless \
        dbus-x11 \
        libglib2.0-bin \
        libgl1 \
        libegl1 \
        libgles2 \
        mesa-utils \
        libgtk-3-0 \
        adwaita-icon-theme \
        fonts-dejavu-core \
        git \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (UID matches typical single-user Linux host).
# Ubuntu 24.04's base image ships a pre-existing `ubuntu` user at UID/GID
# 1000 — remove it first so we can claim that UID.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupdel ubuntu 2>/dev/null || true \
    && groupadd -g 1000 kicad \
    && useradd -m -u 1000 -g 1000 -s /bin/bash kicad \
    && install -d -o kicad -g kicad /tmp/kicad /app /home/kicad/.local /home/kicad/.local/bin

ENV HOME=/home/kicad \
    PATH=/home/kicad/.local/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONPATH=/usr/lib/kicad/lib/python3/dist-packages

# ─── deps ─── install repo dependencies (npm + pip) as user
FROM base AS deps
WORKDIR /app
USER kicad

# Copy only manifests to maximize cache hits on dep changes
COPY --chown=kicad:kicad package.json package-lock.json ./
COPY --chown=kicad:kicad requirements.txt ./

# --ignore-scripts avoids running package.json's `prepare` (npm run build → tsc)
# for two reasons: (a) this is the prod-only install (--omit=dev), so the
# `typescript` devDep isn't present, and (b) even in the `build` stage below,
# `npm ci` runs BEFORE tsconfig.json/src/ are copied, so `prepare` would have
# no project to compile. The compile happens via the explicit `RUN npm run build`
# in the `build` stage after sources are in place.
RUN --mount=type=cache,target=/home/kicad/.npm,uid=1000,gid=1000 \
    npm ci --omit=dev --ignore-scripts

RUN --mount=type=cache,target=/home/kicad/.cache/pip,uid=1000,gid=1000 \
    pip install --user --break-system-packages -r requirements.txt

# ─── build ─── compile TypeScript
FROM deps AS build

# Bring in dev deps for the TS compile.
# --ignore-scripts again: `prepare` (npm run build → tsc) would fire during
# `npm ci` here, but tsconfig.json and src/ are copied AFTER this step, so tsc
# would run with no project to compile. The explicit `npm run build` below
# performs the compile once the sources are in place.
RUN --mount=type=cache,target=/home/kicad/.npm,uid=1000,gid=1000 \
    npm ci --ignore-scripts

COPY --chown=kicad:kicad tsconfig.json ./
COPY --chown=kicad:kicad src/ ./src/

RUN npm run build

# ─── runtime ─── slim final image for MCP invocation
FROM base AS runtime
WORKDIR /app

# Copy prod node_modules from deps (NOT from build — build has dev deps too)
COPY --from=deps --chown=kicad:kicad /app/node_modules ./node_modules
# Copy Python user-site
COPY --from=deps --chown=kicad:kicad /home/kicad/.local /home/kicad/.local
# Copy compiled TS output
COPY --from=build --chown=kicad:kicad /app/dist ./dist
# Copy Python source + manifests needed at runtime
COPY --chown=kicad:kicad python/ ./python/
COPY --chown=kicad:kicad package.json ./
COPY --chown=kicad:kicad resources/ ./resources/
COPY --chown=kicad:kicad config/ ./config/

ENV KICAD_BACKEND=auto \
    LOG_LEVEL=info \
    NODE_ENV=production

USER kicad
ENTRYPOINT ["/usr/bin/tini", "--", "node", "/app/dist/index.js"]

# ─── dev ─── devcontainer target (adds dev tooling + passwordless sudo)
FROM base AS dev

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        ripgrep \
        fd-find \
        jq \
        less \
        vim-tiny \
        sudo \
        make \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'kicad ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/kicad \
    && chmod 0440 /etc/sudoers.d/kicad

USER kicad
WORKDIR /workspaces/KiCAD-MCP-Server
CMD ["sleep", "infinity"]
