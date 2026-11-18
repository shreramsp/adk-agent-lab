# adk-agent-lab

End-to-end AI agents built with [Google ADK](https://google.github.io/adk-docs/), Gemini, and MCP.

## Agents

| Agent | Description |
|---|---|
| [Deep Research Lead Generation](lead_gen_agent/) | Multi-agent web research pipeline that learns pre-investment signals from past investors and finds new companies showing them, with ranked leads and CSV export |
| [GitHub Repo Explainer](repo_explainer_agent/) | ADK agent that uses Gemini CLI as a tool to review any public GitHub repo, with cost caps, untrusted-repo lock-down, and a private Cloud Run deployment |
| [Bug Assistant (MCP)](bug_assistant_agent/) | Bug triage agent whose tools all come from two MCP servers (MCP Toolbox over Postgres, GitHub MCP): duplicate detection, triage summary, and human approval for every write |
| [Code Review Assistant](code_review_agent/) | Reviews Python code with AST-based structure, complexity and security checks, PEP 8 scoring, and AI-written tests run in a Docker sandbox; fixes code in a loop with a code-enforced acceptance rule, and remembers past reviews |
| [Shop Assistant](shop_agent/) | Sports-store shopping agent on AlloyDB (Omni) via MCP Toolbox: hybrid vector + filter search with Gemini embeddings, all-or-nothing orders with approval, and session-enforced identity |

## Tech Stack

- Google Agent Development Kit (ADK)
- Gemini models
- Model Context Protocol (MCP) / MCP Toolbox for Databases
- Google Cloud Run, AlloyDB (Omni) with pgvector and ScaNN

## Getting started

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
adk web          # run from the repo root, then pick an agent in the browser
```

Each agent folder has its own `README.md` and `.env.example`. `hello_agent/` is a minimal single-tool agent for checking your setup.
