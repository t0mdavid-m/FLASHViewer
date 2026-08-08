"""Can the shipped example data actually be processed, and are the results right?

Ingests example-data/ the way the app does, parses it with the app's own
parsers, and checks the parsed frames — not merely that something was produced.

Also compares the two ingest routes. The example-data button strips a glob
suffix; the picker and the uploader strip a role suffix. They must agree, or
the same files land under two different dataset ids.

Run: python3 tests/test_example_data.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "example-data"

from src.tools import TOOLS  # noqa: E402
from src.workflow.FileManager import FileManager  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


# (tool, example subdir, the loader's globs, the parse call)
PLAN = [
    ("FLASHDeconv", "flashdeconv",
     (("*_deconv.mzML", "out_deconv_mzML"),
      ("*_annotated.mzML", "anno_annotated_mzML"),
      ("*_spec1.tsv", "spec1_tsv"))),
    ("FLASHTnT", "flashtagger",
     (("*_deconv.mzML", "out_deconv_mzML"),
      ("*_annotated.mzML", "anno_annotated_mzML"),
      ("*_tagged.tsv", "tags_tsv"),
      ("*_protein.tsv", "protein_tsv"))),
    ("FLASHQuant", "flashquant",
     (("*.fq.tsv", "quant_tsv"),
      ("*.fq.mts.tsv", "trace_tsv"),
      ("*.fq_shared.tsv", "conflict_tsv"))),
]


def id_agreement():
    """The two ingest routes must derive the same dataset id from a filename."""
    for tool, subdir, globs in PLAN:
        d = EXAMPLES / subdir
        if not d.is_dir():
            continue
        disagreements = []
        for pattern, _tag in globs:
            for f in sorted(d.glob(pattern)):
                loader_id = f.name.replace(pattern[1:], "")
                routed = TOOLS[tool].dataset_id_for(f.name)
                if routed and routed[0] != loader_id:
                    disagreements.append((f.name, loader_id, routed[0]))
        if tool == "FLASHQuant":
            # KNOWN, pre-existing: the loader strips ".fq.tsv" and the picker
            # strips ".tsv", so the button yields "example" and adding the same
            # files by hand yields "example.fq" — two datasets for one
            # experiment. Recorded rather than silently normalised, because
            # changing either id changes what existing workspaces are keyed on.
            check(f"{tool}: example-loader vs picker ids differ (known)",
                  bool(disagreements), f"{len(disagreements)} file(s)")
        else:
            check(f"{tool}: both ingest routes agree on the dataset id",
                  not disagreements, str(disagreements))


def process(tool, subdir, globs, tmp):
    """Ingest exactly as the loader does, then parse, then check the frames."""
    d = EXAMPLES / subdir
    if not d.is_dir():
        print(f"  skip  {tool}: no example data")
        return

    cache = tmp / tool / "cache"
    cache.mkdir(parents=True)
    fm = FileManager(tmp / tool, cache)

    stored = 0
    for pattern, name_tag in globs:
        for f in sorted(d.glob(pattern)):
            fm.store_file(f.name.replace(pattern[1:], ""), name_tag, f,
                          remove=False)
            stored += 1
    check(f"{tool}: example files ingest", stored > 0, f"{stored} files")

    datasets = sorted(set(
        i for _p, tag in globs for i in fm.get_results_list([tag])))
    check(f"{tool}: datasets registered", bool(datasets), str(datasets))

    for dataset_id in datasets:
        if tool == "FLASHDeconv":
            from src.parse.deconv import parseDeconv
            got = fm.get_results(dataset_id,
                                 ["out_deconv_mzML", "anno_annotated_mzML",
                                  "spec1_tsv", "spec2_tsv"], partial=True)
            parsed = parseDeconv(**got)
            _check_frames(tool, dataset_id, parsed,
                          expect=("deconv_dfs", "anno_dfs"))
        elif tool == "FLASHTnT":
            from src.parse.tnt import parseTnT
            need = ["out_deconv_mzML", "anno_annotated_mzML",
                    "tags_tsv", "protein_tsv"]
            got = fm.get_results(dataset_id, need)
            if [t for t in need if t not in got]:
                continue          # incomplete by design; covered elsewhere
            parsed = parseTnT(got["out_deconv_mzML"], got["anno_annotated_mzML"],
                              got["tags_tsv"], got["protein_tsv"])
            _check_frames(tool, dataset_id, parsed,
                          expect=("deconv_dfs", "anno_dfs", "tag_dfs",
                                  "protein_dfs"))
        else:
            from src.parse.quant import parseQuant
            got = fm.get_results(dataset_id, ["quant_tsv", "trace_tsv"])
            if "quant_tsv" not in got or "trace_tsv" not in got:
                continue
            conflict = None
            if fm.result_exists(dataset_id, "conflict_tsv"):
                conflict = fm.get_results(dataset_id,
                                          ["conflict_tsv"])["conflict_tsv"]
            parsed = parseQuant(got["quant_tsv"], got["trace_tsv"], conflict)
            _check_frames(tool, dataset_id, parsed, expect=("quant_dfs",))


def _check_frames(tool, dataset_id, parsed, expect):
    """The results must be usable, not merely present."""
    for tag in expect:
        check(f"{tool}/{dataset_id}: {tag} produced", tag in parsed)
        frame = parsed.get(tag)
        if frame is None:
            continue
        check(f"{tool}/{dataset_id}: {tag} is non-empty", len(frame) > 0,
              f"{len(frame)} rows")

    # Spectral frames carry paired mass/intensity arrays. A length mismatch
    # renders a plot with silently wrong points, so it is worth asserting.
    spec = parsed.get("deconv_dfs")
    if spec is not None and "mzarray" in spec and "intarray" in spec:
        pairs_ok = all(len(a) == len(b)
                       for a, b in zip(spec["mzarray"], spec["intarray"]))
        check(f"{tool}/{dataset_id}: mass and intensity arrays are paired",
              pairs_ok)
        masses = [m for row in spec["mzarray"] for m in row]
        check(f"{tool}/{dataset_id}: masses positive and finite",
              bool(masses) and all(m > 0 and m == m for m in masses),
              f"{len(masses)} masses" if masses else "none")

    proteins = parsed.get("protein_dfs")
    if proteins is not None and "DatabaseSequence" in proteins:
        check(f"{tool}/{dataset_id}: proteoforms carry sequences",
              all(isinstance(s, str) and s for s in proteins["DatabaseSequence"]))


def main():
    if not EXAMPLES.is_dir():
        print(f"SKIP: no example data at {EXAMPLES}")
        return 0

    print(f"example data: {EXAMPLES}\n")
    id_agreement()
    tmp = Path(tempfile.mkdtemp(prefix="flashapp-example-"))
    try:
        for tool, subdir, globs in PLAN:
            process(tool, subdir, globs, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
