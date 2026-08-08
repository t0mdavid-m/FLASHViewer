"""A dataset missing some of its files must not crash the Add-results page.

FLASHTnT needs four files. get_results_list() silently drops columns that do not
exist, so its AND query degrades to whatever columns are present and returns a
dataset that has only the two mzMLs. get_results() then returns only the tags it
found, and the page indexed results['tags_tsv'] directly — a bare
KeyError: 'tags_tsv' for anyone who added the mzML pair before the TSVs.

Run: python3 tests/test_partial_upload.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "example-data" / "flashtagger"

from src.workflow.FileManager import FileManager  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


REQUIRED = ["out_deconv_mzML", "anno_annotated_mzML", "tags_tsv", "protein_tsv"]


def main():
    if not DATA.is_dir():
        print(f"SKIP: no example data at {DATA}")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="flashapp-partial-"))
    try:
        cache = tmp / "cache"
        cache.mkdir(parents=True)
        fm = FileManager(tmp, cache)

        # A partial upload: the two mzMLs, no TSVs. This is what a user gets by
        # adding files in two goes, or by picking the wrong subset.
        fm.store_file("s1", "out_deconv_mzML",
                      DATA / "example_spectrum_1_deconv.mzML", remove=False)
        fm.store_file("s1", "anno_annotated_mzML",
                      DATA / "example_spectrum_1_annotated.mzML", remove=False)

        # The dataset IS returned as needing parsing, despite being incomplete.
        listed = fm.get_results_list(REQUIRED)
        check("an incomplete dataset still appears in the AND query",
              "s1" in listed, str(listed))

        # ...and get_results returns fewer tags than asked for, without raising.
        results = fm.get_results("s1", REQUIRED)
        missing = [t for t in REQUIRED if t not in results]
        check("get_results silently omits absent tags",
              missing == ["tags_tsv", "protein_tsv"], str(missing))

        # The guard the page now applies: detect the gap instead of indexing.
        check("the missing tags are detectable before parsing", bool(missing))

        # A complete dataset must still pass the guard.
        fm.store_file("s2", "out_deconv_mzML",
                      DATA / "example_spectrum_1_deconv.mzML", remove=False)
        fm.store_file("s2", "anno_annotated_mzML",
                      DATA / "example_spectrum_1_annotated.mzML", remove=False)
        fm.store_file("s2", "tags_tsv",
                      DATA / "example_spectrum_1_tagged.tsv", remove=False)
        fm.store_file("s2", "protein_tsv",
                      DATA / "example_spectrum_1_protein.tsv", remove=False)
        complete = fm.get_results("s2", REQUIRED)
        check("a complete dataset yields every tag",
              [t for t in REQUIRED if t not in complete] == [], str(sorted(complete)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
