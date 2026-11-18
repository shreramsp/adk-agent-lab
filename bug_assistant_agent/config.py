"""Every setting for the bug assistant in one place, so they're easy to find and tune."""

import os

# --- The ADK agent that talks to the user ---
AGENT_MODEL = "gemini-3.5-flash-lite"  # it mostly picks tools and formats rows, so the cheapest model is enough

# --- MCP servers ---
# Where MCP Toolbox serves our database tools (started by run_toolbox.sh).
# adk web loads .env before importing this file, so TOOLBOX_URL in .env can override it.
TOOLBOX_URL = os.getenv("TOOLBOX_URL", "http://127.0.0.1:5000/mcp")

# Toolbox tools split by risk. Read tools run freely; write tools change shared data, so ADK
# pauses and asks a human to approve each call (enforced in code, not just asked for in the prompt).
TICKET_READ_TOOLS = ["search-tickets", "get-ticket", "list-open-tickets", "find-duplicate-tickets", "triage-summary"]
TICKET_WRITE_TOOLS = ["create-ticket", "update-ticket-status", "assign-ticket", "mark-duplicate"]

# GitHub's official MCP server, hosted by GitHub (nothing to install or run).
# Login = the GITHUB_TOKEN in .env (a read-only token). If it's missing, the agent runs without GitHub.
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Only these GitHub tools are enabled. GitHub has ~100; every tool's description is sent
# to Gemini on each message, so fewer tools = fewer tokens and fewer wrong choices.
GITHUB_TOOLS = ["search_issues", "issue_read", "search_repositories"]

# Max results per GitHub search. The default is 30 full issues, which can be tens of
# thousands of tokens per search; 5 is plenty to spot a known bug.
GITHUB_MAX_RESULTS = 5

# Fields kept per GitHub issue. Without this, 5 issues = ~4,700 tokens (full bodies,
# reactions, labels); with it, ~260 tokens. The agent can still open one issue with issue_read.
GITHUB_ISSUE_FIELDS = ["number", "title", "state", "html_url", "comments", "created_at"]
