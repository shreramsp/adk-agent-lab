"""The non-AI steps of the pipelines: custom ADK agents written in plain Python.

A custom agent subclasses BaseAgent and implements `_run_async_impl`. It can read session state,
do any work in code, and yield Events: an Event can show a message, write to state (`state_delta`),
stop a LoopAgent (`escalate=True`), and stop a Pipeline early (`halt=True` in state).
These steps cost nothing and give the same result every time, so every exact job (parsing, style,
security, running tests, deciding whether a fix is good enough) lives here, not in a prompt.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from . import analysis, config, sandbox

HISTORY_KEY = "user:review_history"  # `user:` prefix = kept for this user across all sessions


def _event(ctx: InvocationContext, author: str, text: str | None = None,
           delta: dict[str, Any] | None = None, escalate: bool | None = None) -> Event:
    return Event(
        invocation_id=ctx.invocation_id,
        author=author,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(text=text)]) if text else None,
        actions=EventActions(state_delta=delta or {}, escalate=escalate),
    )


def _issue_types(a: dict[str, Any]) -> set[str]:
    """The kinds of problems in one review (style codes + security rules), for spotting repeats."""
    if not a or a.get("syntax_error"):
        return set()
    return set(a["style"]["by_code"]) | {s["rule"] for s in a["security"]} | (
        {"too-complex"} if a["metrics"]["complex_functions"] else set())


def _history_note(history: list[dict[str, Any]], current_types: set[str]) -> str:
    """Plain-text summary of this user's past reviews for the feedback writer."""
    if not history:
        return "This is the user's first review. Do not write a progress section."
    styles = " -> ".join(str(h["style_score"]) for h in history)
    security = " -> ".join(str(h["security_total"]) for h in history)
    counts = Counter(t for h in history for t in h.get("issue_types", []))
    repeats = [f"{t} (seen in {n} earlier reviews)" for t, n in counts.most_common() if t in current_types]
    return (f"{len(history)} earlier review(s), oldest first. Style scores: {styles}. "
            f"Security findings: {security}. "
            f"Problems that appear again in this code: {', '.join(repeats[:5]) or 'none'}.")


class Pipeline(BaseAgent):
    """Runs its sub-agents in order, like SequentialAgent, but stops as soon as a step writes
    `halt=True` to state. (A step can't stop its siblings with `ctx.end_invocation`: every agent runs
    on its own copy of the invocation context, so the flag never reaches the parent. State is shared.)
    The first step of each pipeline always writes `halt`, so an old value is never reused."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        for agent in self.sub_agents:
            async for event in agent.run_async(ctx):
                yield event
            if ctx.session.state.get("halt"):
                return


# ----------------------------------------------------------------------------------------------
# Review pipeline
# ----------------------------------------------------------------------------------------------

class StaticAnalyzer(BaseAgent):
    """Step 1: take the code from the user's message and run every static check (AST structure,
    complexity, security, PEP 8 style). Ends the run early when there is no usable code."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        text = "".join(p.text or "" for p in (ctx.user_content.parts if ctx.user_content else []))
        code = analysis.extract_code(text)

        stop = None
        if not code:
            stop = "I couldn't find any Python code in that message. Paste it, ideally inside ```python ... ```."
        elif len(code.splitlines()) > config.MAX_CODE_LINES:
            stop = (f"That's {len(code.splitlines())} lines; I review up to {config.MAX_CODE_LINES} lines "
                    "at a time to keep cost down. Send one module or a few functions.")
        if stop:
            yield _event(ctx, self.name, stop, delta={"halt": True})  # Pipeline stops: no model calls wasted
            return

        a = analysis.analyze(code)
        if a["syntax_error"]:
            yield _event(ctx, self.name,
                         f"⛔ Syntax error at {a['syntax_error']}. The code has to parse before I can check "
                         "its structure, style, and security or run tests on it. Fix that line and send it again.",
                         delta={"code": code, "fix_ready": False, "halt": True})
            return

        history = ctx.session.state.get(HISTORY_KEY, [])
        m = a["metrics"]
        yield _event(
            ctx, self.name,
            f"🔍 Static analysis: style {m['style_score']}/100 · security findings {m['security_total']} "
            f"({m['security_high']} high) · complex functions {m['complex_functions']}",
            delta={
                "code": code,
                "analysis": a,
                "metrics": m,
                "analysis_report": analysis.analysis_report(a),
                "history_note": _history_note(history, _issue_types(a)),
                # reset everything from an earlier review in this session
                "tests": "", "test_results": {}, "test_report": "Tests not run yet.",
                "fix_ready": False,
                "halt": False,
            },
        )


