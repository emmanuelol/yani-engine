from yani_engine.core.llm_provider import _convert_tool_to_openai_schema
from yani_engine.core.state import read_file
import json

schema = _convert_tool_to_openai_schema(read_file)
print(json.dumps(schema, indent=2))
