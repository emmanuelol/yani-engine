# Use a stable Ubuntu LTS base
FROM ubuntu:24.04

# Prevent interactive prompts during apt-get installations
ENV DEBIAN_FRONTEND=noninteractive

# 1. Install core system dependencies, Python 3, and Git
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    build-essential \
    docker.io \
    docker-compose-v2 \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Node.js v20+ (Required for MCP npx servers)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Install 'uv' (The lightning-fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# 4. Install RTK (Rust Token Killer) directly from the official source
RUN curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

# Ensure both uv and rtk are available in the system PATH
ENV PATH="/root/.local/bin:/root/.cargo/bin:$PATH"

# 5. Set the default working directory to match the execution mount
WORKDIR /workspace

# Default entrypoint
CMD ["bash"]