class TestRunner(BaseAgent):
    """Step 3: run the tests the test writer produced against the code, inside the Docker sandbox."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        tests = sandbox.strip_fences(state.get("tests", ""))
        if "NO_TESTS" in tests[:40]:
            r = {"status": "no_tests", "message": "The code has nothing testable (no functions or classes)."}
        else:
            # subprocess + Docker is blocking work, so run it in a thread and keep the server responsive
            r = await asyncio.to_thread(sandbox.run_tests, state["code"], tests)
        report = sandbox.test_report(r)
        yield _event(ctx, self.name, f"🧪 Sandbox (Docker, no network): {report.splitlines()[0]}",
                     delta={"tests": tests, "test_results": r, "test_report": report})


def remember_review(callback_context: CallbackContext) -> None:
    """after_agent_callback on the feedback writer: save a short record of this review in `user:`
    state, so the next review (even in a new session) can mention progress and repeated mistakes."""
    state = callback_context.state
    a, m, r = state.get("analysis"), state.get("metrics"), state.get("test_results") or {}
    if not a or not m:
        return None
    entry = {
        "date": date.today().isoformat(),
        "style_score": m["style_score"],
        "security_total": m["security_total"],
        "tests": f"{r['passed']}/{r['total']}" if r.get("status") == "ok" else "n/a",
        "issue_types": sorted(_issue_types(a)),
    }
    history = list(state.get(HISTORY_KEY, [])) + [entry]
    state[HISTORY_KEY] = history[-config.HISTORY_SIZE:]
    state["fix_ready"] = True  # a review exists, so "fix it" is now possible
    return None


# ----------------------------------------------------------------------------------------------
# Fix pipeline
# ----------------------------------------------------------------------------------------------

def _needs_fixing(m: dict[str, Any], r: dict[str, Any]) -> bool:
    tests_failing = r.get("status") == "ok" and r["passed"] < r["total"]
    return bool(m["security_total"] or m["complex_functions"] or m["style_score"] < 100 or tests_failing)


class FixSetup(BaseAgent):
    """Before the loop: check there is a reviewed piece of code and remember its scores as the
    baseline that every fix attempt is compared against."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        m, r = state.get("metrics"), state.get("test_results") or {}
        stop = None
        if not state.get("fix_ready") or not m:
            stop = "There's no reviewed code to fix yet. Send me some Python code and I'll review it first."
        elif not _needs_fixing(m, r):
            stop = "Nothing to fix: no security findings, no overly complex functions, full style score, and all tests pass."
        if stop:
            yield _event(ctx, self.name, stop, delta={"halt": True})
            return
        yield _event(ctx, self.name, f"🔧 Fixing (up to {config.FIX_MAX_ATTEMPTS} attempts). Baseline: "
                     f"{analysis.metrics_line(m)}, tests {r.get('passed', '-')}/{r.get('total', '-')}.",
                     delta={"halt": False, "fix_baseline": {"metrics": m, "tests": r}, "fix_attempt": 0,
                            "fix_feedback": "This is the first attempt.", "fix_best": None,
                            "fixed_code": "", "fix_summary": ""})


