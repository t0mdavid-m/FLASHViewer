"""The View presets page, shared by FLASHDeconv and FLASHTnT.

Replaces hand-building a grid for the common cases. A custom layout is still
reachable, but it is no longer the only way in.
"""
import json
from pathlib import Path

import streamlit as st

from src import presets as presets_mod
from src.workflow.FileManager import FileManager


def _param_key(tool):
    return f"view_preset_{tool}"


def selected_preset_id(tool):
    """The preset the user picked, falling back to the tool's default."""
    return st.session_state.get(_param_key(tool)) or presets_mod.default_id(tool)


def selected_rows(tool):
    """The grid rows for the current preset, prerequisites already satisfied.

    Returns None when the user has a custom layout saved, so the viewer keeps
    using that.
    """
    preset = presets_mod.get(tool, selected_preset_id(tool))
    if preset is None:
        return None
    rows, _ = presets_mod.expand_prerequisites(tool, preset["rows"])
    return rows


def compare_count(tool):
    """How many datasets to show side by side. 1 means no comparison.

    This replaces the old '#Experiments to view at once' selectbox. It is a
    count rather than a list of ids because each slot keeps its own dataset
    selector in the viewer, exactly as before — the layout is shared, which is
    the whole point of a preset.
    """
    return int(st.session_state.get(f"compare_count_{tool}", 1) or 1)


# Every tool the app knows, not only the two with presets: this module is
# reached for FLASHQuant the moment anything iterates all three, and a KeyError
# here is a blank page rather than a message.
CACHE_DIRS = {
    "FLASHDeconv": "flashdeconv",
    "FLASHTnT": "flashtnt",
    "FLASHQuant": "flashquant",
}


def _cache_dir(tool):
    try:
        return CACHE_DIRS[tool]
    except KeyError:
        raise ValueError(f"unknown tool: {tool!r}") from None


def has_presets(tool):
    """FLASHQuant renders a single fixed grid and has no presets to choose."""
    return bool(presets_mod.PRESETS.get(tool))


def render(tool, required_tags):
    """Draw the page. `required_tags` are the fields a dataset needs to exist."""
    st.title("View presets")
    st.caption(
        "Pick the view that matches the question you are asking. "
        "Presets that need data this run does not have are shown greyed out, "
        "with the reason."
    )

    file_manager = FileManager(
        st.session_state["workspace"],
        Path(st.session_state["workspace"], _cache_dir(tool), "cache"),
    )
    datasets = file_manager.get_results_list(required_tags)

    if not datasets:
        st.info(
            "No datasets in this workspace yet. Run an analysis or upload "
            "FLASH\\* output, then come back to choose a view."
        )
        return

    dataset = st.selectbox("Dataset", datasets, key=f"preset_dataset_{tool}")
    has_sequence = bool(st.session_state.get("input_sequence"))
    current = selected_preset_id(tool)

    for preset, available, reason in presets_mod.for_dataset(
        tool, file_manager, dataset, has_sequence
    ):
        with st.container(border=True):
            head, action = st.columns([5, 1], vertical_alignment="center")
            is_current = preset["id"] == current
            head.markdown(f"**{preset['name']}**" + (" — current" if is_current else ""))
            head.caption(preset["description"])

            rows, _ = presets_mod.expand_prerequisites(tool, preset["rows"])
            head.caption(
                " · ".join(
                    " | ".join(presets_mod.label(c) for c in row) for row in rows
                )
            )

            if available:
                head.caption(":green[Available]")
            else:
                head.caption(f":orange[Not available — {reason}]")

            if action.button(
                "Use", key=f"use_{tool}_{preset['id']}",
                disabled=not available or is_current,
            ):
                st.session_state[_param_key(tool)] = preset["id"]
                # A preset and a hand-built layout cannot both be in charge.
                st.session_state.pop(_saved_key(tool), None)
                st.rerun()

    st.divider()

    # Replaces the old "#Experiments to view at once" selectbox, which lived in
    # the layout editor this page replaced. 1 is the default and the common case.
    st.selectbox(
        "Datasets to compare side by side",
        [1, 2, 3, 4, 5],
        key=f"compare_count_{tool}",
        help="Each slot gets its own dataset selector in the Viewer and shows "
             "the same preset, so the grids line up.",
    )

    st.divider()
    _render_interchange(tool)


def _saved_key(tool):
    return "saved_layout_setting" if tool == "FLASHDeconv" else "saved_layout_setting_tagger"


def _render_interchange(tool):
    """Import/export, kept compatible with the old settings file plus a tool tag."""
    with st.expander("Import / export a layout"):
        st.caption(
            "Exported layouts now record which tool they belong to. Importing a "
            "layout built for the other tool is refused rather than crashing on "
            "an unknown component name."
        )

        rows = selected_rows(tool) or []
        st.download_button(
            "Export current view",
            data=json.dumps({"tool": tool, "layout": [rows]}, indent=2),
            file_name="FLASHViewer_layout_settings.json",
            mime="application/json",
            disabled=not rows,
        )

        uploaded = st.file_uploader("Import a layout", type="json", key=f"import_{tool}")
        if uploaded is not None:
            try:
                payload = json.load(uploaded)
            except json.JSONDecodeError as exc:
                st.error(f"Not valid JSON: {exc}")
                return

            # Old files are a bare list of experiments and carry no tool tag.
            if isinstance(payload, dict):
                if payload.get("tool") not in (None, tool):
                    st.error(
                        f"That layout was built for {payload['tool']}, not {tool}."
                    )
                    return
                layout = payload.get("layout") or []
            else:
                layout = payload

            if not layout or not layout[0]:
                st.error("That file contains no layout.")
                return

            prereqs = presets_mod.PREREQUISITES.get(tool, {})
            known = set(prereqs) | set(prereqs.values())
            unknown = [
                c for row in layout[0] for c in row
                if c not in known and c not in _EXTRA_COMPONENTS.get(tool, set())
            ]
            if unknown:
                st.error(f"Unknown component(s) for {tool}: {', '.join(sorted(set(unknown)))}")
                return

            repaired, added = presets_mod.expand_prerequisites(tool, layout[0])
            st.session_state[_saved_key(tool)] = [repaired]
            st.session_state.pop(_param_key(tool), None)
            if added:
                st.toast(f"Added missing prerequisite(s): {', '.join(added)}")
            st.success("Layout imported.")


# Components with no prerequisite of their own, so absent from PREREQUISITES.
_EXTRA_COMPONENTS = {
    "FLASHDeconv": {"ms1_raw_heatmap", "ms1_deconv_heat_map", "scan_table", "fdr_plot"},
    "FLASHTnT": {"protein_table"},
}
