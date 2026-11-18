"""Pipeline 2: find NEW companies that show the discovered patterns but have not invested yet."""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import google_search

from .config import MODEL
from .schemas import LeadList, LeadReport
from .tools import resolve_source_urls

# spells out what "not invested yet" means: factories, plants and JVs all count as investing
_NOT_INVESTED = (
    "has NOT announced, started building, or operated a factory, plant, or other major "
    "facility in the target country, directly or through a joint venture or licensing "
    "deal (sales offices and imports are fine)"
)

lead_finder = LlmAgent(
    name="lead_finder",
    model=MODEL,
    # the big players have usually invested already, so look at mid-sized/emerging
    # companies, self-check each one, and return extras so the validator has room to filter
    instruction="Research request: {intent}\nSuccess patterns: {patterns}\n"
    "Companies already studied (never list these): {companies}\n"
    "Use Google Search to find foreign companies in this industry that "
    f"{_NOT_INVESTED}, but in the last 12 months showed at least two of the success "
    "patterns. Well-known market leaders have usually invested already, so focus on "
    "mid-sized and emerging companies. Before listing a company, search for its name plus "
    "'factory' or 'plant' and the target country, and drop it if a facility exists or was "
    "announced. List num_companies plus 2 candidates. For each, give the name, home "
    "country, why it is a candidate, and a source URL. "
    "Write your final answer exactly once; never repeat or rewrite it.",
    tools=[google_search],
    output_key="raw_leads",
)

lead_formatter = LlmAgent(
    name="lead_formatter",
    model=MODEL,
    instruction="Convert this research into a clean structured list:\n{raw_leads}",
    output_schema=LeadList,
    output_key="leads",
)

lead_validator = LlmAgent(
    name="lead_validator",
    model=MODEL,
    # two plain yes/no questions + an explicit rule (the double negative confused the model)
    instruction="Research request: {intent}\nLeads: {leads}\n"
    "For each lead, use Google Search to answer two yes/no questions:\n"
    "Q1: Is the company headquartered outside the target country?\n"
    "Q2: Does it already have, or has it announced, a factory, plant, or other major "
    "facility in the target country, including through a joint venture or licensing deal?\n"
    "Rule: VALID only when Q1 is yes AND Q2 is no. Every other case is INVALID.\n"
    "Examples: a company with a joint-venture plant in the target country has Q2 = yes, "
    "so it is INVALID. A company with no plant there yet has Q2 = no, so it is VALID, "
    "because it is exactly the kind of company we want as a lead.\n"
    "Answer one line per lead in the form "
    "'Company: Q1=yes/no, Q2=yes/no -> VALID or INVALID - reason - source URL'. "
    "Write your final answer exactly once; never repeat or rewrite it.",
    tools=[google_search],
    output_key="lead_validation",
)

lead_signal_analyzer = LlmAgent(
    name="lead_signal_analyzer",
    model=MODEL,
    instruction="Success patterns: {patterns}\nLeads: {leads}\n"
    "For each lead, use Google Search to find recent evidence (last 12 months) of each "
    "pattern. List the matched patterns with date and source URL, then give the lead a "
    "score from 1 (weak) to 10 (very likely to invest soon). "
    "Write your final answer exactly once; never repeat or rewrite it.",
    tools=[google_search],
    output_key="lead_signals",
)

parallel_lead_checks = ParallelAgent(
    name="parallel_lead_checks",
    sub_agents=[lead_validator, lead_signal_analyzer],
)

report_compiler = LlmAgent(
    name="report_compiler",
    model=MODEL,
    # only VALID leads may appear; an empty list is an acceptable answer
    instruction="Research request: {intent}\n"
    "Lead validation (VALID or INVALID per lead):\n{lead_validation}\n\n"
    "Lead signal analysis (matched patterns and score):\n{lead_signals}\n\n"
    "Include ONLY leads marked VALID in the validation report; leave out every INVALID "
    "lead no matter how high its score. Rank the rest by score. If no lead is VALID, "
    "return an empty leads list and explain why in the summary. Use only evidence from "
    "the reports; never invent facts or URLs.",
    output_schema=LeadReport,
    output_key="lead_report",
    # swap Google's temporary redirect links for the real article URLs
    after_agent_callback=resolve_source_urls("lead_report", "leads", "source_urls"),
)

lead_generation = SequentialAgent(
    name="lead_generation",
    description="Finds new companies that match the discovered patterns and ranks them as leads.",
    sub_agents=[lead_finder, lead_formatter, parallel_lead_checks, report_compiler],
)
