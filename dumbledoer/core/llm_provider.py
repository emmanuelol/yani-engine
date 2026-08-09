from abc import ABC, abstractmethod
from typing import Any, List, Dict
import httpx
import json
from google import genai
from google.genai.types import Part
import inspect

def _convert_tool_to_openai_schema(tool_func) -> dict:
    """Converts a DumbleDoer Python/MCP tool signature into an OpenAI-compatible function schema."""
    name = getattr(tool_func, "__name__", "unknown_tool")
    description = getattr(tool_func, "__doc__", "") or ""
    
    try:
        sig = inspect.signature(tool_func)
    except (TypeError, ValueError):
        sig = inspect.Signature()

    properties = {}
    required = []
    
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
            
        # Map Python types to JSON schema types
        param_type = "string"
        annotation = param.annotation
        if annotation is int:
            param_type = "integer"
        elif annotation is bool:
            param_type = "boolean"
        elif annotation is float:
            param_type = "number"
        elif annotation is list:
            param_type = "array"
            
        properties[param_name] = {
            "type": param_type,
            "description": f"Parameter {param_name} for {name}"
        }
        
        if param.default == inspect.Parameter.empty:
            required.append(param_name)
            
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description.strip()[:1024],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }

class AbstractLLMProvider(ABC):    
    @abstractmethod
    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        pass    
    
    @abstractmethod
    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        pass    
    
    @abstractmethod
    def parse_tool_calls(self, response: Any) -> List[Dict]:
        pass
            
    @abstractmethod
    def format_tool_response(self, tool_name: str, result: str) -> Any:
        pass

    @abstractmethod
    def prune_history(self, session: Any, max_turns: int) -> Any:
        """Prunes the session history to prevent context window bloat. Returns the updated session."""
        pass
        
class GeminiProvider(AbstractLLMProvider):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        
    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        session = self.client.aio.chats.create(
            model=model_name,
            config={
                "tools": tools,
                "automatic_function_calling": {"disable": True}
            }
        )
        # Store these so we can recreate the session during pruning
        session._dumbledoer_model = model_name
        session._dumbledoer_tools = tools
        return session
        
    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        return await session.send_message(payload)
        
    def parse_tool_calls(self, response: Any) -> List[Dict]:
        calls = []
        if response.function_calls:
            for call in response.function_calls:
                calls.append({
                    "name": call.name,
                    "args": dict(call.args) if call.args else {}
                })
        return calls
        
    def format_tool_response(self, tool_name: str, result: str) -> Any:
        return Part.from_function_response(
            name=tool_name,
            response={"result": result}
        )
    
    def format_tool_error(self, tool_name: str, error: str) -> Any:
        return Part.from_function_response(
            name=tool_name,
            response={"error": error}
        )

    def prune_history(self, session: Any, max_turns: int) -> Any:
        history = getattr(session, '_history', None)
        if history is not None and len(history) > max_turns:
            # Ensure we slice at an even boundary so User/Model turn parity isn't broken
            found_safe_boundary = False
            slice_index = -(max_turns - 1)
            while abs(slice_index) < len(history):
                item = history[slice_index]
                item_role = getattr(item, 'role', None) or (item.get('role') if isinstance(item, dict) else None)
                if item_role == 'model':
                    found_safe_boundary = True
                    break
                slice_index -= 1

            if found_safe_boundary:
                new_history = [history[0]] + history[slice_index:]
                # Recreate session cleanly instead of mutating private SDK state
                new_session = self.client.aio.chats.create(
                    model=getattr(session, '_dumbledoer_model', 'gemini-3.6-flash'),
                    config={"tools": getattr(session, '_dumbledoer_tools', []), "automatic_function_calling": {"disable": True}},
                    history=new_history
                )
                new_session._dumbledoer_model = getattr(session, '_dumbledoer_model', 'gemini-3.6-flash')
                new_session._dumbledoer_tools = getattr(session, '_dumbledoer_tools', [])
                return new_session
        return session

