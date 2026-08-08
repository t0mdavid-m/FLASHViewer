"""Workspace names reach us from a URL parameter and a sidebar text box.

Both are joined onto the workspaces directory; the text box's value is then
rmtree'd by "Delete Workspace". An absolute path replaces the prefix outright
and ".." walks out of it, so either would delete a directory the user never
named. Guards that, plus the empty value that used to resolve to the workspaces
directory itself and raise ValueError in render_sidebar.

Run: python3 tests/test_workspace_name.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.common import valid_workspace_name  # noqa: E402


def main():
    root = Path("..", "workspaces-FLASHViewer")

    # Rejected: every one of these would have escaped the workspaces directory.
    for bad in ("", "   ", ".", "..", "../..", "../../etc",
                "/Users/me/Documents", "/", "a/b", "a\\b", ".hidden", None):
        assert valid_workspace_name(bad) == "", repr(bad)

    # Accepted: ordinary names.
    for good in ("default", "my-run", "run_2026", "AB12", "a b"):
        assert valid_workspace_name(good) == good, good

    # Whatever survives must stay inside the workspaces directory.
    for candidate in ("", "..", "../..", "/etc", "a/b", "default", "my-run", ".hidden"):
        name = valid_workspace_name(candidate) or "default"
        resolved = (root / name).resolve()
        assert root.resolve() in resolved.parents, candidate

    # The specific shape of the data-loss bug: an absolute path must never
    # survive the join.
    assert (root / (valid_workspace_name("/Users/me/Documents") or "default")).resolve() \
        != Path("/Users/me/Documents")

    print("workspace names: all checks passed")


if __name__ == "__main__":
    main()
