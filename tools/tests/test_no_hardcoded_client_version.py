"""No request code bakes in an App-Version or a /v12.x prefix any more (spec test 15).

Scans string constants with ast, so comments and docstrings - which legitimately record what
was measured - do not count. client_version.py holds the defaults and is the one exception.
"""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))
               + glob.glob(os.path.join(ROOT, "bot", "engine", "*.py")))
BAKED = re.compile(r"LGRGS/\d|^/v\d+\.\d+/")


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def test_no_string_in_request_code_carries_a_version_or_prefix():
    hits = []
    for path in FILES:
        if os.path.basename(path) == "client_version.py":
            continue
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and BAKED.search(node.value)):
                hits.append("%s:%d %r" % (os.path.relpath(path, ROOT), node.lineno, node.value[:60]))
    assert hits == []


def test_only_rangers_api_still_names_its_old_constants():
    users = []
    for path in FILES:
        if os.path.basename(path) == "rangers_api.py":
            continue
        with open(path, encoding="utf-8") as fh:
            if re.search(r"\bCLIENT_VERSION\b|rangers_api\.API\b", fh.read()):
                users.append(os.path.relpath(path, ROOT))
    assert users == []
