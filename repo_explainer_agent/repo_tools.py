"""The repo-analysis tool: download a GitHub repo safely, summarize it for free, then let
Gemini CLI read the important parts (read-only, capped) and write a report."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config

# GitHub's rules for owner and repo names; anything else is rejected
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


# accept only https://github.com/<owner>/<repo>[...], return (owner, repo)
def validate_github_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Only https://github.com/<owner>/<repo> links are supported.")
    if parsed.params:  # a ';...' part never appears in real GitHub links (e.g. 'repo;rm -rf ~')
        raise ValueError("That link has unexpected characters; paste the plain repo link.")
    parts = [p for p in parsed.path.split("/") if p]  # extra parts like /tree/main are ignored
    if len(parts) < 2:
        raise ValueError("The link must include both the owner and the repo name.")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not (_OWNER_RE.match(owner) and _REPO_RE.match(repo)) or repo in {".", ".."}:
        raise ValueError("That doesn't look like a valid GitHub owner/repo name.")
    return owner, repo


# free GitHub API call: size, language, stars - lets us refuse huge repos before downloading
def check_repo_size(owner: str, repo: str) -> dict:
    try:
        response = httpx.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=10)
    except httpx.HTTPError:
        return {"size_mb": None}  # network hiccup: carry on, the clone timeout still protects us
    if response.status_code == 404:
        raise ValueError("Repo not found. It may be private or misspelled.")
    if response.status_code != 200:  # e.g. GitHub's 60-requests/hour limit without login
        return {"size_mb": None}
    data = response.json()
    info = {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "language": data.get("language"),
        "stars": data.get("stargazers_count"),
        "size_mb": round(data.get("size", 0) / 1024, 1),  # GitHub reports size in KB
    }
    if info["size_mb"] > config.MAX_REPO_SIZE_MB:
        raise ValueError(f"Repo is {info['size_mb']} MB; the limit is {config.MAX_REPO_SIZE_MB} MB.")
    return info


# shallow clone (latest commit only) into a fresh temp folder; returns its path
def clone_repo(owner: str, repo: str) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="repo_explainer_"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--no-tags", "--quiet",
             f"https://github.com/{owner}/{repo}.git", str(dest)],
            # GIT_TERMINAL_PROMPT=0: fail instead of asking for a password on private repos
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True, text=True, timeout=config.CLONE_TIMEOUT_S, check=True,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"Download took longer than {config.CLONE_TIMEOUT_S}s.")
    except subprocess.CalledProcessError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"git clone failed: {e.stderr.strip()[:200]}")
    return dest


# remove anything in the download that could change how Gemini CLI behaves, then add our limits
def lock_down_clone(root: Path) -> list[str]:
    removed = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        name = path.name
        # symlinks could point outside the folder (e.g. to ~/.ssh) - delete them all
        # .env*       -> Gemini CLI loads it automatically (could swap the API key or settings)
        # .gemini/    -> its settings.json can start extra programs (MCP servers)
        # GEMINI.md   -> extra instructions Gemini CLI reads automatically (prompt injection)
        if path.is_symlink() or name.startswith(".env") or name in {".gemini", "GEMINI.md", ".geminiignore"}:
            removed.append(str(path.relative_to(root)))
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    shutil.rmtree(root / ".git", ignore_errors=True)  # git history isn't needed for a review

    # our own ignore list: Gemini CLI won't read or list these
    ignore_lines = [f"{d}/" for d in sorted(config.IGNORED_DIRS)]
    ignore_lines += [f"*{s}" for s in sorted(config.IGNORED_SUFFIXES)] + sorted(config.IGNORED_FILES)
    (root / ".geminiignore").write_text("\n".join(ignore_lines) + "\n")

    # our own settings: a hard cap on model calls per run (each call costs ~10K tokens)
    (root / ".gemini").mkdir()
    settings = {"model": {"maxSessionTurns": config.CLI_MAX_TURNS}}
    (root / ".gemini" / "settings.json").write_text(json.dumps(settings))
    return [r for r in removed if not r.startswith(".git/")]


def _is_ignored(path: Path) -> bool:
    return path.name in config.IGNORED_FILES or any(path.name.endswith(s) for s in config.IGNORED_SUFFIXES)


# free summary of the repo in plain Python: tree, languages, key files, README start
def build_repo_map(root: Path) -> dict:
    tree, key_files, by_ext = [], [], Counter()
    total_files = total_lines = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # prune noise folders and our own .gemini/ so os.walk never enters them
        dirnames[:] = sorted(d for d in dirnames if d not in config.IGNORED_DIRS and d != ".gemini")
        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        if depth and depth <= 3 and len(tree) < config.MAP_MAX_TREE_LINES:
            tree.append("  " * (depth - 1) + f"{rel_dir.name}/")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if _is_ignored(path) or name == ".geminiignore":
                continue
            total_files += 1
            by_ext[path.suffix or name] += 1
            if path.stat().st_size < 1_000_000:  # count lines only in normal-sized files
                total_lines += path.read_bytes().count(b"\n")
            if name in config.KEY_FILES:
                key_files.append(str(path.relative_to(root)))
            if depth < 3 and len(tree) < config.MAP_MAX_TREE_LINES:
                tree.append("  " * depth + name)

    readme = next((root / k for k in ("README.md", "README.rst", "README") if (root / k).is_file()), None)
    readme_start = ""
    if readme:
        readme_start = "\n".join(readme.read_text(errors="ignore").splitlines()[: config.MAP_README_LINES])

    return {
        "total_files": total_files,
        "total_lines": total_lines,
        "top_file_types": dict(by_ext.most_common(8)),
        "key_files": key_files[:30],
        "tree": "\n".join(tree),
        "readme_start": readme_start,
    }


# run Gemini CLI read-only in the repo folder; return its answer plus token usage and cost
def run_gemini_cli(prompt: str, cwd: Path) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"status": "error", "message": "No Gemini API key found in the environment."}
    # clean environment: only what Gemini CLI needs, so no other secrets leak in
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GEMINI_API_KEY": api_key}
    cmd = [
        "gemini", "-p", prompt,
        "-m", config.CLI_MODEL,
        "--approval-mode", "plan",  # read-only: can read and search, can't edit or run commands
        "--skip-trust",  # OK only because lock_down_clone() already removed risky files
        "-o", "json",  # machine-readable output that includes token stats
    ]
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                                timeout=config.CLI_TIMEOUT_S)
    except FileNotFoundError:
        return {"status": "error", "message": "Gemini CLI is not installed (npm install -g @google/gemini-cli)."}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Gemini CLI took longer than {config.CLI_TIMEOUT_S}s."}

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": (result.stderr or result.stdout).strip()[-300:]}
    if result.returncode != 0 or "error" in output:
        error = output.get("error", {})
        message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        return {"status": "error", "message": message[:300] or result.stderr.strip()[-300:]}

    # add up tokens across every model call Gemini CLI made
    prompt_tokens = output_tokens = requests = 0
    for model_stats in output.get("stats", {}).get("models", {}).values():
        tokens = model_stats.get("tokens", {})
        prompt_tokens += tokens.get("prompt", 0)
        output_tokens += tokens.get("candidates", 0) + tokens.get("thoughts", 0)
        requests += model_stats.get("api", {}).get("totalRequests", 0)
    files_read = output.get("stats", {}).get("tools", {}).get("byName", {}).get("read_file", {}).get("count", 0)
    cost = (prompt_tokens * config.PRICE_INPUT_PER_M + output_tokens * config.PRICE_OUTPUT_PER_M) / 1_000_000
    return {
        "status": "success",
        "report": output.get("response", ""),
        "usage": {
            "model_calls": requests,
            "files_read": files_read,
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": round(cost, 4),  # upper bound (treats cached tokens as full price)
        },
    }


def _build_prompt(repo_map: dict, focus: str) -> str:
    # the free map goes first so Gemini CLI doesn't spend turns rediscovering the structure
    focus_line = f"The user especially wants to know about: {focus}\n" if focus else ""
    return (
        "You are reviewing the code repository in the current folder.\n"
        "A free summary of the repo is below. Use it instead of listing folders yourself.\n\n"
        f"Files: {repo_map['total_files']}, lines: {repo_map['total_lines']}, "
        f"top file types: {repo_map['top_file_types']}\n"
        f"Key files: {repo_map['key_files']}\n"
        f"Folder tree:\n{repo_map['tree']}\n\n"
        f"README (start):\n{repo_map['readme_start']}\n\n"
        f"{focus_line}"
        "Write a report with these sections:\n"
        "1. What it does (2-3 sentences)\n"
        "2. Architecture: the main components and how they connect\n"
        "3. How to run it\n"
        "4. Top 5 risks or issues (bugs, security, missing tests, outdated dependencies), "
        "each with the file path\n\n"
        f"Rules: read at most {config.CLI_MAX_FILES_TO_READ} files, picking the most important "
        "ones from the summary. Never read lock files, generated files, or tests unless asked. "
        "Keep the report under 500 words and finish in as few steps as possible."
    )


def _analyze(repo_url: str, focus: str) -> dict:
    try:
        owner, repo = validate_github_url(repo_url)  # 
        github_info = check_repo_size(owner, repo)  # 
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    root = None
    try:
        root = clone_repo(owner, repo)  # 
        removed = lock_down_clone(root)  # 
        repo_map = build_repo_map(root)  # 
        result = run_gemini_cli(_build_prompt(repo_map, focus), root)  # 
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)  # always delete the downloaded copy

    result["repo"] = {**github_info, "files": repo_map["total_files"], "lines": repo_map["total_lines"]}
    result["removed_for_safety"] = removed
    return result


# THE tool the ADK agent will call. The docstring is what Gemini reads to decide when to use it.
async def analyze_github_repo(repo_url: str, focus: str = "") -> dict:
    """Downloads a public GitHub repository and writes a code review report: what it does,
    its architecture, how to run it, and the top 5 risks or issues.

    Args:
        repo_url: A public GitHub link, e.g. 'https://github.com/owner/repo'.
        focus: Optional topic to look at more closely, e.g. 'security' or 'the API layer'.
    """
    # the work blocks for minutes, so run it in a thread to keep adk web responsive
    return await asyncio.to_thread(_analyze, repo_url, focus)
