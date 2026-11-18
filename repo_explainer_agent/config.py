"""Every cost and safety limit in one place, so they're easy to find and tune."""

# --- The ADK agent that talks to the user ---
AGENT_MODEL = "gemini-3.5-flash-lite"  # it only chats and presents reports, so the cheapest model is enough

# --- Repo download limits ---
MAX_REPO_SIZE_MB = 50  # refuse bigger repos before downloading (GitHub reports size for free)
CLONE_TIMEOUT_S = 90  # give up if `git clone` takes longer than this

# --- Gemini CLI limits ---
CLI_MODEL = "gemini-3.5-flash-lite"  # cheapest current model
CLI_TIMEOUT_S = 240  # kill Gemini CLI if a run takes longer than 4 minutes
CLI_MAX_TURNS = 12  # max model calls per run; each one costs about 10K tokens of overhead
CLI_MAX_FILES_TO_READ = 8  # asked for in the prompt so it finishes well before the turn cap

# --- Pricing for the cost estimate (USD per 1M tokens, gemini-3.5-flash-lite paid tier) ---
PRICE_INPUT_PER_M = 0.30  # cached tokens are cheaper, so this gives an upper-bound estimate
PRICE_OUTPUT_PER_M = 2.50  # output and "thinking" tokens

# --- Repo map (the free summary built in plain Python) ---
MAP_MAX_TREE_LINES = 120  # keep the folder tree short
MAP_README_LINES = 40  # only the start of the README

# folders and files that are noise for understanding a codebase
IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
    "target", ".next", ".idea", ".vscode", "vendor", "coverage", ".pytest_cache", ".mypy_cache",
}
IGNORED_SUFFIXES = {
    ".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".gz",
    ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".min.js", ".map", ".pyc", ".db", ".sqlite",
}
IGNORED_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock"}

# files that tell you the most about a project, checked by name
KEY_FILES = {
    "README.md", "README.rst", "README", "requirements.txt", "pyproject.toml", "setup.py",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Dockerfile",
    "docker-compose.yml", "Makefile", "main.py", "app.py", "manage.py", "index.js", "server.js",
}
