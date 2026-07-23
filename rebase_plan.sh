echo "🌱 Initiating Step 0: Establishing Baseline..."

# 1. Initialize git if it hasn't been already
git init

# 2. Stage all cleaned files
git add .

# 3. Commit the baseline
git commit -m "chore: baseline commit prior to DumbleDoer stability remediation"

# 4. Spin up a fresh, isolated virtual environment using uv (as dictated by the project)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv
source .venv/bin/activate

echo "✅ Step 0 Complete: Baseline committed and virtual environment active."
