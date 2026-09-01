import os
import pytest
from yani_engine.core.sandbox import execute_bash


@pytest.mark.asyncio
async def test_permissions(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = await execute_bash("touch test_perm.txt", sandbox_mode="native")
        file_path = tmp_path / "test_perm.txt"
        assert file_path.exists()
        stat_info = os.stat(file_path)
        assert stat_info.st_uid == os.getuid()
    finally:
        os.chdir(original_cwd)

