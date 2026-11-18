"""Plain-Python helpers: a callback that cleans source links, and a tool that exports a CSV."""

import asyncio
import csv
import io
import json

import httpx
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext
from google.genai import types

# [Step 12] Google Search grounding returns temporary redirect links with this prefix
_REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


async def _resolve(client: httpx.AsyncClient, url: str) -> str:
    """Follows one redirect hop to get the real article URL; keeps the original on failure."""
    if not url.startswith(_REDIRECT_PREFIX):
        return url
    try:
        response = await client.head(url, follow_redirects=False)
        return response.headers.get("location", url)
    except httpx.HTTPError:
        return url


async def _resolve_all(urls: list[str]) -> list[str]:
    # The model sometimes packs several links into one comma-separated string, so split them first.
    flat = [u.strip() for entry in urls for u in entry.split(",") if u.strip()]
    async with httpx.AsyncClient(timeout=8) as client:
        resolved = await asyncio.gather(*(_resolve(client, u) for u in flat))
    return list(dict.fromkeys(resolved))  # drop duplicates, keep order


# [Step 12] after_agent_callback factory: runs AFTER an agent finishes, rewrites its saved
# report with real URLs, and returns the cleaned JSON as the agent's final message
# (so AgentTool hands the boss the clean version, not the redirect links).
def resolve_source_urls(output_key: str, list_key: str, url_field: str):
    async def callback(callback_context: CallbackContext) -> types.Content | None:
        report = callback_context.state.get(output_key)
        if isinstance(report, str):
            report = json.loads(report)
        if not isinstance(report, dict):
            return None
        for item in report.get(list_key, []):
            item[url_field] = await _resolve_all(item.get(url_field, []))
        callback_context.state[output_key] = report
        return types.Content(role="model", parts=[types.Part(text=json.dumps(report))])

    return callback


# [Step 12] a normal function tool for the boss: turns state["lead_report"] into a CSV artifact
async def export_leads_csv(tool_context: ToolContext) -> dict:
    """Saves the latest ranked lead report as leads.csv, a file the user can download."""
    report = tool_context.state.get("lead_report")
    if isinstance(report, str):
        report = json.loads(report)
    if not report or not report.get("leads"):
        return {"status": "error", "message": "No leads to export yet. Run lead_generation first."}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "company", "home_country", "score", "matched_patterns", "key_evidence", "source_urls"])
    for rank, lead in enumerate(report["leads"], start=1):
        writer.writerow([
            rank,
            lead["name"],
            lead["home_country"],
            lead["score"],
            "; ".join(lead["matched_patterns"]),
            lead["key_evidence"],
            " ".join(lead["source_urls"]),
        ])

    csv_file = types.Part.from_bytes(data=buffer.getvalue().encode("utf-8"), mime_type="text/csv")
    version = await tool_context.save_artifact("leads.csv", csv_file)
    return {"status": "success", "filename": "leads.csv", "version": version, "num_leads": len(report["leads"])}
