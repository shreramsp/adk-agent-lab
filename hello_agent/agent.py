from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent


def get_current_time(timezone: str) -> dict:
    """Returns the current time in an IANA timezone, e.g. 'America/Los_Angeles' or 'Asia/Tokyo'."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        return {"status": "error", "message": f"Unknown timezone: {timezone}"}
    return {"status": "success", "time": now.strftime("%Y-%m-%d %H:%M:%S %Z")}


root_agent = Agent(
    name="hello_agent",
    model="gemini-2.5-flash",
    description="A friendly assistant that can tell the current time anywhere.",
    instruction="You are a friendly assistant. When the user asks about the time "
    "in a place, call get_current_time with the correct IANA timezone.",
    tools=[get_current_time],
)
