"""Pipeline 1: study companies that ALREADY invested and find the signals they showed beforehand."""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import google_search

from .config import MODEL
from .schemas import CompanyList, PatternReport, ResearchIntent
from .tools import resolve_source_urls

intent_extractor = LlmAgent(
    name="intent_extractor",
    model=MODEL,
    instruction="Read the user's request and extract the target industry, the target "
    "country, and how many companies to study. If no count is given, use 3.",
    output_schema=ResearchIntent,
    output_key="intent",
)

company_finder = LlmAgent(
    name="company_finder",
    model=MODEL,
    instruction="Research request: {intent}\n"
    "Use Google Search to find foreign companies in this industry that made a major "
    "investment (new factory, office, or acquisition) in the target country in the "
    "last 3 years. Find exactly num_companies of them. For each, give the company name, "
    "its home country, what it invested in, when, and the source URL.",
    tools=[google_search],
    output_key="raw_companies",
)

company_formatter = LlmAgent(
    name="company_formatter",
    model=MODEL,
    instruction="Convert this research into a clean structured list:\n{raw_companies}",
    output_schema=CompanyList,
    output_key="companies",
)

validator = LlmAgent(
    name="validator",
    model=MODEL,
    instruction="Research request: {intent}\nCompanies: {companies}\n"
    "For each company, use Google Search to verify: (1) it is headquartered outside the "
    "target country, (2) the investment in the target country really happened, and "
    "(3) it was within the last 3 years. Mark each company VALID or INVALID with a "
    "one-line reason and a source URL. "
    "Write your final answer exactly once; never repeat or rewrite it.",
    tools=[google_search],
    output_key="validation",
)

signal_searcher = LlmAgent(
    name="signal_searcher",
    model=MODEL,
    instruction="Research request: {intent}\nCompanies: {companies}\n"
    "For each company, use Google Search to find signals from 6-24 months BEFORE its "
    "investment that hinted it was coming: hiring for roles in the target country, "
    "executive visits or statements, partnerships, new subsidiaries, site-selection "
    "news, or government incentives. List each signal with its date and source URL. "
    "Write your final answer exactly once; never repeat or rewrite it.",
    tools=[google_search],
    output_key="signals",
)

# Runs both at once; finishes when both are done.
parallel_research = ParallelAgent(
    name="parallel_research",
    sub_agents=[validator, signal_searcher],
)

pattern_synthesizer = LlmAgent(
    name="pattern_synthesizer",
    model=MODEL,
    instruction="Research request: {intent}\n"
    "Validation report (VALID or INVALID per company):\n{validation}\n\n"
    "Signal report (signals seen before each investment):\n{signals}\n\nIgnore INVALID "
    "companies. Find 3-5 patterns that showed up in at least two valid companies. Use "
    "only evidence from the reports and never invent facts or URLs.",
    output_schema=PatternReport,
    output_key="patterns",
    # [Step 12] swap Google's temporary redirect links for the real article URLs
    after_agent_callback=resolve_source_urls("patterns", "patterns", "evidence_urls"),
)

pattern_discovery = SequentialAgent(
    name="pattern_discovery",
    description="Studies companies that already invested and finds the signals they showed beforehand.",
    sub_agents=[
        intent_extractor,
        company_finder,
        company_formatter,
        parallel_research,
        pattern_synthesizer,
    ],
)
