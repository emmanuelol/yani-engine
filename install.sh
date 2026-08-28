#!/usr/bin/env bash
# yani-engine Automated Global Installer 🐩

set -e

echo "🐩 Preparing the yani-engine global environment..."

PLUGIN_DIR="$HOME/.gemini/config/plugins/yani-engine"

# 1. Clean previous installation
if [ -d "$PLUGIN_DIR" ]; then
    echo "🧹 Removing previous global installation..."
    rm -rf "$PLUGIN_DIR"
fi

echo "📂 Creating global plugin directory at $PLUGIN_DIR..."
mkdir -p "$PLUGIN_DIR"

# 2. Copy source files (excluding unwanted directories)
echo "📦 Copying files to global plugin directory..."
rsync -av --exclude='.git' --exclude='.venv' --exclude='.yani' --exclude='.dumbledoer' --exclude='__pycache__' ./ "$PLUGIN_DIR/"

# 3. Create the Virtual Environment natively in the global directory using uv
echo "⚡ Creating virtual environment using uv..."
cd "$PLUGIN_DIR"
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed. Please install uv (e.g. 'curl -LsSf https://astral.sh/uv/install.sh | sh') and try again."
    exit 1
fi
uv venv .venv
source .venv/bin/activate

# 4. Install Dependencies
echo "📜 Installing dependencies using uv..."
uv pip install -r requirements.txt

# 5. Make sub-tools executable (e.g., RTK and run_yani.sh)
if [ -f "bin/rtk" ]; then
    echo "⚙️ Granting execution permissions to RTK..."
    chmod +x bin/rtk
fi
chmod +x run_yani.sh run_dumbledoer.sh

# 6. Initialize the Agent Workspace locally (for the repo we ran this from, optional)
cd - > /dev/null
if [ ! -d ".yani" ]; then
    echo "🏗️ Initializing local .yani workspace directories..."
    mkdir -p .yani/tmp
    mkdir -p .yani/checkpoints
    mkdir -p .yani/rollbacks
fi

echo ""
echo "🐳 Building Docker Base Image..."
docker build -t yani-base:latest .

echo ""
echo "✨ yani-engine global installation complete! 🐩"
echo "The plugin is now globally available to Antigravity."