class LocalProvider(AbstractLLMProvider):
    """Interfaces with a local Ollama or vLLM instance using standard OpenAI schema."""
    def __init__(self, base_url: str = "http://localhost:11434/v1"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        # Pre-convert all tools to OpenAI schema format once upon session creation
        openai_tools = [_convert_tool_to_openai_schema(t) for t in tools if callable(t)]
        return {
            "model": model_name,
            "_history": [],
            "tools": openai_tools
        }

    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        # Handle user message or tool response parts safely
        if isinstance(payload, list):
            for part in payload:
                # If it's a tool response part from our helper
                if isinstance(part, dict) and part.get("role") == "tool":
                    session["_history"].append(part)
                else:
                    session["_history"].append({"role": "user", "content": str(part)})
        else:
            session["_history"].append({"role": "user", "content": str(payload)})
        
        request_body = {
            "model": session["model"],
            "messages": session["_history"]
        }
        
        # Attach tools if available
        if session.get("tools"):
            request_body["tools"] = session["tools"]
            request_body["tool_choice"] = "auto"

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=request_body
        )
        response.raise_for_status()
        data = response.json()
        
        # Append assistant response
        message = data["choices"][0]["message"]
        session["_history"].append(message)
        
        # FIX: Mock an object instance so getattr() works correctly in _run_with_tools
        usage_data = data.get("usage", {})
        class MockUsage:
            def __init__(self, count):
                self.total_token_count = count
        
        class LocalResponse:
            def __init__(self, msg, usage_obj):
                self.text = msg.get("content", "") or ""
                self.function_calls = msg.get("tool_calls", None)
                self.usage_metadata = usage_obj
            
        return LocalResponse(message, MockUsage(usage_data.get("total_tokens", 0)))

    def parse_tool_calls(self, response: Any) -> List[Dict]:
        calls = []
        raw_tool_calls = getattr(response, "function_calls", None)
        if raw_tool_calls:
            for call in raw_tool_calls:
                # OpenAI format: call['function']['name'] and call['function']['arguments'] (stringified JSON)
                if isinstance(call, dict) and "function" in call:
                    func_data = call["function"]
                    args_raw = func_data.get("arguments", "{}")
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    calls.append({
                        "name": func_data.get("name"),
                        "args": args
                    })
        return calls

    def format_tool_response(self, tool_name: str, result: str) -> Any:
        return {"role": "tool", "name": tool_name, "content": result}

    def format_tool_error(self, tool_name: str, error: str) -> Any:
        return {"role": "tool", "name": tool_name, "content": f"Error: {error}"}

    def prune_history(self, session: Any, max_turns: int) -> Any:
        if len(session["_history"]) > max_turns:
            # Keep system prompt/first instruction, prune the middle
            session["_history"] = [session["_history"][0]] + session["_history"][-(max_turns - 1):]
        return session

class AntigravityProvider(AbstractLLMProvider):
    """Hooks directly into the native 'agy' client to use native account credits."""
    
    def __init__(self):
        # Dynamically import agy to prevent crash if run outside the client
        try:
            from agy.core.session import AgySession
            self.agy_session = AgySession()
        except ImportError:
            raise RuntimeError("CRITICAL: Antigravity native modules not found. Are you running inside agy?")

    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        # Request a specific model tier from the native client (e.g., 'high' for Pro, 'standard' for Flash)
        # The agy client tracks the credit burn internally for this session
        return await self.agy_session.spawn_agent(
            model=model_name,
            tools=tools,
            enforce_json=False
        )

    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        # The native agy session handles backoffs, rate limits, and credit accounting automatically
        return await session.send(payload)

    def parse_tool_calls(self, response: Any) -> List[Dict]:
        # Adapt agy's native tool response objects into DumbleDoer's standard format
        calls = []
        if getattr(response, 'tool_calls', None):
            for call in response.tool_calls:
                calls.append({
                    "name": call.name,
                    "args": call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments)
                })
        return calls

    def format_tool_response(self, tool_name: str, result: str) -> Any:
        # Import agy's specific tool response class
        from agy.core.types import ToolResult
        return ToolResult(name=tool_name, content=result)

    def format_tool_error(self, tool_name: str, error: str) -> Any:
        from agy.core.types import ToolResult
        return ToolResult(name=tool_name, content=f"Error: {error}", is_error=True)

    def prune_history(self, session: Any, max_turns: int) -> Any:
        # Utilize agy's internal memory management if available
        if hasattr(session, 'truncate_context'):
            session.truncate_context(keep_recent=max_turns)
        return session
