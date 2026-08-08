"""The shared add / list / remove surface, for one tool, on any deployment.

Replaces three near-identical copies. They had diverged — FLASHQuant's uploader
had no `type=` restriction and no parsing progress, FLASHDeconv's example loader
ignores `_spec2.tsv` — so this is written to preserve each tool's behaviour
through its ToolSpec rather than to average them.

`parse_pending` stays a per-tool callable: the three parse steps genuinely
differ (parseTnT's parameter names do not match its cache tags, so it is called
positionally), and the st.status progress phase belongs to the page that knows
what it is parsing.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from src.common.common import desktop_file_picker
from src.tools import record_intent
from src.workflow.StreamlitUI import DESKTOP
from src import confirm


def data_surface(spec, wf, parse_pending, example_dir=None, example_globs=()):
    """Add, list and remove for one tool. Returns the dataset ids on show."""
    _add_region(spec, wf, parse_pending, example_dir, example_globs)
    ids = _datasets_region(spec, wf)
    _remove_region(spec, wf, ids)
    return ids


def _store(spec, wf, files):
    """Route each file to its role by suffix, within this tool.

    The tool is never inferred from the filename: "_deconv.mzML" is accepted
    identically by FLASHDeconv and FLASHTnT, and FLASHQuant claims any
    remaining ".tsv". That is why Add is a per-tool surface.
    """
    stored, rejected = 0, []
    for file in files:
        name = getattr(file, "name", None) or Path(file).name
        routed = spec.dataset_id_for(name)
        if routed is None:
            rejected.append(name)
            continue
        dataset_id, name_tag = routed
        wf.file_manager.store_file(dataset_id, name_tag, file)
        stored += 1
    for name in rejected:
        st.warning(f"Not a {spec.name} output file: {name}")
    return stored


def _add_region(spec, wf, parse_pending, example_dir, example_globs):
    with st.container(border=True):
        st.subheader(f"Add {spec.name} output files")

        if DESKTOP:
            picked = desktop_file_picker(
                f"Add {spec.name} output files", list(spec.extensions),
                key=f"{spec.cache_subdir}_pick",
            )
            if picked:
                n = _store(spec, wf, picked)
                if n:
                    record_intent(wf.workflow_dir, "data",
                                  source="reference", count=n)
                    parse_pending()
                    st.rerun()
        else:
            with st.form(f"{spec.cache_subdir}_add", clear_on_submit=True):
                uploaded = st.file_uploader(
                    f"{spec.name} output files",
                    accept_multiple_files=True,
                    type=list(spec.extensions),
                )
                st.caption("Files are copied into this workspace.")
                if st.form_submit_button("Add files", type="primary"):
                    if not uploaded:
                        st.warning("Choose some files first.")
                    else:
                        if not isinstance(uploaded, list):
                            uploaded = [uploaded]   # online allows one file
                        n = _store(spec, wf, uploaded)
                        if n:
                            record_intent(wf.workflow_dir, "data",
                                          source="upload", count=n)
                            parse_pending()
                            st.rerun()

        # source="example" is what lets the wizard banner say "Example data
        # only" rather than claim the user chose these files.
        if example_dir and Path(example_dir).is_dir():
            if st.button("Load example data", key=f"{spec.cache_subdir}_ex"):
                n = 0
                for pattern, name_tag in example_globs:
                    for f in Path(example_dir).glob(pattern):
                        wf.file_manager.store_file(
                            f.name.replace(pattern[1:], ""), name_tag, f,
                            remove=False)
                        n += 1
                if n:
                    record_intent(wf.workflow_dir, "data",
                                  source="example", count=n)
                parse_pending()
                st.rerun()
        elif example_dir:
            st.caption("This build does not ship example data.")


def _datasets_region(spec, wf):
    """One row per dataset, one column per role — the three tables merged."""
    ids = set()
    for role in spec.roles:
        ids |= set(wf.file_manager.get_results_list([role.name_tag]))
    ids = sorted(ids)
    if not ids:
        st.caption("No datasets in this workspace yet.")
        return []

    table = {"Dataset": ids}
    for role in spec.roles:
        table[role.label] = [
            wf.file_manager.result_exists(i, role.name_tag) for i in ids
        ]
    st.markdown("**Datasets in this workspace**")
    st.dataframe(pd.DataFrame(table), hide_index=True)
    return ids


def _remove_region(spec, wf, ids):
    with st.expander("Remove datasets"):
        to_remove = st.multiselect("Select datasets", options=ids,
                                   key=f"{spec.cache_subdir}_rm")
        c1, c2 = st.columns(2)

        if c2.button("Remove selected", type="primary",
                     icon=":material/delete_forever:",
                     disabled=not to_remove, key=f"{spec.cache_subdir}_rm_go"):
            def _go():
                for dataset_id in to_remove:
                    wf.file_manager.remove_results(dataset_id)
                st.rerun()
            confirm.confirm_list(
                to_remove, _go,
                body="Removes these datasets from this workspace. Files you "
                     "added from your own disk are not deleted.")

        # Unbounded and unrecoverable: clear_cache() drops both tables and
        # rmtree's <cache>/files. It had no confirmation at all.
        if c1.button("Remove all", icon=":material/delete_forever:",
                     key=f"{spec.cache_subdir}_clear"):
            st.session_state[f"armed_clear_{spec.name}"] = True
        if st.session_state.get(f"armed_clear_{spec.name}"):
            def _clear():
                wf.file_manager.clear_cache()
                st.session_state.pop(f"armed_clear_{spec.name}", None)
                st.rerun()
            confirm.confirm_typed(
                title=f"Remove every {spec.name} dataset",
                body=f"This deletes every {spec.name} dataset in this "
                     "workspace, including parsed results. It cannot be undone.",
                phrase=spec.name,
                confirm_label=f"Remove all {spec.name} datasets",
                on_confirm=_clear,
            )
