import os
from openai import OpenAI

api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")

# Connect the official OpenAI client to your LiteLLM proxy
client = OpenAI(api_key=api_key, base_url=base_url)

CHAT_MODEL = os.getenv("MODEL","claude-4.5-sonnet")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL","text-embedding-3-large")
