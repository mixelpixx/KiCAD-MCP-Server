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
