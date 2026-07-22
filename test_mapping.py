import inspect
from dumbledoer.dumbledoer_cli import DumbleDoerCLI

class MockTool:
    def __init__(self):
        self.name = "codegraph/impact"
        self.description = "Test"
        self.inputSchema = {
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }

cli = DumbleDoerCLI.__new__(DumbleDoerCLI)
cli.mcp_sessions = {}
wrapper = cli._create_mcp_wrapper("codegraph", MockTool())
print("Name:", wrapper.__name__)
print("Signature:", inspect.signature(wrapper))
