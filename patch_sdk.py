import os

paths = [
    os.path.expanduser("~/.gemini/config/plugins/dumbledoer/dumbledoer/dumbledoer_cli.py"),
    os.path.expanduser("~/Documentos/GitHub/DumbleDoer/dumbledoer/dumbledoer_cli.py")
]

for p in paths:
    if not os.path.exists(p):
        continue
    with open(p, "r") as f:
        c = f.read()

    # Strip config from chats.create
    c = c.replace(
        'chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": self.gemini_tools})',
        'chat_session = self.client.aio.chats.create(model="gemini-2.5-flash")'
    )
    c = c.replace(
        'chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": list(self.gemini_tools)})',
        'chat_session = self.client.aio.chats.create(model="gemini-2.5-flash")'
    )
    
    # Strip config from fallback chat session
    c = c.replace(
        'self.chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": self.gemini_tools})',
        'self.chat_session = self.client.aio.chats.create(model="gemini-2.5-flash")'
    )
    c = c.replace(
        'self.chat_session = self.client.aio.chats.create(model="gemini-2.5-flash", config={"tools": list(self.gemini_tools)})',
        'self.chat_session = self.client.aio.chats.create(model="gemini-2.5-flash")'
    )

    # Add config directly to send_message via Late Binding
    if 'send_message(prompt_payload)' in c:
        c = c.replace(
            'send_message(prompt_payload)',
            'send_message(prompt_payload, config={"tools": list(self.gemini_tools)})'
        )
        
    if 'send_message(f"Execute {command} with {args}")' in c:
        c = c.replace(
            'send_message(f"Execute {command} with {args}")',
            'send_message(f"Execute {command} with {args}", config={"tools": list(self.gemini_tools)})'
        )

    # Fail-safe: ensure .codegraph exists so the npx server never panics
    if 'if not os.path.exists(".codegraph"):' in c and 'os.makedirs(".codegraph"' not in c:
        c = c.replace(
            'if not os.path.exists(".codegraph"):',
            'if not os.path.exists(".codegraph"):\n            os.makedirs(".codegraph", exist_ok=True)'
        )

    with open(p, "w") as f:
        f.write(c)
    print("Successfully patched: " + p)
