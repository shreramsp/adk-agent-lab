"""Runs untrusted code + generated unit tests inside a locked-down, throw-away Docker container.

The code under review comes from a chat message, so it is untrusted: it could delete files, read
~/.ssh, or call the internet. It never runs on this machine directly. Each run gets a fresh container
with no network, a read-only filesystem, no Linux capabilities, a non-root user, and limits on memory,
CPU, processes, and time. The container is deleted afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any

from . import config

# Runs INSIDE the container. It imports the tests, runs them with unittest, and prints one JSON
# line that starts with a random marker, so output printed by the code under test can't be mistaken
# for the result.
_RUNNER = r'''
import io, json, sys, unittest
sys.path.insert(0, "/work")
marker = sys.argv[1]
real_out = sys.__stdout__

class _Capped(io.StringIO):
    """Keeps at most 64 KB of whatever the code prints, so it can't flood the host."""
    def write(self, s):
        return super().write(s) if self.tell() < 65536 else len(s)

sys.stdout = sys.stderr = _Capped()

def emit(data):
    real_out.write("\n" + marker + json.dumps(data) + "\n")
    real_out.flush()

def last_lines(tb, n=3):
    return "\n".join(tb.strip().splitlines()[-n:])[:400]

try:
    suite = unittest.defaultTestLoader.loadTestsFromName("test_solution")
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0, buffer=True).run(suite)
except BaseException as e:  # also catches SystemExit raised by the code under test
    emit({"load_error": (type(e).__name__ + ": " + str(e))[:400]})
    raise SystemExit(0)

details = ([{"test": t.id().split(".", 1)[-1], "outcome": "failed", "message": last_lines(tb)} for t, tb in result.failures]
           + [{"test": t.id().split(".", 1)[-1], "outcome": "error", "message": last_lines(tb)} for t, tb in result.errors])
emit({"total": result.testsRun, "failed": len(result.failures), "errors": len(result.errors),
      "skipped": len(result.skipped), "details": details})
'''


def strip_fences(text: str) -> str:
    """Model output often comes wrapped in ```python ... ```; keep only the code."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip("\n") + "\n"


def sandbox_problem() -> str | None:
    """None if Docker and the sandbox image are ready, otherwise a short explanation."""
    if not shutil.which("docker"):
        return "Docker is not installed, so tests can't be run safely."
    try:
        r = subprocess.run(["docker", "image", "inspect", config.SANDBOX_IMAGE],
                           capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return "Docker is not responding (is Docker Desktop running?)."
    if r.returncode != 0:
        return f"The sandbox image is missing. Run: docker pull {config.SANDBOX_IMAGE}"
    return None


def run_tests(code: str, tests: str) -> dict[str, Any]:
    """Run `tests` (a unittest module that does `from solution import ...`) against `code`.

    Returns a dict with `status` = ok | no_tests | load_error | timeout | crashed | sandbox_unavailable,
    and for `ok`: total, passed, failed, errors, details (failing tests only).
    """
    if problem := sandbox_problem():
        return {"status": "sandbox_unavailable", "message": problem}
    if "def test" not in tests:
        return {"status": "no_tests", "message": "No unittest test methods were generated."}

    work = tempfile.mkdtemp(prefix="code-review-")
    name = f"code-review-{uuid.uuid4().hex[:12]}"
    marker = f"@@RESULT-{uuid.uuid4().hex}@@"
    try:
        for fname, body in (("solution.py", code), ("test_solution.py", tests), ("_runner.py", _RUNNER)):
            path = os.path.join(work, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            os.chmod(path, 0o644)  # readable by the container's unprivileged user
        os.chmod(work, 0o755)

        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",                      # no internet, no access to local services
            "--read-only", "--tmpfs", "/tmp:rw,size=16m",  # can't write anywhere except a small /tmp
            "--memory", config.SANDBOX_MEMORY, "--memory-swap", config.SANDBOX_MEMORY,
            "--cpus", "1", "--pids-limit", str(config.SANDBOX_PIDS),
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534",                  # "nobody", not root
            "-v", f"{work}:/work:ro", "-w", "/tmp",   # the code itself is mounted read-only
            config.SANDBOX_IMAGE,
            "python", "-I", "-B", "/work/_runner.py", marker,  # -I: ignore env vars and user site-packages
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.SANDBOX_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return {"status": "timeout",
                    "message": f"Tests did not finish in {config.SANDBOX_TIMEOUT_S} s (infinite loop or very slow code)."}

        line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith(marker)), None)
        if line is None:
            tail = (proc.stderr or proc.stdout or "").strip()[-400:]
            return {"status": "crashed", "message": f"The test process died before reporting (exit {proc.returncode}). {tail}"}
        data = json.loads(line[len(marker):])
        if "load_error" in data:
            return {"status": "load_error", "message": data["load_error"]}
        data["passed"] = data["total"] - data["failed"] - data["errors"] - data["skipped"]
        data["details"] = data["details"][: config.MAX_TEST_DETAILS]
        data["status"] = "ok" if data["total"] else "no_tests"
        return data
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_report(r: dict[str, Any]) -> str:
    """Plain-text summary of `run_tests()` for prompts and status lines."""
    if r.get("status") != "ok":
        return f"Tests not run ({r.get('status')}): {r.get('message', '')}"
    head = f"{r['passed']}/{r['total']} tests passed"
    if r["failed"] or r["errors"]:
        head += f" ({r['failed']} failed, {r['errors']} errors)"
    rows = "\n".join(f"- {d['outcome'].upper()} {d['test']}: {d['message']}" for d in r["details"])
    return head + ("\n" + rows if rows else "")
