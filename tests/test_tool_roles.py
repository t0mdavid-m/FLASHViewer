"""Filename → (dataset_id, cache tag), per tool.

Reproduces the three hand-written if/elif chains in the Add-results pages. Two
properties matter and both are easy to break in a refactor:

1. Declaration order. FLASHQuant's ".tsv" is a catch-all, so ".mts.tsv" and
   "_shared.tsv" must be tested first or every quant file becomes quant_tsv.
2. The stripped filename is a deliberate JOIN KEY. sampleA_deconv.mzML and
   sampleA_annotated.mzML must collide into one dataset — that collision is the
   mechanism that groups a multi-file experiment, which is why opaque dataset
   ids were rejected.

Run: python3 tests/test_tool_roles.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tools import TOOLS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


CASES = [
    ("FLASHDeconv", "example_fd_deconv.mzML", "example_fd", "out_deconv_mzML"),
    ("FLASHDeconv", "example_fd_annotated.mzML", "example_fd", "anno_annotated_mzML"),
    ("FLASHDeconv", "example_fd_spec1.tsv", "example_fd", "spec1_tsv"),
    ("FLASHDeconv", "example_fd_spec2.tsv", "example_fd", "spec2_tsv"),
    ("FLASHTnT", "s1_deconv.mzML", "s1", "out_deconv_mzML"),
    ("FLASHTnT", "s1_annotated.mzML", "s1", "anno_annotated_mzML"),
    ("FLASHTnT", "s1_tagged.tsv", "s1", "tags_tsv"),
    ("FLASHTnT", "s1_protein.tsv", "s1", "protein_tsv"),
    # Order-critical: all three must reach a different tag, same dataset.
    ("FLASHQuant", "example.fq.mts.tsv", "example.fq", "trace_tsv"),
    ("FLASHQuant", "example.fq_shared.tsv", "example.fq", "conflict_tsv"),
    ("FLASHQuant", "example.fq.tsv", "example.fq", "quant_tsv"),
]


def main():
    for tool, filename, want_id, want_tag in CASES:
        got = TOOLS[tool].dataset_id_for(filename)
        check(f"{tool}: {filename}", got == (want_id, want_tag), str(got))

    # Files that belong to no role are rejected, not silently mis-filed.
    for tool, filename in (("FLASHDeconv", "notes.txt"),
                           ("FLASHTnT", "image.png"),
                           ("FLASHDeconv", "plain.mzML")):
        check(f"{tool}: rejects {filename}",
              TOOLS[tool].dataset_id_for(filename) is None)

    # The join key: a multi-file experiment collapses to ONE dataset id.
    for tool, names in (
        ("FLASHDeconv", ["s_deconv.mzML", "s_annotated.mzML", "s_spec1.tsv"]),
        ("FLASHTnT", ["s_deconv.mzML", "s_annotated.mzML",
                      "s_tagged.tsv", "s_protein.tsv"]),
        ("FLASHQuant", ["e.fq.tsv", "e.fq.mts.tsv", "e.fq_shared.tsv"]),
    ):
        ids = {TOOLS[tool].dataset_id_for(n)[0] for n in names}
        check(f"{tool}: {len(names)} files group into one dataset",
              len(ids) == 1, str(ids))

    # Every shipped example file must classify — this cross-checks the specs
    # against the data tests/test_workflow_pipeline.py already relies on.
    for tool, subdir in (("FLASHDeconv", "flashdeconv"),
                         ("FLASHTnT", "flashtagger"),
                         ("FLASHQuant", "flashquant")):
        d = REPO / "example-data" / subdir
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lstrip(".") not in TOOLS[tool].extensions:
                continue
            # example_fd.mzML is raw input, not FLASH* output: no role, by design.
            if f.name in ("example_fd.mzML", "example_spectrum_1.mzML",
                          "example_spectrum_2.mzML"):
                continue
            check(f"{tool}: example {f.name} classifies",
                  TOOLS[tool].dataset_id_for(f.name) is not None)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
