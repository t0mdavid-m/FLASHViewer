"""Per-tool facts, and the pure helpers that read a workspace.

Deliberately free of Streamlit *and* of the parsers: `src/parse/*` pull in
pyopenms via `src/masstable.py`, and keeping this module importable without
either is what lets the plain-python test suite exercise it. Same split as
`src/presets.py` (pure) vs `src/preset_page.py` (Streamlit).
"""
import json
import os
import time
from pathlib import Path


def input_listing(files_dir):
    """Split a tool's input directory into (copied files, referenced paths).

    Files added by reference are recorded as one absolute path per line in
    external_files.txt, not placed in the directory — so anything deciding
    "is there input here?" has to consult both. A referenced file that has
    since been moved away is dropped rather than reported as present.

    This is the single implementation; `StreamlitUI.upload_widget` calls it, so
    a test that exercises it is testing the shipping code rather than a mirror
    of it.
    """
    files_dir = Path(files_dir)
    if not files_dir.exists():
        return [], []

    external_index = files_dir / "external_files.txt"
    external_list = []
    if external_index.exists():
        with open(external_index) as fh:
            external_list = [
                line for line in fh.read().splitlines()
                if line and os.path.exists(line)
            ]

    copied_present = [f for f in files_dir.iterdir()
                      if f.name != "external_files.txt"]
    return copied_present, external_list


def has_input(files_dir):
    """Does this tool have any input at all, copied or referenced?"""
    copied, external = input_listing(files_dir)
    return bool(copied or external)


def missing_references(files_dir):
    """Referenced paths recorded in external_files.txt that no longer exist.

    input_listing() *drops* these, which is right for "what can I run?" and
    useless for "is anything broken?". A separate function rather than a third
    return value, because upload_widget and tests/test_input_listing.py both
    unpack the existing two-tuple.
    """
    index = Path(files_dir, "external_files.txt")
    if not index.exists():
        return []
    with open(index) as fh:
        return [line for line in fh.read().splitlines()
                if line and not os.path.exists(line)]


# ------------------------------------------------------------ recorded intent

_INTENT_STEPS = ("data", "method")


def _intent_path(workflow_dir, step):
    if step not in _INTENT_STEPS:
        raise ValueError(f"unknown intent step: {step!r}")
    return Path(workflow_dir, "intent", f"{step}.json")


def record_intent(workflow_dir, step, **fields):
    """Record that the user did something deliberate.

    Ownership must be a recorded property, never inferred — the two data-loss
    bugs in HANDOFF.md section 2 are both that mistake. The same applies to
    intent: `upload_widget` auto-copies the example files whenever its
    directory is empty, and `save_parameters()` runs on every widget render, so
    both naive signals are already true before the user has done anything.

    Call this ONLY from a branch a user action actually reached:
      - the upload form's submit branch           source="upload"
      - desktop_file_picker's non-empty return    source="reference"
      - the Load example data button              source="example"
      - save_parameters(), only when the dict differs from the one on disk
    """
    path = _intent_path(workflow_dir, step)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    payload.update(fields)
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_intent(workflow_dir, step):
    """The recorded intent, or None if there is none.

    None means UNKNOWN, not "no". Existing workspaces are deliberately not
    migrated, so one made before this existed has files and no marker — the UI
    must say "added earlier" rather than claim the user chose them, or claim
    there is nothing there.
    """
    path = _intent_path(workflow_dir, step)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# ------------------------------------------------------------------------ run state

