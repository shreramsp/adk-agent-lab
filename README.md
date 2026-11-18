# adk-agent-lab

End-to-end AI agents built with [Google ADK](https://google.github.io/adk-docs/), Gemini, and MCP.

## Agents

| Agent | Description | Status |
|---|---|---|
| [Deep Research Lead Generation](lead_gen_agent/) | Multi-agent web research pipeline that learns pre-investment signals from past investors and finds new companies showing them, with ranked leads and CSV export | ✅ Done |
| Gemini CLI Tool Agent | ADK agent that delegates tasks to Gemini CLI as a tool | 🚧 Planned |
| Bug Assistant (MCP) | Bug triage assistant powered by MCP tools (database, GitHub, search) | 🚧 Planned |
| Code Review Assistant | Production-style code review pipeline with analysis, testing, and feedback | 🚧 Planned |
| E-Commerce Agent | Shopping assistant with vector search over AlloyDB via MCP Toolbox | 🚧 Planned |

## Tech Stack

- Google Agent Development Kit (ADK)
- Gemini models
- Model Context Protocol (MCP) / MCP Toolbox for Databases
- Google Cloud (Cloud Run, AlloyDB)

## Getting started

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
adk web          # run from the repo root, then pick an agent in the browser
```

Each agent folder has its own `README.md` and `.env.example`. `hello_agent/` is a minimal single-tool agent for checking your setup.
