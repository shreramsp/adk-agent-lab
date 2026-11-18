from google.adk.models import Gemini
from google.genai import types

# One shared model for every agent. Retries with growing waits on 503 (busy) / 429 (rate limit).
MODEL = Gemini(
    model="gemini-3.5-flash-lite",
    retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2),
)
