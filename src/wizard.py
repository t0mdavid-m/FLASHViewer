"""src/wizard.py — the wizard banner. Rendering only; state comes from src/tools.py.

Mounted above st.tabs on each tool's first page. It sits OUTSIDE st.tabs, so it
does not touch the eager-render contract execution() depends on.
"""
from dataclasses import dataclass

import streamlit as st

from pathlib import Path

from src import presets as presets_mod
from src.tools import (
    format_age, has_input, input_listing, missing_references, read_intent,
    run_state,
)

# label, st.badge colour name, Material Symbol.
# The colour names resolve to greenColor / orangeColor / redColor / primaryColor
# in .streamlit/config.toml. st.badge takes names, not hexes.
STEP_BADGE = {
    "todo":    ("To do",          "gray",    "radio_button_unchecked"),
    "partial": ("Partial",        "orange",  "incomplete_circle"),
    "done":    ("Done",           "green",   "check_circle"),
    "running": ("Running",        "primary", "progress_activity"),
    "error":   ("Error",          "red",     "error"),
    "skipped": ("Not applicable", "gray",    "do_not_disturb_on"),
}


@dataclass
class Step:
    name: str
    state: str
    caption: str
    detail: str = ""    # second caption line, code font. Run error only.
    page: str = ""      # st.page_link target. Explore only.


# --------------------------------------------------------------------- rendering

def wizard_banner(steps):
    """Four steps, always four — including the skipped ones.

    Streamlit stacks columns below roughly 640px with no control over the
    breakpoint. Stacked, this becomes four rows of name-badge-caption, which
    still reads correctly. No fixed widths anywhere.
    """
    with st.container(border=True):
        cols = st.columns([1, .12, 1, .12, 1, .12, 1], vertical_alignment="top")
        for i, step in enumerate(steps):
            with cols[i * 2]:
                _render_step(step)
            if i < len(steps) - 1:
                # The only connector Streamlit can draw. A literal arrow in a
                # markdown string needs no unsafe_allow_html and no class-name
                # targeting. It will NOT vertically centre against the badge.
                cols[i * 2 + 1].markdown(":gray[\u2192]")


def _render_step(step):
    if step.state == "skipped":
        # The only state that dims its own label.
        st.markdown(f":gray[{step.name}]")
    elif step.page:
        # Explore only. st.tabs has no programmatic selection, so Data, Method
        # and Run are labels — do not style them to look clickable.
        st.page_link(step.page, label=f"**{step.name}**")
    else:
        st.markdown(f"**{step.name}**")

    label, colour, icon = STEP_BADGE[step.state]
    st.badge(label, icon=f":material/{icon}:", color=colour)
    st.caption(step.caption)
    if step.detail:
        st.caption(f"`{step.detail}`")


def banner(steps):
    """Mount point. Polls only while something is running."""
    if any(s.state == "running" for s in steps):
        @st.fragment(run_every="5s")
        def _live():
            wizard_banner(steps)
        _live()
    else:
        wizard_banner(steps)


# ------------------------------------------------------------------ step builders

def build_steps(spec, wf, params, files_dir, selected_inputs):
    """Compute all four steps for one tool.

    Recomputed on every rerun — never cached. Do not hold a FileManager or a
    SQLite connection in session state; Streamlit reruns on a fresh thread.

    'wf' is the page's own workflow object. NOTHING here may construct a
    FileManager for another tool: FileManager.__init__ does mkdir + CREATE TABLE.
    """
    return [
        _data_step(spec, params, files_dir, wf.workflow_dir),
        _method_step(spec, wf.workflow_dir, params),
        _run_step(spec, wf.workflow_dir, wf.file_manager, selected_inputs),
        _explore_step(spec, wf.file_manager),
    ]


def _data_step(spec, params, files_dir, workflow_dir):
    # A missing reference outranks every other Data state: it is the one failure
    # the user cannot see from the tab.
    missing = missing_references(files_dir)
    if missing:
        n = len(missing)
        return Step("Data", "error",
                    f"{n} referenced file is missing" if n == 1
                    else f"{n} referenced files are missing")

    intent = read_intent(workflow_dir, "data")

    if intent is None:
        # No marker. Either an un-migrated workspace, or upload_widget's
        # auto-copy of the example files. Never claim the user chose these.
        if not has_input(files_dir):
            return Step("Data", "todo", "No data yet")
        copied, external = _listing(files_dir)
        n = len(copied) + len(external)
        return Step("Data", "partial",
                    f"1 file, added earlier" if n == 1
                    else f"{n} files, added earlier")

    if intent.get("source") == "example":
        return Step("Data", "partial", "Example data only")

    selected = list(selected_names(params, "mzML-files"))
    total = intent.get("count") or len(selected)
    if not selected:
        return Step("Data", "partial",
                    f"{total} file, none selected" if total == 1
                    else f"{total} files, none selected")

    if spec.name == "FLASHTnT" and not selected_names(params, "fasta-file"):
        return Step("Data", "partial", "No database selected")

    if len(selected) == 1:
        return Step("Data", "done", _truncate(selected[0], 28))
    return Step("Data", "done", f"{len(selected)} of {total} files selected")


