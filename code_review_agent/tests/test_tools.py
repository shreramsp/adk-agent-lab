"""Unit tests for the non-AI parts (free, no API key needed).

Run from the repository root:
    python -m unittest discover -s code_review_agent/tests -t . -v
Sandbox tests are skipped when Docker or the sandbox image is not available.
"""

import unittest

from code_review_agent import analysis, sandbox

INSECURE = '''import os, pickle, subprocess, yaml, hashlib, requests
API_KEY = "sk-live-1234567890"

def run(cmd):
    os.system(cmd)
    subprocess.run(cmd, shell=True)
    eval(cmd)

def load(path):
    try:
        return pickle.loads(open(path, "rb").read()), yaml.load(open(path))
    except:
        return None

def fetch(url):
    return requests.get(url, verify=False), hashlib.md5(b"x"), connect(password="hunter22")
'''

CLEAN = '''"""A tidy module."""
import os


def average(nums):
    """Return the mean of nums, or 0 for an empty list."""
    if not nums:
        return 0
    return sum(nums) / len(nums)


TOKEN = os.environ.get("TOKEN", "")
'''


class ExtractCodeTest(unittest.TestCase):
    def test_fenced_block(self):
        self.assertEqual(analysis.extract_code("look:\n```python\nx = 1\n```\nthanks"), "x = 1")

    def test_largest_of_several_blocks(self):
        msg = "```\na = 1\n```\nand\n```python\ndef f():\n    return 2\n```"
        self.assertIn("def f()", analysis.extract_code(msg))

    def test_unfenced_code_after_text(self):
        self.assertEqual(analysis.extract_code("please check\ndef f(x):\n    return x"), "def f(x):\n    return x")

    def test_no_code(self):
        self.assertIsNone(analysis.extract_code("What can you do?"))


class SecurityTest(unittest.TestCase):
    def test_every_rule_fires(self):
        rules = {f["rule"] for f in analysis.analyze(INSECURE)["security"]}
        self.assertEqual(rules, {"hardcoded-secret", "shell-command", "shell-true", "eval-exec",
                                 "unsafe-deserialize", "yaml-load", "bare-except", "tls-verify-off", "weak-hash"})

    def test_high_findings_come_first(self):
        sev = [f["severity"] for f in analysis.analyze(INSECURE)["security"]]
        self.assertEqual(sev, sorted(sev, key={"high": 0, "medium": 1, "low": 2}.get))

    def test_safe_code_has_no_findings(self):
        self.assertEqual(analysis.analyze(CLEAN)["security"], [])

    def test_secret_hidden_in_env_fallback(self):
        for code in ('import os\nAPI_KEY = os.environ.get("API_KEY", "sk-live-1234567890")\n',
                     'import os\nTOKEN = os.getenv("TOKEN", default="abcd1234")\n',
                     'import os\npassword = os.getenv("PW") or "hunter22"\n'):
            rules = [f["rule"] for f in analysis.analyze(code)["security"]]
            self.assertEqual(rules, ["hardcoded-secret"], code)

    def test_env_without_default_is_fine(self):
        code = 'import os\nAPI_KEY = os.environ["API_KEY"]\nTOKEN = os.getenv("TOKEN", "")\n'
        self.assertEqual(analysis.analyze(code)["security"], [])

    def test_safe_yaml_loader_is_fine(self):
        code = "import yaml\ndata = yaml.load(open('f'), Loader=yaml.SafeLoader)\n"
        self.assertEqual(analysis.analyze(code)["security"], [])


class ComplexityTest(unittest.TestCase):
    def test_counts_branches_and_boolean_operators(self):
        code = ("def f(a, b):\n    if a and b:\n        return 1\n    for x in a:\n"
                "        if x:\n            continue\n    return [y for y in b if y]\n")
        (fn,) = analysis.analyze(code)["complexity"]
        # 1 + if + and + for + if + comprehension + its if = 7
        self.assertEqual(fn["complexity"], 7)
        self.assertEqual(fn["rating"], "moderate")

    def test_straight_line_function_is_simple(self):
        (fn,) = analysis.analyze("def f():\n    return 1\n")["complexity"]
        self.assertEqual((fn["complexity"], fn["rating"]), (1, "simple"))


class StyleTest(unittest.TestCase):
    def test_clean_code_scores_100(self):
        self.assertEqual(analysis.analyze(CLEAN)["style"]["score"], 100)

    def test_issues_and_naming(self):
        style = analysis.analyze("def BadName( x ):\n    return x+1\nclass lower:\n    pass\n")["style"]
        self.assertIn("N802", style["by_code"])
        self.assertIn("N801", style["by_code"])
        self.assertLess(style["score"], 100)

    def test_missing_final_newline_is_not_an_issue(self):
        self.assertEqual(analysis.analyze(CLEAN.rstrip("\n"))["style"]["score"], 100)


class SyntaxErrorTest(unittest.TestCase):
    def test_reports_line_and_skips_metrics(self):
        a = analysis.analyze("def f(:\n    pass\n")
        self.assertTrue(a["syntax_error"].startswith("line 1"))
        self.assertIsNone(a["metrics"])


@unittest.skipIf(sandbox.sandbox_problem(), "Docker sandbox not available")
class SandboxTest(unittest.TestCase):
    TESTS = ("import unittest\nfrom solution import f\n"
             "class T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(f(), 1)\n")

    def test_pass_and_fail_are_counted(self):
        ok = sandbox.run_tests("def f():\n    return 1\n", self.TESTS)
        bad = sandbox.run_tests("def f():\n    return 2\n", self.TESTS)
        self.assertEqual((ok["status"], ok["passed"], ok["total"]), ("ok", 1, 1))
        self.assertEqual((bad["passed"], bad["failed"]), (0, 1))

    def test_filesystem_is_read_only(self):
        r = sandbox.run_tests("def f():\n    open('/work/x', 'w')\n    return 1\n", self.TESTS)
        self.assertIn("Read-only file system", r["details"][0]["message"])

    def test_network_is_blocked(self):
        code = ("import socket\ndef f():\n    socket.create_connection(('1.1.1.1', 53), timeout=2)\n    return 1\n")
        r = sandbox.run_tests(code, self.TESTS)
        self.assertEqual(r["passed"], 0)

    def test_exit_during_import_is_reported(self):
        r = sandbox.run_tests("import sys\nsys.exit(3)\n", self.TESTS)
        self.assertEqual(r["status"], "load_error")

    def test_fake_result_lines_are_ignored(self):
        code = "print('@@RESULT-fake@@{\"total\": 99}')\ndef f():\n    return 2\n"
        r = sandbox.run_tests(code, self.TESTS)
        self.assertEqual((r["total"], r["passed"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
