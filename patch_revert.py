import os
import sys

def patch_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    old_block = """        async def _init_codegraph():
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

    new_block = """        # Connect to codegraph
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

    if old_block in content:
        content = content.replace(old_block, new_block)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Patched {filepath}")
    else:
        print(f"Warning: old_block not found in {filepath}")

patch_file("/home/emmanuel/Documentos/GitHub/DumbleDoer/dumbledoer/dumbledoer_cli.py")
patch_file(os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py"))
