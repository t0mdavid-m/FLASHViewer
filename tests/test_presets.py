"""Availability against a real FileManager, not a mock.

The point of the exercise is FileManager.get_results_list()'s habit of dropping
columns it does not know about: a preset whose required field was never created
must report unavailable, not silently pass.

Run: python3 tests/test_presets.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import presets  # noqa: E402
from src.workflow.FileManager import FileManager  # noqa: E402


def build_cache(root, tags):
    cache = Path(root, "cache")
    cache.mkdir(parents=True, exist_ok=True)
    fm = FileManager(Path(root), cache)
    for tag in tags:
        fm.store_data("run-a", tag, pd.DataFrame({"x": [1, 2, 3]}))
    return fm


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        # A FLASHDeconv run with the basics but no FDR TSV and no sequence.
        fm = build_cache(tmp / "deconv", ["deconv_dfs", "anno_dfs"])

        by_id = {p["id"]: (ok, why) for p, ok, why in
                 presets.for_dataset("FLASHDeconv", fm, "run-a", has_sequence=False)}

        assert by_id["deconvolution_qc"][0], by_id["deconvolution_qc"]
        assert by_id["spectrum_deep_dive"][0], by_id["spectrum_deep_dive"]

        # The two that must be refused, and the reason must be legible.
        ok, why = by_id["scoring_fdr"]
        assert not ok, "FDR preset offered without any parsed_tsv_file_*"
        assert "report_FDR" in why, why

        ok, why = by_id["sequence_coverage"]
        assert not ok, "sequence preset offered with no sequence"
        assert "sequence" in why.lower(), why

        # Same run, once the FDR TSV exists.
        fm.store_data("run-a", "parsed_tsv_file_ms1", pd.DataFrame({"Qscore": [0.1]}))
        by_id = {p["id"]: ok for p, ok, _ in
                 presets.for_dataset("FLASHDeconv", fm, "run-a")}
        assert by_id["scoring_fdr"], "FDR preset still refused after the TSV appeared"

        # A sequence unlocks the coverage preset without touching the cache.
        by_id = {p["id"]: ok for p, ok, _ in
                 presets.for_dataset("FLASHDeconv", fm, "run-a", has_sequence=True)}
        assert by_id["sequence_coverage"]

        # A FLASHTnT run missing tag_dfs: both presets must be refused, naming it.
        fm_tnt = build_cache(tmp / "tnt", ["protein_dfs", "deconv_dfs"])
        for preset, ok, why in presets.for_dataset("FLASHTnT", fm_tnt, "run-a"):
            assert not ok, f"{preset['id']} offered without tag_dfs"
            assert "tag_dfs" in why, why

        # An unknown dataset id must never look available.
        for _, ok, _ in presets.for_dataset("FLASHDeconv", fm, "no-such-run"):
            assert not ok

        print("presets/availability: all checks passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
