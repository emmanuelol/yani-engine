from abc import ABC, abstractmethod
import typing
from typing import Any, List, Dict
import httpx
import json
import uuid
from google import genai
from google.genai.types import Part
import inspect

def _convert_tool_to_openai_schema(tool_func) -> dict:
    """Converts a yani-engine Python/MCP tool signature into an OpenAI-compatible function schema."""
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
        origin = typing.get_origin(annotation)
        if annotation is int:
            param_type = "integer"
        elif annotation is bool:
            param_type = "boolean"
        elif annotation is float:
            param_type = "number"
        elif annotation is list or origin in (list, tuple, set, typing.List, typing.Sequence):
            param_type = "array"
            
        prop_schema = {
            "type": param_type,
            "description": f"Parameter {param_name} for {name}"
        }
        if param_type == "array":
            prop_schema["items"] = {"type": "string"}
            
        properties[param_name] = prop_schema
        
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
    def format_tool_response(self, tool_name: str, result: str, call_id: str = None) -> Any:
        pass

    @abstractmethod
    def format_tool_error(self, tool_name: str, error: str, call_id: str = None) -> Any:
        pass

    @abstractmethod
    async def prune_history(self, session: Any, max_turns: int) -> tuple[Any, bool]:
        """Prunes the session history to prevent context window bloat. Returns (updated_session, bool_if_pruned)."""
        pass
        
    async def aclose(self):
        """Cleanup hook for lingering HTTP sessions."""
        pass
        
class GeminiProvider(AbstractLLMProvider):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        
    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        # [FIX]: Await the async SDK call before mutating the session
        session = await self.client.aio.chats.create(
            model=model_name,
            config={
                "tools": tools,
                "automatic_function_calling": {"disable": True}
            }
        )
        session._yani_model = model_name
        session._yani_tools = tools
        return session
        
    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        return await session.send_message(payload)
        
    def parse_tool_calls(self, response: Any) -> List[Dict]:
        calls = []
        if response.function_calls:
            for call in response.function_calls:
                calls.append({
                    "id": getattr(call, "id", None) or f"call_{uuid.uuid4().hex[:10]}",
                    "name": call.name,
                    "args": dict(call.args) if call.args else {}
                })
        return calls
        
    def format_tool_response(self, tool_name: str, result: str, call_id: str = None) -> Any:
        part = Part.from_function_response(name=tool_name, response={"result": result})
        if call_id and hasattr(part.function_response, "id"):
            part.function_response.id = call_id
        return part
    
    def format_tool_error(self, tool_name: str, error: str, call_id: str = None) -> Any:
        part = Part.from_function_response(name=tool_name, response={"error": error})
        if call_id and hasattr(part.function_response, "id"):
            part.function_response.id = call_id
        return part

    async def prune_history(self, session: Any, max_turns: int) -> tuple[Any, bool]:
        # [FIX]: Make pruning async to support the aio chats.create reconstruction
        history = getattr(session, 'history', None) or getattr(session, '_history', None)
        if history is None and hasattr(session, 'get_history') and callable(session.get_history):
            history = session.get_history()
        if history is not None and len(history) > max_turns:
            found_safe_boundary = False
            slice_index = -(max_turns - 1)
            
            while abs(slice_index) <= len(history):
                item = history[slice_index]
                item_role = getattr(item, 'role', None) or (item.get('role') if isinstance(item, dict) else None)
                if item_role == 'model':
                    found_safe_boundary = True
                    break
                slice_index -= 1

            if found_safe_boundary:
                new_history = [history[0]] + history[slice_index:]
                # Cleanly recreate session and await it
                new_session = await self.client.aio.chats.create(
                    model=getattr(session, '_yani_model', 'gemini-3.6-flash'),
                    config={"tools": getattr(session, '_yani_tools', []), "automatic_function_calling": {"disable": True}},
                    history=new_history
                )
                new_session._yani_model = getattr(session, '_yani_model', 'gemini-3.6-flash')
                new_session._yani_tools = getattr(session, '_yani_tools', [])
                return new_session, True
        return session, False

class MockUsage:
    def __init__(self, count):
        self.total_token_count = count

class LocalResponse:
    def __init__(self, msg, usage_obj):
        self.text = msg.get("content", "") or ""
        self.function_calls = msg.get("tool_calls", None)
        self.usage_metadata = usage_obj

