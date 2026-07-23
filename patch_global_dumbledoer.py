import os

# Target the active plugin file in your agy installation
plugin_path = os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")

with open(plugin_path, "r") as f:
    content = f.read()

# Swap the silent failure (check=False) for a strict guard (check=True)
target = 'await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=False)'
replacement = 'await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=True)'

if target in content:
    content = content.replace(target, replacement)
    with open(plugin_path, "w") as f:
        f.write(content)
    print("✅ Plugin successfully patched globally! DumbleDoer will now strictly validate CodeGraph initialization in all repositories.")
else:
    print("⚠️ Target string not found. The plugin might already be patched or the file structure changed.")
