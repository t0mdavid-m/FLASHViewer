"""End-to-end pipeline test for all three tools, over the shipped example data.

Exercises the steps a workflow actually performs, in order, without Streamlit:

    ingest files -> parse -> store in cache -> index queries -> preset
    availability -> the layout the viewer would render

Test data is example-data/, which is in the repo but stripped from the desktop
bundle, so this runs from a source checkout.

Run:  python3 tests/test_workflow_pipeline.py
      python3 tests/test_workflow_pipeline.py --keep   (leave the workspace)
"""
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "example-data"

from src.workflow.FileManager import FileManager  # noqa: E402
from src import presets as presets_mod  # noqa: E402

RESULTS = []


def step(name):
    def wrap(fn):
        def run(*a, **kw):
            try:
                fn(*a, **kw)
            except Exception as exc:
                RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))
                traceback.print_exc()
                return False
            RESULTS.append((name, "ok", ""))
            return True
        return run
    return wrap


def require(paths):
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(", ".join(str(m) for m in missing))


# ---------------------------------------------------------------- FLASHDeconv

@step("FLASHDeconv: ingest + parse + cache")
def deconv(ws):
    from src.parse.deconv import parseDeconv

    d = EXAMPLES / "flashdeconv"
    deconv_mzml = d / "example_fd_deconv.mzML"
    anno_mzml = d / "example_fd_annotated.mzML"
    spec1 = d / "example_fd_spec1.tsv"
    require([deconv_mzml, anno_mzml, spec1])

    fm = FileManager(ws, ws / "flashdeconv" / "cache")
    # remove defaults to True; these are the user's files and must survive.
    fm.store_file("example_fd", "out_deconv_mzML", deconv_mzml, remove=False)
    fm.store_file("example_fd", "anno_annotated_mzML", anno_mzml, remove=False)
    fm.store_file("example_fd", "spec1_tsv", spec1, remove=False)
    assert deconv_mzml.exists(), "ingest deleted the user's source file"

    got = fm.get_results("example_fd",
                         ["out_deconv_mzML", "anno_annotated_mzML", "spec1_tsv"])
    parsed = parseDeconv(**got)
    for tag, frame in parsed.items():
        fm.store_data("example_fd", tag, frame)

    assert "deconv_dfs" in parsed and "anno_dfs" in parsed, sorted(parsed)
    assert len(parsed["deconv_dfs"]) > 0, "no deconvolved spectra parsed"
    assert fm.result_exists("example_fd", "deconv_dfs")
    assert "example_fd" in fm.get_results_list(["deconv_dfs", "anno_dfs"])
    return fm


@step("FLASHDeconv: preset availability matches the cache")
def deconv_presets(ws):
    fm = FileManager(ws, ws / "flashdeconv" / "cache")
    avail = {p["id"]: (ok, why)
             for p, ok, why in presets_mod.for_dataset("FLASHDeconv", fm, "example_fd")}

    assert avail["deconvolution_qc"][0], avail["deconvolution_qc"]
    assert avail["spectrum_deep_dive"][0], avail["spectrum_deep_dive"]
    # No sequence was submitted, so this one must be refused, with a reason.
    ok, why = avail["sequence_coverage"]
    assert not ok and why, avail["sequence_coverage"]

    # FDR needs a parsed TSV, which parseDeconv only writes when the file
    # carried a TargetDecoyType column.
    ok, why = avail["scoring_fdr"]
    assert isinstance(ok, bool) and (ok or why)

    # Whatever the viewer would render must satisfy its own prerequisites.
    for pid in avail:
        preset = presets_mod.get("FLASHDeconv", pid)
        rows, added = presets_mod.expand_prerequisites("FLASHDeconv", preset["rows"])
        assert added == [], f"{pid} ships unsatisfied prerequisites: {added}"
        assert all(len(r) <= 3 for r in rows), pid


# ------------------------------------------------------------------ FLASHTnT

