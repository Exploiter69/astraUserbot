import os
import aiohttp
from helpers.net import get_session
from core.errors import CommandError

# The key is read from the environment to prevent hardcoding secrets
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

async def get_chat_completion(messages: list[dict], model: str = "llama3-70b-8192") -> str:
    """Routes LLM inference to Groq via the shared aiohttp connection pool."""
    if not GROQ_API_KEY:
        raise CommandError("GROQ_API_KEY environment variable is not set. Cannot use AI features.")
        
    session = get_session()
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7
    }
    
    async with session.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise CommandError(f"Groq API Error ({resp.status}): {err_text}")
        data = await resp.json()
        return data["choices"][0]["message"]["content"]

async def transcribe_audio(file_path: str, model: str = "whisper-large-v3") -> str:
    """Routes audio transcription to Groq Whisper."""
    if not GROQ_API_KEY:
        raise CommandError("GROQ_API_KEY environment variable is not set.")
        
    session = get_session()
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }
    
    data = aiohttp.FormData()
    data.add_field('file', open(file_path, 'rb'), filename=os.path.basename(file_path))
    data.add_field('model', model)
    
    async with session.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, data=data) as resp:
        if resp.status != 200:
            err_text = await resp.text()
            raise CommandError(f"Groq Whisper API Error ({resp.status}): {err_text}")
        json_data = await resp.json()
        return json_data["text"]
