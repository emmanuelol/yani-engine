import os
import pytest
from yani_engine.core.planner import WavePlanner


@pytest.mark.asyncio
async def test_wave_planner_pending_waves(tmp_path):
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with open("memory.md", "w", encoding="utf-8") as f:
            f.write("# Memory\n\n## Task Registry\n| Task ID | Title | Type | Status | Depends On |\n|---|---|---|---|---|\n")
        planner = WavePlanner(start_at_index=2)
        waves = await planner.get_pending_waves()
        assert isinstance(waves, list)
    finally:
        os.chdir(original_cwd)

