import sys
sys.path.append('.')
import asyncio
import os
from google import genai
from dumbledoer.core.sandbox import execute_bash

async def test():
    client = genai.Client()
    chat = client.aio.chats.create(model='gemini-2.5-flash')
    response = await chat.send_message(
        'Please run echo hello using execute_bash', 
        config={'tools': [execute_bash], 'automatic_function_calling': {'disable': False}}
    )
    print("Response text:", response.text)
    if hasattr(response, "candidates") and response.candidates:
        if response.candidates[0].content.parts:
            print("Response parts:", [p for p in response.candidates[0].content.parts])

if __name__ == "__main__":
    asyncio.run(test())
