# yani-base:latest — Zero Trust Sandbox for yani-engine
# Base image for all agent sub-workers. Includes:
#   - Python 3.12 runtime for yani-engine orchestrator
#   - git for worktree operations
#   - VHS + ffmpeg + ttyd for deterministic demo GIF rendering
#
# Build: docker build -t yani-base:latest .
# Used by: yani_engine/core/sandbox.py, install.sh

FROM python:3.12-slim AS base

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# --- System dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ffmpeg \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# --- ttyd (not in Debian repos — install from GitHub release) ---
ARG TTYD_VERSION=1.7.7
RUN curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
    -o /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd

# --- VHS (Charmbracelet) ---
# Install from official .deb release — no Go toolchain needed
ARG VHS_VERSION=0.8.0
RUN curl -fsSL "https://github.com/charmbracelet/vhs/releases/download/v${VHS_VERSION}/vhs_${VHS_VERSION}_amd64.deb" \
    -o /tmp/vhs.deb \
    && dpkg -i /tmp/vhs.deb \
    && rm -f /tmp/vhs.deb

# --- Chromium sandbox fix for containerized rendering ---
# VHS uses go-rod which discovers Chrome at well-known paths (/usr/bin/chromium).
# In a container, Chromium must run with --no-sandbox. We replace the binary
# in-place with a wrapper that injects the required flags.
RUN mv /usr/bin/chromium /usr/bin/chromium-real \
    && printf '#!/bin/bash\nexec /usr/bin/chromium-real --no-sandbox --disable-gpu --disable-dev-shm-usage "$@"\n' \
    > /usr/bin/chromium \
    && chmod +x /usr/bin/chromium

# --- Workspace ---
WORKDIR /workspace

# Default entrypoint for sandbox exec
CMD ["/bin/bash"]