class LocalProvider(AbstractLLMProvider):
    """Interfaces with a local Ollama or vLLM instance using standard OpenAI schema."""
    def __init__(self, base_url: str = "http://localhost:11434/v1"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        openai_tools = [_convert_tool_to_openai_schema(t) for t in tools if callable(t)]
        return {
            "model": model_name,
            "_history": [],
            "tools": openai_tools
        }

    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        # [FIX]: Idempotency - Clone the history to prevent duplicates on timeout/retry
        candidate_history = list(session["_history"])
        
        if isinstance(payload, list):
            for part in payload:
                if isinstance(part, dict) and part.get("role") == "tool":
                    candidate_history.append(part)
                else:
                    candidate_history.append({"role": "user", "content": str(part)})
        else:
            candidate_history.append({"role": "user", "content": str(payload)})
        
        request_body = {
            "model": session["model"],
            "messages": candidate_history
        }
        
        if session.get("tools"):
            request_body["tools"] = session["tools"]
            request_body["tool_choice"] = "auto"

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=request_body
        )
        response.raise_for_status()
        data = response.json()
        
        message = data["choices"][0]["message"]
        candidate_history.append(message)
        
        # Safely commit to state only after a 200 OK
        session["_history"] = candidate_history
        
        usage_data = data.get("usage", {})
        return LocalResponse(message, MockUsage(usage_data.get("total_tokens", 0)))

    def parse_tool_calls(self, response: Any) -> List[Dict]:
        calls = []
        raw_tool_calls = getattr(response, "function_calls", None)
        if raw_tool_calls:
            for call in raw_tool_calls:
                if isinstance(call, dict) and "function" in call:
                    func_data = call["function"]
                    args_raw = func_data.get("arguments", "{}")
                    
                    # [FIX]: Safely handle malformed tool JSON
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                        if not isinstance(args, dict):
                            args = {}
                    except json.JSONDecodeError:
                        args = {}
                        
                    call_id = call.get("id") or f"call_{uuid.uuid4().hex[:10]}"
                    call["id"] = call_id
                    
                    calls.append({
                        "id": call_id,
                        "name": func_data.get("name", "unknown"),
                        "args": args
                    })
        return calls

    def format_tool_response(self, tool_name: str, result: str, call_id: str = None) -> Any:
        # [FIX]: Hard-enforce tool_call_id inclusion to prevent 400 Bad Request
        call_id = call_id or f"call_{uuid.uuid4().hex[:10]}"
        return {"role": "tool", "name": tool_name, "content": result, "tool_call_id": call_id}

    def format_tool_error(self, tool_name: str, error: str, call_id: str = None) -> Any:
        call_id = call_id or f"call_{uuid.uuid4().hex[:10]}"
        return {"role": "tool", "name": tool_name, "content": f"Error: {error}", "tool_call_id": call_id}

    async def prune_history(self, session: Any, max_turns: int) -> tuple[Any, bool]:
        history = session["_history"]
        if len(history) > max_turns:
            found_safe_boundary = False
            slice_index = -(max_turns - 1)

            # [FIX]: Off-by-one correction to guarantee boundary inclusion
            while abs(slice_index) <= len(history):
                item = history[slice_index]
                if item.get("role") == "user":
                    found_safe_boundary = True
                    break
                slice_index -= 1

            if found_safe_boundary:
                session["_history"] = [history[0]] + history[slice_index:]
                return session, True

        return session, False

    async def aclose(self):
        await self.client.aclose()


class AntigravityProvider(AbstractLLMProvider):
    """Hooks directly into the native 'agy' client to use native account credits."""
    
    def __init__(self):
        try:
            from agy.core.session import AgySession
            self.agy_session = AgySession()
        except ImportError:
            raise RuntimeError("CRITICAL: Antigravity native modules not found. Are you running inside agy?")

    async def create_chat_session(self, model_name: str, tools: List[Any]) -> Any:
        return await self.agy_session.spawn_agent(
            model=model_name,
            tools=tools,
            enforce_json=False
        )

    async def send_message(self, session: Any, payload: str | List[Any]) -> Any:
        return await session.send(payload)

    def parse_tool_calls(self, response: Any) -> List[Dict]:
        calls = []
        if getattr(response, 'tool_calls', None):
            for call in response.tool_calls:
                # [FIX]: Added exception protection for native client hallucinations
                args_raw = call.arguments
                try:
                    args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw)
                    if not isinstance(args, dict):
                        args = {}
                except (json.JSONDecodeError, TypeError):
                    args = {}
                    
                calls.append({
                    "id": getattr(call, "id", None) or f"call_{uuid.uuid4().hex[:10]}",
                    "name": call.name,
                    "args": args
                })
        return calls

    def format_tool_response(self, tool_name: str, result: str, call_id: str = None) -> Any:
        from agy.core.types import ToolResult
        return ToolResult(name=tool_name, content=result, tool_call_id=call_id)

    def format_tool_error(self, tool_name: str, error: str, call_id: str = None) -> Any:
        from agy.core.types import ToolResult
        return ToolResult(name=tool_name, content=f"Error: {error}", is_error=True, tool_call_id=call_id)

    async def prune_history(self, session: Any, max_turns: int) -> tuple[Any, bool]:
        if hasattr(session, 'truncate_context'):
            session.truncate_context(keep_recent=max_turns)
            return session, True
        return session, False
