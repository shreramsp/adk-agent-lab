"""Entry point: ADK loads `root_agent` from this file.

    code_review_assistant (LlmAgent, routes by transferring the conversation)
    ├── review_pipeline (Pipeline: steps in order, stops early on bad input)
    │     static_analyzer (code) → test_writer (LLM) → test_runner (code, Docker) → feedback_writer (LLM)
    └── fix_pipeline (Pipeline)
          fix_setup (code) → fix_loop (LoopAgent, max 3: code_fixer (LLM) → fix_checker (code)) → fix_reporter (LLM)
"""

import warnings

from google.adk.agents import LlmAgent, LoopAgent
from google.adk.models import Gemini
from google.genai import types

from . import config
from .steps import FixChecker, FixSetup, Pipeline, StaticAnalyzer, TestRunner, remember_review

# LoopAgent is marked deprecated in favour of Workflow, but a Workflow can't be a sub-agent that an
# LlmAgent transfers to, so it is still the right tool inside a chat router.
warnings.filterwarnings("ignore", message=r".*LoopAgent is deprecated.*")


def _model() -> Gemini:
    return Gemini(model=config.MODEL, retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2))


# Worker LLM agents only see what their instruction gives them (include_contents="none"): the code
# and reports come from state via {key}. Without this, each would also receive the whole chat
# history, which costs tokens on every call. They also can't transfer anywhere.
_WORKER = dict(include_contents="none", disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
_PRECISE = types.GenerateContentConfig(temperature=0.2)


# ---------------------------------------------------------------- review pipeline

test_writer = LlmAgent(
    name="test_writer",
    model=_model(),
    generate_content_config=_PRECISE,
    description="Writes unittest tests for the submitted code.",
    instruction=(
        "Write Python unittest tests for the code below. The code is saved as solution.py.\n\n"
        "CODE:\n{code}\n\n"
        "STRUCTURE AND FINDINGS:\n{analysis_report}\n\n"
        "Rules:\n"
        "- Start with: import unittest, then from solution import the names you test.\n"
        "- Write 4 to 8 short test methods in one TestCase class. Test the behaviour the names and "
        "docstrings promise, including edge cases such as empty input, zero, None, and wrong types.\n"
        "- A test should fail when the code has a real bug, so do not copy the code's current output "
        "as the expected value; decide what the correct result is.\n"
        "- Do not test anything that touches files, the network, subprocesses, the clock, or randomness, "
        "and do not use mocks. Skip functions that only do those things.\n"
        "- If nothing in the code can be tested this way, reply with exactly: NO_TESTS\n"
        "Reply with only the test code in one ```python block."
    ),
    output_key="tests",
    **_WORKER,
)

feedback_writer = LlmAgent(
    name="feedback_writer",
    model=_model(),
    description="Writes the final review from the analysis and test results.",
    instruction=(
        "You are a senior Python reviewer. Write a review of the code using ONLY the findings below. "
        "Do not invent problems that are not listed.\n\n"
        "CODE:\n{code}\n\n"
        "STATIC ANALYSIS (exact, from tools):\n{analysis_report}\n\n"
        "TEST RESULTS (run in a sandbox):\n{test_report}\n\n"
        "THE USER'S HISTORY:\n{history_note}\n\n"
        "Format, in Markdown:\n"
        "1. One line: a verdict, then 'Style X/100 · Security N · Tests P/T · Max complexity C'.\n"
        "2. '🔴 Must fix': high security findings and failing tests. For each failing test, say whether "
        "the code is wrong or the test's expectation is debatable, with the line number.\n"
        "3. '🟡 Should fix': medium/low security findings, complex functions, missing docstrings.\n"
        "4. '🔵 Style': group the PEP 8 issues by kind; do not list every one.\n"
        "5. '📈 Progress': only if the history shows earlier reviews. Mention the score trend and any "
        "problem that keeps coming back, in one or two sentences.\n"
        "Leave out empty sections. Cite line numbers. Stay under 300 words. If there is anything to fix, "
        "end with: 'Want me to fix these? I'll fix the code, re-run the tests, and only accept a version "
        "that doesn't make anything worse.'"
    ),
    output_key="review",
    after_agent_callback=remember_review,  # saves a short record in `user:` state (review memory)
    **_WORKER,
)

review_pipeline = Pipeline(
    name="review_pipeline",
    description="Reviews Python code: static analysis, generated tests run in a sandbox, then written feedback.",
    sub_agents=[StaticAnalyzer(name="static_analyzer"), test_writer, TestRunner(name="test_runner"), feedback_writer],
)


# ---------------------------------------------------------------- fix pipeline

code_fixer = LlmAgent(
    name="code_fixer",
    model=_model(),
    generate_content_config=_PRECISE,
    description="Rewrites the reviewed code to fix its problems.",
    instruction=(
        "Fix the Python code below.\n\n"
        "ORIGINAL CODE:\n{code}\n\n"
        "FINDINGS:\n{analysis_report}\n\n"
        "TESTS THE FIXED CODE MUST PASS:\n{tests}\n\n"
        "CURRENT TEST RESULTS:\n{test_report}\n\n"
        "FEEDBACK ON YOUR PREVIOUS ATTEMPT:\n{fix_feedback}\n\n"
        "Rules:\n"
        "- Keep every public function and class name and its parameters, because the tests import them.\n"
        "- Fix every security finding: read secrets with os.environ, pass subprocess a list of "
        "arguments (shlex.split for a command string) without shell=True, catch specific exceptions.\n"
        "- Fix real bugs so the tests pass. Never add special cases for specific test inputs.\n"
        "- Split any function above the complexity limit into smaller helpers.\n"
        "- Follow PEP 8 and add a short docstring to each function and class.\n"
        "- Do not change behaviour that is not related to a finding or a failing test.\n"
        "Reply with only the complete fixed module in one ```python block."
    ),
    output_key="fixed_code_raw",
    **_WORKER,
)

fix_loop = LoopAgent(
    name="fix_loop",
    description="Fix, then re-check and re-test, until the checker accepts or attempts run out.",
    sub_agents=[code_fixer, FixChecker(name="fix_checker")],
    max_iterations=config.FIX_MAX_ATTEMPTS,  # the hard cap; FixChecker escalates earlier on success
)

fix_reporter = LlmAgent(
    name="fix_reporter",
    model=_model(),
    description="Presents the fixed code and what changed.",
    instruction=(
        "Report the result of an automatic code fix.\n\n"
        "RESULT (exact, from the checker):\n{fix_summary}\n\n"
        "ORIGINAL CODE:\n{code}\n\n"
        "FIXED CODE:\n{fixed_code}\n\n"
        "Write, in Markdown: the result line; a small before/after table (style, security findings, "
        "tests) using only the numbers in RESULT; 'What changed' as 3 to 6 bullets that compare the two "
        "versions; if the result is NOT FULLY FIXED, what is still open and why; then the complete fixed "
        "code in one ```python block. Keep the text under 200 words, not counting the code."
    ),
    **_WORKER,
)

fix_pipeline = Pipeline(
    name="fix_pipeline",
    description="Fixes the code from the last review and re-tests it in a loop (max 3 attempts).",
    sub_agents=[FixSetup(name="fix_setup"), fix_loop, fix_reporter],
)


# ---------------------------------------------------------------- root

root_agent = LlmAgent(
    name="code_review_assistant",
    model=_model(),
    description="Reviews Python code for structure, style, security, complexity and correctness, and can fix it.",
    instruction=(
        "You are the front desk of a Python code review assistant. You never review or fix code yourself; "
        "you hand the conversation to the right pipeline.\n"
        "- If the user's latest message contains Python code (in a ``` block or pasted), transfer to "
        "review_pipeline without writing anything.\n"
        "- If the user asks to fix the code that was just reviewed (for example 'yes', 'fix it', "
        "'please fix'), transfer to fix_pipeline without writing anything.\n"
        "- Otherwise answer briefly yourself. If asked what you can do: you check structure and "
        "complexity, PEP 8 style, and security risks with exact tools; you write unit tests and run them "
        "in an isolated Docker sandbox; you remember past reviews to show progress; and you can fix the "
        "code, re-testing until nothing is worse. If the user asks for a review without code, ask them "
        "to paste it. Answer questions about an earlier review from the conversation."
    ),
    sub_agents=[review_pipeline, fix_pipeline],  # transfer = hand over the conversation (not AgentTool)
)
