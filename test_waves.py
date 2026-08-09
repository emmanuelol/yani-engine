import asyncio
from dumbledoer.core.config import config
from dumbledoer.core.planner import WavePlanner

async def test():
    config.start_at_index = 2
    planner = WavePlanner(start_at_index=config.start_at_index)
    waves = await planner.get_pending_waves()
    print("Waves:", waves)

asyncio.run(test())
