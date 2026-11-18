"""Entry point: ADK loads `root_agent` from this file."""

import os

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.agent_tool import AgentTool

from .config import MODEL
from .lead_generation import lead_generation
from .pattern_discovery import pattern_discovery
from .tools import export_leads_csv

# The "boss": chats with the user and decides WHEN to run each pipeline.
# Each pipeline becomes one tool; state they save (patterns, lead_report...) flows back into this session.
lead_gen_boss = LlmAgent(
    name="lead_gen_boss",
    model=MODEL,
    description="Finds B2B sales leads by learning from companies that already invested.",
    instruction="You are a lead-generation research assistant. Work in two phases.\n"
    "Phase 1: when the user names an industry and a target country, call "
    "pattern_discovery with their request in plain words. Then show the discovered "
    "patterns as a short list (pattern name, typical lead time, companies that showed it) "
    "and ask the user whether to continue to lead generation.\n"
    "Phase 2: only after the user says yes, call lead_generation with a short request. "
    "Then present the ranked leads as a markdown table with columns Rank, Company, "
    "Country, Score, Matched patterns, followed by the summary and the source links. "
    # [Step 12] the boss now also saves a downloadable CSV
    "Finally call export_leads_csv and tell the user leads.csv is in the Artifacts tab.\n"
    "If the industry or country is missing, ask for it first. Never call lead_generation "
    "before pattern_discovery has run. Only use facts from the tool results.",
    tools=[AgentTool(agent=pattern_discovery), AgentTool(agent=lead_generation), export_leads_csv],
)

# [Step 12] SHOW_FLOW switch (set in .env, then restart adk web) - for demos and the video:
#   (unset)            -> the boss: chats, asks to confirm, but hides the inner agents
#   pattern_discovery  -> run pipeline 1 directly; adk web draws all its inner agents
#   lead_generation    -> pipeline 2 directly (only works after pattern_discovery in the same session)
#   full               -> both pipelines back to back, every inner agent visible, no confirmation
_SHOW_FLOW = os.getenv("SHOW_FLOW", "").strip().lower()

if _SHOW_FLOW == "pattern_discovery":
    root_agent = pattern_discovery
elif _SHOW_FLOW == "lead_generation":
    root_agent = lead_generation
elif _SHOW_FLOW == "full":
    root_agent = SequentialAgent(name="full_flow", sub_agents=[pattern_discovery, lead_generation])
else:
    root_agent = lead_gen_boss
