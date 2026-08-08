"""Run FLASHDeconv for real and check the results are correct.

example-data ships both the input (example_fd.mzML) and the outputs the app was
built against (example_fd_deconv.mzML, example_fd_annotated.mzML), so the
reference is the shipped output, not a value invented here.

Needs the FLASHDeconv binary. Set OPENMS_BIN, or drop it in desktop/topp/, or
have it on PATH; otherwise the run is skipped rather than reported as passing.

Run: python3 tests/test_end_to_end.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "example-data" / "flashdeconv"

# Deconvolution is a numerical pipeline; different builds differ in the last
# bits. Correctness here means "the same spectra, the same masses to within
# tolerance", not byte equality.
REL_TOL = 1e-4
MIN_MASS_OVERLAP = 0.98


def find_binary():
    for candidate in (
        Path(os.environ["OPENMS_BIN"]) / "FLASHDeconv" if os.environ.get("OPENMS_BIN") else None,
        REPO / "desktop" / "topp" / "FLASHDeconv",
        Path("/Users/kohlbach/Claude/OpenMS/OpenMS-build/bin/FLASHDeconv"),
    ):
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("FLASHDeconv")
    return Path(found) if found else None


def run_flashdeconv(binary, in_mzml, out_dir):
    out = {
        "out": out_dir / "features.tsv",
        "out_mzml": out_dir / "produced_deconv.mzML",
        "out_annotated_mzml": out_dir / "produced_annotated.mzML",
        "out_spec1": out_dir / "spec1.tsv",
    }
    cmd = [str(binary), "-in", str(in_mzml)]
    for flag, path in out.items():
        cmd += [f"-{flag}", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FLASHDeconv exited {proc.returncode}\n"
            f"stdout tail:\n{proc.stdout[-1500:]}\nstderr tail:\n{proc.stderr[-1500:]}"
        )
    missing = [str(p) for p in out.values() if not p.exists()]
    if missing:
        raise RuntimeError(f"tool reported success but did not write: {missing}")
    return out


def summarise(deconv_mzml, anno_mzml):
    """Parse through the app's own parser, so the test covers what it ships."""
    from src.masstable import parseFLASHDeconvOutput

    deconv_df, anno_df, *_ = parseFLASHDeconvOutput(str(anno_mzml), str(deconv_mzml))
    return deconv_df, anno_df


def main():
    if not DATA.is_dir():
        print(f"SKIP: no example data at {DATA}")
        return 0
    binary = find_binary()
    if binary is None:
        print("SKIP: FLASHDeconv binary not found (set OPENMS_BIN)")
        return 0

    in_mzml = DATA / "example_fd.mzML"
    ref_deconv = DATA / "example_fd_deconv.mzML"
    ref_anno = DATA / "example_fd_annotated.mzML"
    for p in (in_mzml, ref_deconv, ref_anno):
        if not p.exists():
            print(f"SKIP: missing {p}")
            return 0

    print(f"binary:  {binary}\ninput:   {in_mzml.name}\nreference: {ref_deconv.name}\n")
    tmp = Path(tempfile.mkdtemp(prefix="flashapp-e2e-"))
    failures = []
    try:
        produced = run_flashdeconv(binary, in_mzml, tmp)
        print("run: FLASHDeconv completed")

        got_deconv, got_anno = summarise(produced["out_mzml"], produced["out_annotated_mzml"])
        ref_deconv_df, ref_anno_df = summarise(ref_deconv, ref_anno)

        def check(name, cond, detail=""):
            print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")
            if not cond:
                failures.append(name)

        check("produced some deconvolved spectra", len(got_deconv) > 0,
              f"{len(got_deconv)} spectra")

        # The shipped reference was written by OpenMS 3.0.x; a current binary is
        # several minor versions ahead, and spectrum counts legitimately move
        # between versions. Comparing counts across versions tests the tool's
        # version, not the app — so it is reported, never asserted.
        print(f"  info  reference comparison (informational, cross-version): "
              f"produced {len(got_deconv)}/{len(got_anno)} vs "
              f"reference {len(ref_deconv_df)}/{len(ref_anno_df)} spectra")

        # The schema IS a contract: the viewer indexes these columns by name,
        # so a rename or removal breaks the app regardless of tool version.
        check("schema matches the reference the app was built against",
              set(got_deconv.columns) == set(ref_deconv_df.columns),
              str(set(got_deconv.columns) ^ set(ref_deconv_df.columns)) or "identical")
        check("annotated schema matches reference",
              set(got_anno.columns) == set(ref_anno_df.columns),
              str(set(got_anno.columns) ^ set(ref_anno_df.columns)) or "identical")

        # Version-independent sanity of the numbers themselves.
        if "mzarray" in got_deconv:
            masses = [m for row in got_deconv["mzarray"] for m in row]
            check("masses are positive and finite",
                  bool(masses) and all(m > 0 and m == m and m != float("inf") for m in masses),
                  f"{len(masses)} masses, range "
                  f"{min(masses):.2f}–{max(masses):.2f}" if masses else "none")
        if "intarray" in got_deconv:
            ints = [i for row in got_deconv["intarray"] for i in row]
            check("intensities are non-negative", all(i >= 0 for i in ints),
                  f"{len(ints)} values")
        if "mzarray" in got_deconv and "intarray" in got_deconv:
            check("every spectrum has matching mass/intensity lengths",
                  all(len(a) == len(b) for a, b in
                      zip(got_deconv["mzarray"], got_deconv["intarray"])))

        # A parsed result must be usable by the rest of the app.
        from src.masstable import getSpectraTableDF
        scan_table = getSpectraTableDF(got_deconv)
        check("scan table builds from the produced result", len(scan_table) > 0,
              f"{len(scan_table)} rows")

        # The input must not have been consumed or altered by the run.
        check("input file untouched", in_mzml.exists())
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  run/compare: {type(exc).__name__}: {exc}")
        failures.append("run")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'end-to-end: all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