@step("FLASHTnT: ingest + parse + cache")
def tnt(ws):
    from src.parse.tnt import parseTnT

    d = EXAMPLES / "flashtagger"
    files = {
        "out_deconv_mzML": d / "example_spectrum_1_deconv.mzML",
        "anno_annotated_mzML": d / "example_spectrum_1_annotated.mzML",
        "tag_tsv": d / "example_spectrum_1_tagged.tsv",
        "protein_tsv": d / "example_spectrum_1_protein.tsv",
    }
    require(list(files.values()))

    fm = FileManager(ws, ws / "flashtnt" / "cache")
    for tag, path in files.items():
        fm.store_file("example_tnt", tag, path, remove=False)
    assert all(p.exists() for p in files.values()), "ingest deleted a source file"

    got = fm.get_results("example_tnt", list(files))
    parsed = parseTnT(
        deconv_mzML=got["out_deconv_mzML"], anno_mzML=got["anno_annotated_mzML"],
        tag_tsv=got["tag_tsv"], protein_tsv=got["protein_tsv"],
    )
    for tag, frame in parsed.items():
        fm.store_data("example_tnt", tag, frame)

    for tag in ("deconv_dfs", "tag_dfs", "protein_dfs"):
        assert fm.result_exists("example_tnt", tag), tag
    assert len(parsed["protein_dfs"]) > 0, "no proteoforms parsed"


@step("FLASHTnT: preset availability + the crash-preset regression")
def tnt_presets(ws):
    fm = FileManager(ws, ws / "flashtnt" / "cache")
    avail = {p["id"]: (ok, why)
             for p, ok, why in presets_mod.for_dataset("FLASHTnT", fm, "example_tnt")}
    assert avail["proteoform_id"][0], avail["proteoform_id"]

    # The handoff's "Proteoform mapping" omitted protein_table and raised
    # KeyError in the viewer, because only that branch builds per_scan_data.
    rows, _ = presets_mod.expand_prerequisites(
        "FLASHTnT", presets_mod.get("FLASHTnT", "proteoform_mapping")["rows"])
    flat = [c for r in rows for c in r]
    assert "protein_table" in flat, rows


# ---------------------------------------------------------------- FLASHQuant

@step("FLASHQuant: ingest + parse + cache")
def quant(ws):
    from src.parse.quant import parseQuant

    d = EXAMPLES / "flashquant"
    files = {
        "quant_tsv": d / "example.fq.tsv",
        "trace_tsv": d / "example.fq.mts.tsv",
        "conflict_tsv": d / "example.fq_shared.tsv",
    }
    require(list(files.values()))

    fm = FileManager(ws, ws / "flashquant" / "cache")
    for tag, path in files.items():
        fm.store_file("example_fq", tag, path, remove=False)

    got = fm.get_results("example_fq", list(files))
    parsed = parseQuant(**got)
    for tag, frame in parsed.items():
        fm.store_data("example_fq", tag, frame)

    assert "quant_dfs" in parsed, sorted(parsed)
    assert len(parsed["quant_dfs"]) > 0, "no quant features parsed"
    assert fm.result_exists("example_fq", "quant_dfs")


# ------------------------------------------------------------------ lifecycle

@step("Lifecycle: delete a dataset without touching the user's files")
def lifecycle(ws):
    d = EXAMPLES / "flashdeconv"
    source = d / "example_fd_deconv.mzML"
    fm = FileManager(ws, ws / "flashdeconv" / "cache")

    fm.store_file("throwaway", "out_deconv_mzML", source, remove=False)
    assert fm.result_exists("throwaway", "out_deconv_mzML")
    fm.remove_results("throwaway")
    assert "throwaway" not in fm.get_results_list(["out_deconv_mzML"])
    assert source.exists(), "removing a dataset deleted the user's original file"

    # The real datasets are untouched by that removal.
    assert "example_fd" in fm.get_results_list(["deconv_dfs"])


def main():
    if not EXAMPLES.is_dir():
        print(f"SKIP: no example data at {EXAMPLES} (stripped from desktop builds)")
        return 0

    keep = "--keep" in sys.argv
    ws = Path(tempfile.mkdtemp(prefix="flashapp-pipeline-"))
    print(f"workspace: {ws}\ntest data: {EXAMPLES}\n")
    try:
        deconv(ws)
        deconv_presets(ws)
        tnt(ws)
        tnt_presets(ws)
        quant(ws)
        lifecycle(ws)
    finally:
        if not keep:
            shutil.rmtree(ws, ignore_errors=True)

    width = max(len(n) for n, _, _ in RESULTS)
    print()
    for name, status, detail in RESULTS:
        print(f"  {status:4}  {name:<{width}}  {detail}")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} steps passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
