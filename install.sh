#!/usr/bin/env bash
set -euo pipefail

echo "🧙♂️ Initializing DumbleDoer Plugin for agy..."

# 1. Verify Node.js 20+
NODE_MAJOR=$(node --version 2>/dev/null | sed 's/v\([0-9]*\).*/\1/')
if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 20 ]; then
    echo "✗ Node.js 20+ required." >&2
    exit 1
fi

# 2. Clean up legacy .git
if [ -d ".git" ] && [ ! -f "main.py" ]; then
    rm -rf .git
fi

# 3. Initialize CodeGraph index
echo "📦 Building semantic index..."
npx -y --package=@colbymchenry/codegraph codegraph init -i

# 4. Build isolated Python environment
echo "⚡ Setting up Python environment..."
uv venv && uv sync

echo "Setup complete!"