def _method_step(spec, workflow_dir, params):
    if not spec.has_method:
        return Step("Method", "skipped", "FLASHQuant reads finished output")
    if params is None:                       # params.json unreadable
        return Step("Method", "error", "Parameters could not be read")
    if read_intent(workflow_dir, "method") is None:
        # NOT "nothing configured". Running on defaults is a legitimate, common
        # choice and must not read as blocking.
        return Step("Method", "todo", "Defaults")
    # No count. A diff against the TOPP ini defaults is not reliably computable,
    # and a wrong number is worse than none.
    return Step("Method", "done", "Changed from defaults")


def _run_step(spec, workflow_dir, file_manager, selected_inputs):
    if not spec.has_run:
        return Step("Run", "skipped", "FLASHQuant reads finished output")

    state, caption, detail = run_state(workflow_dir)
    if state != "done":
        return Step("Run", state, caption, detail or "")

    # One execution produces one dataset PER INPUT FILE, ids are
    # "<basename>_<timestamp>". Matching is a prefix match and is fragile by
    # nature: if it is ambiguous, fall back to done rather than report a wrong
    # count.
    produced = _produced_for(file_manager, spec, selected_inputs)
    if produced is not None and 0 < produced < len(selected_inputs):
        return Step("Run", "partial",
                    f"{produced} of {len(selected_inputs)} files produced results")
    return Step("Run", "done", caption, detail or "")


def _explore_step(spec, file_manager):
    # Never gated on a run this app performed: adding finished output is
    # equally valid.
    datasets = file_manager.get_results_list(spec.required_tags, partial=True)
    n = len(datasets)
    if n == 0:
        return Step("Explore", "todo", "No datasets yet", page=spec.viewer_page)

    # The refusal REASON is already computed per field by the preset
    # availability code. Show the count here and let the Viewer state the
    # reason — do not duplicate refusal text in two places.
    if not any_preset_available(spec, file_manager, datasets):
        return Step("Explore", "partial",
                    f"{n} dataset, no view available" if n == 1
                    else f"{n} datasets, no view available",
                    page=spec.viewer_page)

    return Step("Explore", "done",
                "1 dataset ready" if n == 1 else f"{n} datasets ready",
                page=spec.viewer_page)


# ---------------------------------------------------------------- filled in here

def any_preset_available(spec, file_manager, datasets):
    """Reuse src/presets.py rather than re-deriving availability.

    The Viewer and the preset page already refuse a preset per field with a
    reason; deriving it a second time here would let the banner and the Viewer
    disagree. FLASHQuant has no presets at all — a dataset is simply viewable.
    """
    if not presets_mod.PRESETS.get(spec.name):
        return True
    has_sequence = bool(st.session_state.get("input_sequence"))
    for dataset in datasets:
        for _preset, ok, _reason in presets_mod.for_dataset(
            spec.name, file_manager, dataset, has_sequence
        ):
            if ok:
                return True
    return False


def _produced_for(file_manager, spec, selected_inputs):
    """How many selected inputs have at least one dataset.

    A run mints "<basename>_<timestamp>" per input file, so this is a prefix
    match and fragile by nature. Returns None when the match is ambiguous — one
    dataset prefixing two different inputs — and the caller then reports plain
    'done' rather than a number that might be wrong.
    """
    if not selected_inputs:
        return None
    try:
        datasets = file_manager.get_results_list(spec.required_tags, partial=True)
    except Exception:
        return None

    produced = 0
    for name in selected_inputs:
        stem = Path(str(name)).stem
        matches = [d for d in datasets if d == stem or d.startswith(stem)]
        # Ambiguous: this stem is a prefix of another selected input's stem.
        if any(stem != other and Path(str(other)).stem.startswith(stem)
               for other in selected_inputs):
            return None
        if matches:
            produced += 1
    return produced


def selected_names(params, key):
    """The selected entries for a params key, as bare names."""
    value = (params or {}).get(key) or []
    if not isinstance(value, list):
        value = [value]
    return [Path(str(v)).name for v in value]


def _listing(files_dir):
    return input_listing(files_dir)


def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"
