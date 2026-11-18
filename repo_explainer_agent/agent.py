"""Entry point: ADK loads `root_agent` from this file."""

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import types

from . import config
from .repo_tools import analyze_github_repo

# the front door: one agent, one tool. The fixed steps (clone, clean, map, cleanup) live in
# plain Python inside the tool; the agent only decides WHEN to call it and how to present the result.
root_agent = LlmAgent(
    name="repo_explainer",
    model=Gemini(
        model=config.AGENT_MODEL,
        retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2),  # retry on 503/429
    ),
    description="Explains a public GitHub repository: what it does, its architecture, and its risks.",
    instruction=(
        "You help people quickly understand public GitHub repositories.\n"
        # when to call the tool (and when NOT to - every call costs money)
        "When the user shares a GitHub link, call analyze_github_repo with it. If they mention "
        "something to look at closely (security, tests, an API), pass that as focus. If there is "
        "no link yet, ask for one.\n"
        # how to present the result
        "When the tool succeeds, reply with: a one-line header with the repo name, main language, "
        "stars, and size; then the report with its four sections, without adding facts that are "
        "not in it; then a last line in the form 'Analyzed X files in Y model calls, about $Z.'\n"
        # errors should be explained, not dumped
        "When the tool returns an error, explain it in one or two plain sentences and suggest a "
        "fix, such as a smaller repo or a public link.\n"
        # follow-ups reuse the report already in the conversation, so they cost almost nothing
        "Answer follow-up questions from the report already in this conversation. Only call the "
        "tool again for a different repo or a new focus."
    ),
    tools=[analyze_github_repo],  # a plain async function becomes a tool; its docstring is the manual
)
