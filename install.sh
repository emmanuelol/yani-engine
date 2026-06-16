#!/usr/bin/env bash
# DumbleDoer Automated Installer 🧙♂️

set -e

echo "🪄 Preparing the DumbleDoer environment..."

# 1. Check for Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed."
    exit 1
fi

# 2. Create the Virtual Environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# 3. Activate the Virtual Environment
source .venv/bin/activate

# 4. Install Dependencies
echo "📜 Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. Make sub-tools executable (e.g., RTK)
if [ -f "bin/rtk" ]; then
    echo "⚙️ Granting execution permissions to RTK..."
    chmod +x bin/rtk
fi

# 6. Initialize the Agent Workspace
if [ ! -d ".dumbledoer" ]; then
    echo "🏗️ Initializing .dumbledoer workspace directories..."
    mkdir -p .dumbledoer/tmp
    mkdir -p .dumbledoer/checkpoints
    mkdir -p .dumbledoer/rollbacks
fi

echo ""
echo "✨ DumbleDoer installation complete! ✨"
echo "To activate your spellbook, run:"
echo "  source .venv/bin/activate"
