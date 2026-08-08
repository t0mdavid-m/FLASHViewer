"""The hosted deployment has no other coverage, and that cost us a Blocker.

captcha_control() is skipped unless settings.json sets online_deployment, so
local and desktop never execute its body. Deleting dead code from that module
took three module-level constants with it and left a NameError that only the
hosted deployment could ever hit — invisible to every existing test and to
manual desktop testing.

This checks the module's names resolve without needing a Streamlit runtime.

Run: python3 tests/test_hosted_mode.py
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


def undefined_globals(path):
    """Names a module reads at runtime but never binds, ignoring builtins.

    Deliberately static: importing the module needs a Streamlit script context.
    """
    tree = ast.parse(Path(path).read_text())
    bound = set(dir(__builtins__)) | set(vars(__builtins__)) if hasattr(
        __builtins__, "__dict__") else set(dir(__builtins__))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            pass

    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return sorted(used - bound)


def main():
    # The module that broke, plus the ones only the hosted path exercises.
    for rel in ("src/common/captcha_.py", "src/common/common.py"):
        missing = undefined_globals(REPO / rel)
        check(f"{rel} has no undefined names", missing == [], str(missing))

    # The three constants specifically: their absence was the Blocker.
    text = (REPO / "src/common/captcha_.py").read_text()
    for name in ("length_captcha", "width", "height"):
        check(f"captcha_.py defines {name}", f"\n{name} = " in text)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
