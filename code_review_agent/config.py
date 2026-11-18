"""Every model, cost, and safety setting for the code review assistant in one place."""

# --- Models ---
# All four LLM steps (router, test writer, feedback writer, fixer, reporter) use the cheapest model:
# the hard, exact work (parsing, style, security, running tests) is done by plain Python.
MODEL = "gemini-3.5-flash-lite"

# --- Input limits (cost control) ---
MAX_CODE_LINES = 400  # bigger submissions are refused before any model call

# --- Static analysis ---
MAX_LINE_LENGTH = 99  # PEP 8 allows teams to raise the 79 limit up to 99
COMPLEXITY_LIMIT = 10  # cyclomatic complexity above this = "too complex to test well"
COMPLEXITY_WARN = 6  # above this = "getting complex"
MAX_STYLE_ISSUES_SHOWN = 12  # only the first N style issues are sent to the model

# --- Test sandbox (Docker) ---
SANDBOX_IMAGE = "python:3.13-alpine"  # small official image; pulled once with `docker pull`
SANDBOX_TIMEOUT_S = 30  # the container is killed after this
SANDBOX_MEMORY = "256m"
SANDBOX_PIDS = 64  # stops fork bombs
MAX_TEST_DETAILS = 8  # failing tests reported back per run

# --- Fix loop ---
FIX_MAX_ATTEMPTS = 3  # LoopAgent max_iterations: each attempt is one fixer call + one free check

# --- Review memory (stored in `user:` state, so it survives across sessions) ---
HISTORY_SIZE = 5  # past reviews kept per user
