import os
import sys

filepath = "dumbledoer/dumbledoer_cli.py"
with open(filepath, "r") as f:
    content = f.read()

# 1. Fix the Pydantic Schema Annotations Bug
old_wrapper_start = '''        safe_name = tool.name.replace("-", "_").replace("/", "_")
        mcp_wrapper.__name__ = safe_name if safe_name.startswith(server_name) else f"{server_name}_{safe_name}"'''

new_wrapper_start = '''        safe_name = tool.name.replace("-", "_").replace("/", "_")
        final_name = safe_name if safe_name.startswith(server_name) else f"{server_name}_{safe_name}"
        mcp_wrapper.__name__ = final_name
        mcp_wrapper.__qualname__ = final_name'''

content = content.replace(old_wrapper_start, new_wrapper_start)

old_injection = '''        # --- DYNAMIC SIGNATURE INJECTION ---
        params = []
        if hasattr(tool, 'inputSchema') and tool.inputSchema and "properties" in tool.inputSchema:'''

new_injection = '''        # --- DYNAMIC SIGNATURE INJECTION ---
        params = []
        annotations = {}
        if hasattr(tool, 'inputSchema') and tool.inputSchema and "properties" in tool.inputSchema:'''

content = content.replace(old_injection, new_injection)

old_param_append = '''                params.append(inspect.Parameter(
                    name=prop_name, 
                    kind=inspect.Parameter.KEYWORD_ONLY, 
                    annotation=ptype, 
                    default=default
                ))
        
        mcp_wrapper.__signature__ = inspect.Signature(parameters=params)
        mcp_wrapper.__doc__ = getattr(tool, 'description', '')'''

new_param_append = '''                annotations[prop_name] = ptype
                params.append(inspect.Parameter(
                    name=prop_name, 
                    kind=inspect.Parameter.KEYWORD_ONLY, 
                    annotation=ptype, 
                    default=default
                ))
        
        mcp_wrapper.__signature__ = inspect.Signature(parameters=params)
        mcp_wrapper.__annotations__ = annotations
        mcp_wrapper.__doc__ = getattr(tool, 'description', '')'''

content = content.replace(old_param_append, new_param_append)

# 2. Fix the missing .codegraph/ index causing 0 tools to load
old_connect = '''    async def connect_mcp(self):
        # Connect to codegraph'''

new_connect = '''    async def connect_mcp(self):
        if not os.path.exists(".codegraph"):
            print("Initializing CodeGraph index...", file=sys.stderr)
            import subprocess
            await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=False)
            
        # Connect to codegraph'''

content = content.replace(old_connect, new_connect)

with open(filepath, "w") as f:
    f.write(content)
print("Rabbit hole plugged successfully.")
