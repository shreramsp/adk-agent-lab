"""Static analysis in plain Python: no AI, no cost, and the same answer every time.

Everything here works on the AST (Abstract Syntax Tree): Python turns the source text into a tree of
nodes (FunctionDef, If, Call, ...), and we walk that tree to measure and check the code.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from typing import Any

import pycodestyle

from . import config

# ----------------------------------------------------------------------------------------------
# Getting the code out of a chat message
# ----------------------------------------------------------------------------------------------

_FENCE = re.compile(r"```[ \t]*(?:python|py|python3)?[ \t]*\n(.*?)```", re.S | re.I)
_CODE_START = re.compile(
    r"^\s*(def |async def |class |import |from \S+ import |@|if __name__|for |while |try:|with |"
    r"[A-Za-z_][\w.]*\s*(\[.*\])?\s*[+\-*/]?=)"
)


def extract_code(text: str) -> str | None:
    """Return the Python code in a message: the largest ``` block, or else everything from the first
    line that looks like code. None when there is no code."""
    blocks = _FENCE.findall(text or "")
    if blocks:
        return max(blocks, key=len).strip("\n") or None
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if _CODE_START.match(line):
            code = "\n".join(lines[i:]).strip("\n")
            return code if len(code.splitlines()) >= 2 or "def " in code else None
    return None


# ----------------------------------------------------------------------------------------------
# Structure: what is in the file
# ----------------------------------------------------------------------------------------------

def _structure(tree: ast.Module) -> dict[str, Any]:
    functions, classes, imports = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": len(node.args.args) + len(node.args.kwonlyargs),
                "lines": (node.end_lineno or node.lineno) - node.lineno + 1,
                "has_docstring": ast.get_docstring(node) is not None,
            })
        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "methods": [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                "has_docstring": ast.get_docstring(node) is not None,
            })
        elif isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or ".")
    return {"functions": functions, "classes": classes, "imports": sorted(set(imports))}


# ----------------------------------------------------------------------------------------------
# Complexity: how many paths through each function (cyclomatic complexity)
# ----------------------------------------------------------------------------------------------

_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.match_case)


def _cyclomatic(fn: ast.AST) -> int:
    """1 + one point per decision: if/for/while/except/ternary/case, each extra `and`/`or`,
    and each comprehension loop and its `if` filters."""
    score = 1
    for node in ast.walk(fn):
        if isinstance(node, _BRANCHES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
    return score


def _complexity(tree: ast.Module) -> list[dict[str, Any]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = _cyclomatic(node)
            rating = ("complex" if cc > config.COMPLEXITY_LIMIT
                      else "moderate" if cc > config.COMPLEXITY_WARN else "simple")
            out.append({"function": node.name, "line": node.lineno, "complexity": cc, "rating": rating})
    return sorted(out, key=lambda f: -f["complexity"])


# ----------------------------------------------------------------------------------------------
# Security: risky patterns found by looking at calls and assignments in the tree
# ----------------------------------------------------------------------------------------------

_SECRET_NAME = re.compile(r"(pass(word|wd)?|secret|api_?key|access_?key|private_?key|token|credential)", re.I)


def _dotted(node: ast.AST) -> str:
    """`os.path.join` -> "os.path.join"; `eval` -> "eval"; anything else -> ""."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_secret_literal(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 4


_ENV_READERS = ("os.environ.get", "environ.get", "os.getenv", "getenv")


def _has_secret_fallback(value: ast.AST | None) -> bool:
    """True for `os.environ.get("KEY", "sk-...")`, `os.getenv("KEY", default="sk-...")`, or
    `os.getenv("KEY") or "sk-..."`: the secret is still in the code, only moved into a default.
    (Seen in a real fix attempt: the fixer did exactly this, and the first version of this rule missed it.)"""
    if isinstance(value, ast.Call) and _dotted(value.func) in _ENV_READERS:
        default = value.args[1] if len(value.args) > 1 else _kw(value, "default")
        return _is_secret_literal(default)
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return any(_is_secret_literal(v) for v in value.values)
    return False


def _security(tree: ast.Module) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def add(rule: str, severity: str, node: ast.AST, message: str) -> None:
        found.append({"rule": rule, "severity": severity, "line": getattr(node, "lineno", 0), "message": message})

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            short = name.rsplit(".", 1)[-1]
            if name in ("eval", "exec"):
                add("eval-exec", "high", node, f"{name}() runs any string as code; never pass it user input.")
            elif name in ("os.system", "os.popen"):
                add("shell-command", "high", node, f"{name}() runs a shell command; use subprocess with a list of args.")
            elif name.startswith("subprocess.") and _is_true(_kw(node, "shell")):
                add("shell-true", "high", node, f"{name}(shell=True) allows shell injection; pass a list and drop shell=True.")
            elif name in ("pickle.load", "pickle.loads", "marshal.load", "marshal.loads", "shelve.open"):
                add("unsafe-deserialize", "medium", node, f"{name}() can run code hidden in the data; only load trusted data.")
            elif name in ("yaml.load", "yaml.load_all"):
                loader = _dotted(_kw(node, "Loader") or ast.Constant(None))
                if "Safe" not in loader:
                    add("yaml-load", "medium", node, "yaml.load without SafeLoader can build arbitrary objects; use yaml.safe_load.")
            elif short in ("get", "post", "put", "patch", "delete", "request") and name.startswith(("requests.", "httpx.")):
                if isinstance(_kw(node, "verify"), ast.Constant) and _kw(node, "verify").value is False:
                    add("tls-verify-off", "medium", node, f"{name}(verify=False) turns off HTTPS certificate checks.")
            elif name in ("hashlib.md5", "hashlib.sha1"):
                add("weak-hash", "low", node, f"{name} is broken for security uses (passwords, signatures); use sha256 or a password hash.")
            elif name == "tempfile.mktemp":
                add("insecure-tempfile", "medium", node, "tempfile.mktemp has a race condition; use NamedTemporaryFile or mkstemp.")
            for kw in node.keywords:  # e.g. connect(password="hunter2")
                if kw.arg and _SECRET_NAME.search(kw.arg) and _is_secret_literal(kw.value):
                    add("hardcoded-secret", "high", node, f"'{kw.arg}' is hard-coded; load it from an environment variable.")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                tname = _dotted(t)
                if not (tname and _SECRET_NAME.search(tname.rsplit(".", 1)[-1])):
                    continue
                if _is_secret_literal(node.value):
                    add("hardcoded-secret", "high", node, f"'{tname}' is hard-coded; load it from an environment variable.")
                elif _has_secret_fallback(node.value):
                    add("hardcoded-secret", "high", node,
                        f"'{tname}' falls back to a hard-coded secret; read it from the environment with no default.")
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            add("bare-except", "low", node, "bare `except:` also catches KeyboardInterrupt/SystemExit and hides bugs; catch specific errors.")
    return sorted(found, key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f["severity"]], f["line"]))


# ----------------------------------------------------------------------------------------------
# Style: PEP 8 via pycodestyle, plus PEP 8 naming via the AST
# ----------------------------------------------------------------------------------------------

class _Collect(pycodestyle.BaseReport):
    """A pycodestyle report that keeps the issues in a list instead of printing them."""

    def __init__(self, options):
        super().__init__(options)
        self.items: list[dict[str, Any]] = []

    def error(self, line_number, offset, text, check):
        code = super().error(line_number, offset, text, check)
        if code:
            self.items.append({"line": line_number, "code": text[:4], "message": text[5:]})
        return code


_SNAKE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*_{0,2}$")
_CAPWORDS = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")


def _naming(tree: ast.Module) -> list[dict[str, Any]]:
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _SNAKE.match(node.name):
            issues.append({"line": node.lineno, "code": "N802", "message": f"function name '{node.name}' should be snake_case"})
        elif isinstance(node, ast.ClassDef) and not _CAPWORDS.match(node.name):
            issues.append({"line": node.lineno, "code": "N801", "message": f"class name '{node.name}' should be CapWords"})
    return issues


def _style(code: str, tree: ast.Module | None) -> dict[str, Any]:
    guide = pycodestyle.StyleGuide(quiet=True, max_line_length=config.MAX_LINE_LENGTH)
    report = guide.init_report(_Collect)
    lines = code.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"  # pasted code often lacks the final newline; don't count that as an issue
    pycodestyle.Checker(filename="submitted.py", lines=lines, options=guide.options, report=report).check_all()
    issues = sorted(report.items + (_naming(tree) if tree else []), key=lambda i: i["line"])
    code_lines = max(1, sum(1 for ln in lines if ln.strip()))
    # Score: 100 minus issues per line of code. The +10 smooths short snippets: without it, a 4-line
    # function with 5 small issues scored 0/100 (seen in an eval run), which says nothing useful.
    score = max(0, 100 - round(100 * len(issues) / (code_lines + 10)))
    return {"score": score, "issue_count": len(issues), "issues": issues,
            "by_code": dict(Counter(i["code"] for i in issues).most_common())}


# ----------------------------------------------------------------------------------------------
# Everything at once, plus short text reports for the prompts
# ----------------------------------------------------------------------------------------------

def analyze(code: str) -> dict[str, Any]:
    """Run every static check. Returns the full results and a small `metrics` dict used to compare
    the original code with a fixed version."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"syntax_error": f"line {e.lineno}: {e.msg}", "metrics": None}

    security = _security(tree)
    complexity = _complexity(tree)
    style = _style(code, tree)
    structure = _structure(tree)
    metrics = {
        "style_score": style["score"],
        "security_total": len(security),
        "security_high": sum(1 for s in security if s["severity"] == "high"),
        "complex_functions": sum(1 for c in complexity if c["rating"] == "complex"),
        "max_complexity": max((c["complexity"] for c in complexity), default=0),
    }
    return {"syntax_error": None, "structure": structure, "complexity": complexity,
            "security": security, "style": style, "metrics": metrics}


def analysis_report(a: dict[str, Any]) -> str:
    """Compact plain-text summary of `analyze()` for an LLM prompt (no braces, so it is safe to
    inject into an ADK instruction)."""
    if a.get("syntax_error"):
        return f"SYNTAX ERROR at {a['syntax_error']}. Nothing else could be checked."
    s, m = a["structure"], a["metrics"]
    fn_list = ", ".join(
        f"{f['name']} (line {f['line']}, {f['args']} args{'' if f['has_docstring'] else ', no docstring'})"
        for f in s["functions"][:15]) or "none"
    cls_list = ", ".join(f"{c['name']} ({len(c['methods'])} methods)" for c in s["classes"][:10]) or "none"
    cx = "; ".join(f"{c['function']} = {c['complexity']} ({c['rating']})" for c in a["complexity"][:8]) or "no functions"
    sec = "\n".join(f"- [{x['severity'].upper()}] line {x['line']} {x['rule']}: {x['message']}"
                    for x in a["security"]) or "- none found"
    st = a["style"]
    style_lines = "\n".join(f"- line {i['line']} {i['code']} {i['message']}"
                            for i in st["issues"][:config.MAX_STYLE_ISSUES_SHOWN]) or "- none"
    more = st["issue_count"] - min(st["issue_count"], config.MAX_STYLE_ISSUES_SHOWN)
    return (
        f"Functions: {fn_list}\nClasses: {cls_list}\nImports: {', '.join(s['imports']) or 'none'}\n\n"
        f"Complexity per function (limit {config.COMPLEXITY_LIMIT}): {cx}\n\n"
        f"Security findings ({m['security_total']}, {m['security_high']} high):\n{sec}\n\n"
        f"Style score: {st['score']}/100 with {st['issue_count']} PEP 8 issues"
        f"{' (most common: ' + ', '.join(f'{k} x{v}' for k, v in list(st['by_code'].items())[:4]) + ')' if st['by_code'] else ''}:\n"
        f"{style_lines}{f'{chr(10)}- ... and {more} more' if more > 0 else ''}"
    )


def metrics_line(m: dict[str, Any] | None) -> str:
    if not m:
        return "syntax error"
    return (f"style {m['style_score']}/100, security {m['security_total']} ({m['security_high']} high), "
            f"complex functions {m['complex_functions']}")
