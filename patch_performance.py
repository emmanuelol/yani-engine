import os
import sys

def patch_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    # 1. Fix Deprecation Warning
    content = content.replace(
        "import asyncio\n                        if asyncio.iscoroutinefunction(tool_func):",
        "import inspect\n                        if inspect.iscoroutinefunction(tool_func):"
    )
    
    # 2. Parallel MCP Initialization
    # Find the connect_mcp method
    mcp_old = """    async def connect_mcp(self):
        if not os.path.exists(".codegraph"):
            os.makedirs(".codegraph", exist_ok=True)
            print("Initializing CodeGraph index...", file=sys.stderr)
            import subprocess
            await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=True)
            
        # Connect to codegraph
        try:
            codegraph_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"]
            )
            codegraph_transport, codegraph_stream = await self.exit_stack.enter_async_context(stdio_client(codegraph_params))
            codegraph_session = await self.exit_stack.enter_async_context(ClientSession(codegraph_transport, codegraph_stream))
            await codegraph_session.initialize()
            cg_tools = await codegraph_session.list_tools()
            
            # Enterprise-grade safeguard: limit tools per server
            tools_to_add = cg_tools.tools
            if len(tools_to_add) > 50:
                print(f"Warning: codegraph MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                tools_to_add = tools_to_add[:50]
                
            for tool in tools_to_add:
                self.gemini_tools.append(self._create_mcp_wrapper("codegraph", tool))
            self.mcp_sessions["codegraph"] = codegraph_session
        except Exception as e:
            import sys
            print(f"CodeGraph MCP degraded: {e}", file=sys.stderr)

        # Connect to context7
        try:
            context7_params = StdioServerParameters(
                command="npx",
                args=["--yes", "--quiet", "@upstash/context7-mcp"]
            )
            context7_transport, context7_stream = await self.exit_stack.enter_async_context(stdio_client(context7_params))
            context7_session = await self.exit_stack.enter_async_context(ClientSession(context7_transport, context7_stream))
            await context7_session.initialize()
            c7_tools = await context7_session.list_tools()
            
            # Enterprise-grade safeguard: limit tools per server
            tools_to_add = c7_tools.tools
            if len(tools_to_add) > 50:
                print(f"Warning: context7 MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                tools_to_add = tools_to_add[:50]
                
            for tool in tools_to_add:
                self.gemini_tools.append(self._create_mcp_wrapper("context7", tool))
            self.mcp_sessions["context7"] = context7_session
        except Exception as e:
            import sys
            print(f"Context7 MCP degraded: {e}", file=sys.stderr)"""

    mcp_new = """    async def connect_mcp(self):
        if not os.path.exists(".codegraph"):
            os.makedirs(".codegraph", exist_ok=True)
            print("Initializing CodeGraph index...", file=sys.stderr)
            import subprocess
            await asyncio.to_thread(subprocess.run, ["npx", "--yes", "--package=@colbymchenry/codegraph", "codegraph", "init"], check=True)
            
        async def _init_codegraph():
            try:
                codegraph_params = StdioServerParameters(
                    command="npx",
                    args=["--yes", "--quiet", "--package=@colbymchenry/codegraph", "codegraph", "serve", "--mcp"]
                )
                codegraph_transport, codegraph_stream = await self.exit_stack.enter_async_context(stdio_client(codegraph_params))
                codegraph_session = await self.exit_stack.enter_async_context(ClientSession(codegraph_transport, codegraph_stream))
                await codegraph_session.initialize()
                cg_tools = await codegraph_session.list_tools()
                
                tools_to_add = cg_tools.tools
                if len(tools_to_add) > 50:
                    print(f"Warning: codegraph MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                    tools_to_add = tools_to_add[:50]
                    
                for tool in tools_to_add:
                    self.gemini_tools.append(self._create_mcp_wrapper("codegraph", tool))
                self.mcp_sessions["codegraph"] = codegraph_session
            except Exception as e:
                import sys
                print(f"CodeGraph MCP degraded: {e}", file=sys.stderr)

        async def _init_context7():
            try:
                context7_params = StdioServerParameters(
                    command="npx",
                    args=["--yes", "--quiet", "@upstash/context7-mcp"]
                )
                context7_transport, context7_stream = await self.exit_stack.enter_async_context(stdio_client(context7_params))
                context7_session = await self.exit_stack.enter_async_context(ClientSession(context7_transport, context7_stream))
                await context7_session.initialize()
                c7_tools = await context7_session.list_tools()
                
                tools_to_add = c7_tools.tools
                if len(tools_to_add) > 50:
                    print(f"Warning: context7 MCP provided {len(tools_to_add)} tools. Truncating to 50 to prevent context bloat.", file=sys.stderr)
                    tools_to_add = tools_to_add[:50]
                    
                for tool in tools_to_add:
                    self.gemini_tools.append(self._create_mcp_wrapper("context7", tool))
                self.mcp_sessions["context7"] = context7_session
            except Exception as e:
                import sys
                print(f"Context7 MCP degraded: {e}", file=sys.stderr)

        await asyncio.gather(_init_codegraph(), _init_context7())"""

    if mcp_old in content:
        content = content.replace(mcp_old, mcp_new)
    else:
        print("Warning: Could not find connect_mcp method to replace in", filepath)

    # 3. Selective MCP Initialization
    run_old = """    async def run(self, command: str, args: list, model: str = "gemini-3.6-flash"):
        self.model = model
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            OrphanRecoveryScanner().run()
            # we can fall through to normal execution if it resumes agent logic, or just run the scanner
        await self.connect_mcp()"""

    run_new = """    async def run(self, command: str, args: list, model: str = "gemini-3.6-flash"):
        self.model = model
        print(f"DumbleDoer running command: {command}")
        if command == "resume":
            OrphanRecoveryScanner().run()
            # we can fall through to normal execution if it resumes agent logic, or just run the scanner
        
        # Skip MCP initialization for commands that do not need structural code analysis or semantic search
        if command not in ("status", "rollback"):
            await self.connect_mcp()"""

    if run_old in content:
        content = content.replace(run_old, run_new)
    else:
        print("Warning: Could not find run method to replace in", filepath)

    with open(filepath, "w") as f:
        f.write(content)

repo_path = "/home/emmanuel/Documentos/GitHub/DumbleDoer/dumbledoer/dumbledoer_cli.py"
install_path = os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py")

patch_file(repo_path)
patch_file(install_path)
print("Patched both locations successfully")