def format_age(seconds):
    """'6 min', '4 h 12 min', '3 days'. Used by both Run captions."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return ""                      # caller drops the "for ..." clause
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h {(seconds % 3600) // 60} min"
    days = seconds // 86400
    return f"{days} day" if days == 1 else f"{days} days"


def run_state(workflow_dir):
    """(state, caption, detail) for the Run step. state in todo/running/done/error.

    'partial' is decided by the caller, which knows how many inputs were
    selected; see build_steps in wizard.py.

    A killed app leaves pids/ behind, so 'running' can be stale. This does NOT
    try to detect that: it reports the age, and "Running for 3 days" reads as
    obviously wrong without the app claiming knowledge it does not have.
    """
    pid_dir = Path(workflow_dir, "pids")
    log_dir = Path(workflow_dir, "logs")

    if pid_dir.exists():
        try:
            started = min(p.stat().st_mtime for p in pid_dir.iterdir())
        except (ValueError, OSError):
            started = pid_dir.stat().st_mtime
        age = format_age(time.time() - started)
        return "running", (f"Running for {age}" if age else "Running"), None

    log = _latest_log(log_dir)
    if log is None:
        return "todo", "Not run yet", None

    try:
        content = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "error", "Log could not be read", None

    age = format_age(time.time() - log.stat().st_mtime)

    # Checked BEFORE "WORKFLOW FINISHED", not after. workflow_process() logs
    # FINISHED whenever execution() returns without raising, so a TOPP tool that
    # failed mid-run still reaches it. Reporting "done" for a run that produced
    # nothing is the one failure this banner must not have.
    failed = next((ln for ln in content.splitlines()
                   if ln.startswith("ERROR") or "ERRORS OCCURRED" in ln), None)
    if failed:
        return "error", "Failed", failed.split(":", 1)[-1].strip()[:60]

    if "WORKFLOW FINISHED" in content:
        # The log is wiped at the start of every run and is per-tool, so this
        # describes the LATEST run only. Every caption is phrased that way, so
        # nothing here lies about history.
        return "done", (f"Finished {age} ago" if age else "Just finished"), None

    last = next((ln for ln in reversed(content.splitlines()) if ln.strip()), "")
    return "error", "Stopped before finishing", last.strip()[:60]


def _latest_log(log_dir):
    if not log_dir.exists():
        return None
    logs = [p for p in log_dir.iterdir() if p.is_file()]
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)


# ------------------------------------------------------------- tool descriptors

class Role:
    """One file role within one tool's dataset.

    name_tag is LOAD-BEARING: parseDeconv(**results) works only because the
    cache tags equal the parser's parameter names. Never rename one to prettify
    a column header. (parseTnT's do NOT match, which is why it is called
    positionally — see HANDOFF.md.)
    """

    def __init__(self, suffix, name_tag, label):
        self.suffix = suffix
        self.name_tag = name_tag
        self.label = label


class ToolSpec:
    """The per-tool facts the wizard and the data surface need.

    cache_subdir must equal WorkflowManager's workflow_dir.stem, which is
    name.lower(); the viewers derive the same path from hardcoded strings today.
    """

    def __init__(self, name, cache_subdir, required_tags, viewer_page,
                 has_method, has_run, roles=(), extensions=()):
        self.name = name
        self.cache_subdir = cache_subdir
        self.required_tags = list(required_tags)
        self.viewer_page = viewer_page
        self.has_method = has_method
        self.has_run = has_run
        self.roles = tuple(roles)
        self.extensions = tuple(extensions)

    def role_for(self, filename):
        """The role a filename belongs to, or None.

        Declaration order matters and is deliberate: FLASHQuant's ".tsv" is a
        catch-all, so ".mts.tsv" and "_shared.tsv" must be tested before it.
        """
        for role in self.roles:
            if filename.endswith(role.suffix):
                return role
        return None

    def dataset_id_for(self, filename):
        """(dataset_id, name_tag) for a filename, or None if it is not ours.

        The stripped filename is a deliberate JOIN KEY, not a label:
        sampleA_deconv.mzML and sampleA_annotated.mzML must collide into one
        dataset. Uses split() rather than a slice to match the existing pages
        exactly — they differ on pathological names.
        """
        role = self.role_for(filename)
        if role is None:
            return None
        return filename.split(role.suffix)[0], role.name_tag


TOOLS = {
    "FLASHDeconv": ToolSpec(
        "FLASHDeconv", "flashdeconv", ["deconv_dfs", "anno_dfs"],
        "content/FLASHDeconv/FLASHDeconvViewer.py", True, True,
        roles=(
            Role("_deconv.mzML", "out_deconv_mzML", "Deconvolved"),
            Role("_annotated.mzML", "anno_annotated_mzML", "Annotated"),
            Role("_spec1.tsv", "spec1_tsv", "MS1 TSV"),
            Role("_spec2.tsv", "spec2_tsv", "MS2 TSV"),
        ),
        extensions=("mzML", "tsv")),
    "FLASHTnT": ToolSpec(
        "FLASHTnT", "flashtnt",
        ["deconv_dfs", "anno_dfs", "tag_dfs", "protein_dfs"],
        "content/FLASHTnT/FLASHTnTViewer.py", True, True,
        roles=(
            Role("_deconv.mzML", "out_deconv_mzML", "Deconvolved"),
            Role("_annotated.mzML", "anno_annotated_mzML", "Annotated"),
            Role("_tagged.tsv", "tags_tsv", "Tags"),
            Role("_protein.tsv", "protein_tsv", "Proteins"),
        ),
        extensions=("mzML", "tsv")),
    # QuantWorkflow implements neither configure() nor execution(): the steps
    # are genuinely absent, not unimplemented.
    "FLASHQuant": ToolSpec(
        "FLASHQuant", "flashquant", ["quant_dfs"],
        "content/FLASHQuant/FLASHQuantViewer.py", False, False,
        roles=(
            # Order is load-bearing: ".tsv" is a catch-all and must come last.
            Role(".mts.tsv", "trace_tsv", "Mass traces"),
            Role("_shared.tsv", "conflict_tsv", "Conflicts"),
            Role(".tsv", "quant_tsv", "Quant results"),
        ),
        extensions=("tsv",)),
}