class FixChecker(BaseAgent):
    """Inside the loop, after the fixer: re-check and re-test the new code, then decide in code
    (not by asking a model) whether the fix is good enough. Accepted = all tests pass AND style is
    not worse AND no security finding is new or left at high AND no new complex functions.
    Accepted -> escalate=True ends the LoopAgent. Otherwise the problems become the next prompt."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        attempt = state.get("fix_attempt", 0) + 1
        base_m = state["fix_baseline"]["metrics"]
        base_t = state["fix_baseline"]["tests"]
        code = analysis.extract_code(state.get("fixed_code_raw", "")) or sandbox.strip_fences(state.get("fixed_code_raw", ""))
        a = analysis.analyze(code)

        problems: list[str] = []
        r: dict[str, Any] = {}
        m = a["metrics"]
        if a["syntax_error"]:
            problems.append(f"The new code has a syntax error at {a['syntax_error']}.")
        else:
            if base_t.get("status") == "ok":
                r = await asyncio.to_thread(sandbox.run_tests, code, state["tests"])
                if r.get("status") != "ok" or r["passed"] < r["total"]:
                    problems.append("Not all tests pass: " + sandbox.test_report(r))
            if m["style_score"] < base_m["style_score"]:
                problems.append(f"Style got worse: {m['style_score']} < {base_m['style_score']}.")
            if m["security_total"] > base_m["security_total"] or m["security_high"] > 0:
                left = "; ".join(f"line {s['line']} {s['rule']}" for s in a["security"])
                problems.append(f"Security findings remain ({m['security_total']}, {m['security_high']} high): {left}.")
            if m["complex_functions"] > base_m["complex_functions"]:
                problems.append("A function became more complex than the limit.")

        accepted = not problems
        tests_txt = f"{r['passed']}/{r['total']}" if r.get("status") == "ok" else "n/a"
        record = {"attempt": attempt, "accepted": accepted, "metrics": m, "tests": tests_txt, "code": code,
                  "problems": problems}

        # keep the best attempt so far: most tests passing, then fewest high/total findings, then style
        def rank(rec: dict[str, Any]) -> tuple:
            mm = rec["metrics"] or {"security_high": 99, "security_total": 99, "style_score": 0}
            passed = int(rec["tests"].split("/")[0]) if rec["tests"] != "n/a" else 0
            return (rec["accepted"], passed, -mm["security_high"], -mm["security_total"], mm["style_score"])

        best = state.get("fix_best")
        if best is None or rank(record) > rank(best):
            best = record

        last = attempt >= config.FIX_MAX_ATTEMPTS
        mark = lambda ok: "✅" if ok else "❌"  # noqa: E731
        status = (f"🔁 Attempt {attempt}/{config.FIX_MAX_ATTEMPTS}: tests {tests_txt} "
                  f"{mark(not any(p.startswith('Not all tests') for p in problems))} · "
                  f"{analysis.metrics_line(m)} → {'accepted' if accepted else 'not yet'}")

        delta: dict[str, Any] = {"fix_attempt": attempt, "fix_best": best,
                                 "fix_feedback": "Your previous attempt was rejected because:\n- " + "\n- ".join(problems)
                                 if problems else ""}
        if accepted or last:
            bm = best["metrics"]
            delta["fixed_code"] = best["code"]
            delta["fix_summary"] = (
                f"Result: {'ACCEPTED' if best['accepted'] else 'NOT FULLY FIXED'} after {attempt} attempt(s).\n"
                f"Before: {analysis.metrics_line(base_m)}, tests "
                f"{base_t.get('passed', 'n/a')}/{base_t.get('total', 'n/a')}.\n"
                f"After:  {analysis.metrics_line(bm)}, tests {best['tests']}.\n"
                + ("" if best["accepted"] else f"Best was attempt {best['attempt']}. Still open:\n- " + "\n- ".join(best["problems"]))
            )
        yield _event(ctx, self.name, status, delta=delta, escalate=True if accepted else None)
