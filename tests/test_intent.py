"""Intent markers: the fix for the two signals that were wrong by default.

`upload_widget` auto-copies the example files whenever its directory is empty,
and `save_parameters()` runs on every widget render — so "input-files is
non-empty" and "params.json exists" are both true after one page load, before
the user has done anything. A wizard built on them reads Data done, Method done
on a virgin workspace.

Intent is therefore recorded where a user action actually happens, and read
back with three outcomes: recorded, absent-meaning-unknown, and unreadable.

Run: python3 tests/test_intent.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tools import (  # noqa: E402
    has_input, missing_references, read_intent, record_intent,
)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="flashapp-intent-"))
    try:
        wd = tmp / "flashdeconv"
        files_dir = wd / "input-files" / "mzML-files"
        files_dir.mkdir(parents=True)

        # The exact false-positive state: the auto-copy has put example files in
        # place, so has_input() is true — but the user has done nothing.
        (files_dir / "example_fd.mzML").write_bytes(b"x")
        check("auto-copied example files make has_input() true",
              has_input(files_dir))
        check("...but no intent is recorded, so status is UNKNOWN not done",
              read_intent(wd, "data") is None)

        # A real add records source and count.
        record_intent(wd, "data", source="reference", count=3)
        got = read_intent(wd, "data")
        check("a real add records source and count",
              got and got["source"] == "reference" and got["count"] == 3, str(got))
        check("and carries a timestamp", "at" in (got or {}))

        # Example-data loading is distinguishable from a deliberate choice.
        record_intent(wd, "data", source="example", count=1)
        check("example data is distinguishable from the user's own choice",
              read_intent(wd, "data")["source"] == "example")

        # Unreadable marker degrades to unknown rather than raising.
        (wd / "intent" / "data.json").write_text("{ not json")
        check("a corrupt marker reads as unknown, not an exception",
              read_intent(wd, "data") is None)

        # Method has its own marker and starts unknown.
        check("method intent starts unknown", read_intent(wd, "method") is None)
        record_intent(wd, "method")
        check("method intent records", read_intent(wd, "method") is not None)

        # An unknown step is a programming error, not silent.
        try:
            record_intent(wd, "explore")
        except ValueError:
            check("an unknown intent step raises", True)
        else:
            check("an unknown intent step raises", False)

        # Markers live in a directory absent from old workspaces, so an
        # unmigrated workspace is exactly the 'unknown' case above.
        check("markers live under intent/", (wd / "intent" / "method.json").exists())

        # missing_references reports what input_listing deliberately drops.
        gone = files_dir / "external_files.txt"
        real = tmp / "real.mzML"
        real.write_bytes(b"x")
        gone.write_text(f"{real}\n{tmp / 'vanished.mzML'}\n")
        check("a referenced file that no longer exists is reported",
              missing_references(files_dir) == [str(tmp / "vanished.mzML")],
              str(missing_references(files_dir)))
        check("an existing reference is not reported as missing",
              str(real) not in missing_references(files_dir))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    method_only_ignores_input_selection()

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0




def method_only_ignores_input_selection():
    """Picking an input file must not mark the Method step as configured.

    select_input_file writes the chosen files into params.json, so the whole-file
    diff reported "Method: changed from defaults" as soon as a user chose an mzML
    file on the Data step. Reproduced in the browser before the fix.
    """
    from src.workflow.ParameterManager import method_only

    inp = "/ws/flashdeconv/input-files/mzML-files/example.mzML"
    before = {"mzML-files": [], "threads": 4}
    picked = {"mzML-files": [inp], "threads": 4}
    tuned = {"mzML-files": [inp], "threads": 8}

    check("choosing an input file is not a method change",
          method_only(before) == method_only(picked))
    check("changing a real parameter still is",
          method_only(picked) != method_only(tuned))
    check("a non-path list is kept as a method parameter",
          "charges" in method_only({"charges": ["2", "3"]}))


if __name__ == "__main__":
    sys.exit(main())
