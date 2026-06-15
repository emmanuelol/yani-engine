#!/bin/bash
set -e

echo "Checking Node.js version..."
NODE_VERSION=$(node -v | cut -d 'v' -f 2)
NODE_MAJOR=$(echo $NODE_VERSION | cut -d '.' -f 1)

if [ -z "$NODE_MAJOR" ] || [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Error: Node.js version 20+ is required. Found: $NODE_VERSION"
  exit 1
fi
echo "Node.js version check passed (v$NODE_VERSION)."

echo "Removing legacy .git directories to prevent accidental commits..."
# Prevents removing the root .git directory
find . -mindepth 2 -type d -name ".git" -exec rm -rf {} +

echo "Initializing CodeGraph index..."
npx codegraph init -i

echo "Installing Python dependencies using uv..."
if ! command -v uv &> /dev/null; then
    echo "uv could not be found. Please install uv first."
    exit 1
fi

uv venv
source .venv/bin/activate
uv pip install -e .

echo "Installation complete."
