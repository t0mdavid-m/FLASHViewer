"""Linking a file records its path instead of copying it — and never deletes it.

Linking is decided by the CALLER, which knows whether the file belongs to the
user, not by the deployment mode. Inferring it from "is this a Path on desktop"
linked the workflow's own outputs, which live in a per-run temp directory that
is deleted moments later, leaving index rows pointing at deleted files. The
default-does-not-link check below is the regression guard for that.

Run: FLASHAPP_DESKTOP=1 python3 tests/test_linked_files.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("FLASHAPP_DESKTOP", "1")
from src.workflow.FileManager import FileManager  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        source = tmp / "elsewhere" / "run_deconv.mzML"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x" * 4096)

        cache = tmp / "ws" / "cache"
        cache.mkdir(parents=True)
        fm = FileManager(tmp / "ws", cache)

        # Default must COPY even on desktop: the caller has not claimed the
        # file belongs to the user, and workflow temp output must not be linked.
        fm.store_file("run0", "out_deconv_mzML", source, remove=False)
        copied = Path(fm.get_results("run0", ["out_deconv_mzML"])["out_deconv_mzML"])
        assert copied.parent == cache / "files" / "run0", copied
        assert source.exists()

        # The shape the pages ACTUALLY call: no remove=, so remove defaults to
        # True. That must never delete a file outside our own storage — this is
        # the exact regression that deleted users' raw mzML on desktop.
        fm.store_file("run0b", "out_deconv_mzML", source)
        assert source.exists(), "store_file() deleted the user's original file"

        # ...but a file that IS ours may still be tidied up, or the workflow
        # would leave its scratch copies behind.
        ours = cache / "files" / "scratch.mzML"
        ours.parent.mkdir(parents=True, exist_ok=True)
        ours.write_bytes(b"scratch")
        fm.store_file("run0c", "out_deconv_mzML", ours)
        assert not ours.exists(), "our own scratch file was not cleaned up"

        # Explicit link: referenced, not copied.
        fm.store_file("run", "out_deconv_mzML", source, remove=True, link=True)
        stored = Path(fm.get_results("run", ["out_deconv_mzML"])["out_deconv_mzML"])
        assert stored == source.resolve(), stored
        assert not (cache / "files" / "run").exists(), "linked file was also copied"

        # remove=True must NOT delete a linked original.
        assert source.exists(), "linked source file was deleted"

        # Deleting the dataset must not touch the user's file, and must not
        # crash on the per-dataset directory that linking never creates.
        fm.remove_results("run")
        assert source.exists(), "remove_results() deleted the user's original"
        assert "run" not in fm.get_results_list(["out_deconv_mzML"])

        print("linked files: all checks passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
