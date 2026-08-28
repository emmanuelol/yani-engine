import sys
sys.path.append('.')
import asyncio
import os
from google import genai
from yani_engine.core.sandbox import execute_bash

async def test():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Skipping test_sdk: No GEMINI_API_KEY/GOOGLE_API_KEY set.")
        return
    client = genai.Client(api_key=api_key)
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
