import pytest
import asyncio
from yani_engine.core.sandbox import execute_bash

@pytest.mark.asyncio
async def test_native_sandbox_execution():
    result = await execute_bash("echo 'native execution success'", sandbox_mode="native")
    assert "native execution success" in result
