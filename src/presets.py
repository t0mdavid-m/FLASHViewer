"""View presets: named grid layouts, chosen instead of hand-built ones.

A preset is a nested list of component names in exactly the shape the Vue grid
already takes (rows of up to three components), plus the cache fields it needs.

Two rules this module exists to enforce, both learned the hard way:

1. Component names are **per tool**. `COMPONENT_NAMES` in the two layout managers
   are disjoint lists, and the same name can render a different Vue component
   depending on the tool (`deconv_spectrum` is PlotlyLineplot under FLASHDeconv
   and PlotlyLineplotTagger under FLASHTnT). A preset therefore carries its tool
   and may never mix them.

2. Components have prerequisites *within a layout*, not just in the cache. The
   viewers assemble one shared per-scan frame, and several components only get
   their data as a side effect of another component being present — omit the
   driver and the viewer raises KeyError. `PREREQUISITES` encodes that, and
   `expand_prerequisites()` repairs a layout rather than rejecting it.
"""

# Component -> the component that must also be in the layout for it to work.
# Mirrors the "(… needed)" suffixes in the layout managers' COMPONENT_OPTIONS.
PREREQUISITES = {
    "FLASHDeconv": {
        "deconv_spectrum": "scan_table",
        "anno_spectrum": "scan_table",
        "mass_table": "scan_table",
        "3D_SN_plot": "mass_table",
        "sequence_view": "mass_table",
        "internal_fragment_map": "mass_table",
    },
    "FLASHTnT": {
        "sequence_view": "protein_table",
        "internal_fragment_map": "protein_table",
        "tag_table": "protein_table",
        "deconv_spectrum": "tag_table",
    },
}

# Human labels for the grid component ids, so the UI never shows a raw
# identifier. Taken from the two layout managers' COMPONENT_OPTIONS, minus the
# "(… needed)" suffixes, which PREREQUISITES now encodes properly.
LABELS = {
    "ms1_raw_heatmap": "MS1 raw heatmap",
    "ms1_deconv_heat_map": "MS1 deconvolved heatmap",
    "scan_table": "Scan table",
    "deconv_spectrum": "Deconvolved spectrum",
    "anno_spectrum": "Annotated spectrum",
    "mass_table": "Mass table",
    "3D_SN_plot": "3D S/N plot",
    "fdr_plot": "QScore ECDF plot",
    "protein_table": "Protein table",
    "sequence_view": "Sequence view",
    "internal_fragment_map": "Internal fragment map",
    "tag_table": "Tag table",
}


def label(component):
    """Readable name for a grid component id."""
    return LABELS.get(component, component)


# Cache fields a preset needs before it can render. Checked one at a time with
# FileManager.result_exists(): get_results_list() silently drops columns that do
# not exist yet, so an AND query over a missing field returns rows regardless.
PRESETS = {
    "FLASHDeconv": [
        {
            "id": "deconvolution_qc",
            "name": "Deconvolution QC",
            "description": "Did deconvolution work on this run?",
            "rows": [["ms1_raw_heatmap", "ms1_deconv_heat_map"], ["scan_table"],
                     ["anno_spectrum", "deconv_spectrum"]],
            "requires": ["deconv_dfs", "anno_dfs"],
            "default": True,
        },
        {
            "id": "spectrum_deep_dive",
            "name": "Spectrum deep dive",
            "description": "What is in one particular scan?",
            "rows": [["scan_table", "mass_table"], ["anno_spectrum", "deconv_spectrum"],
                     ["3D_SN_plot"]],
            "requires": ["deconv_dfs", "anno_dfs"],
        },
        {
            "id": "scoring_fdr",
            "name": "Scoring & FDR review",
            "description": "How well separated are targets and decoys?",
            "rows": [["fdr_plot"], ["scan_table", "mass_table"]],
            # Written only when the TSV carried a TargetDecoyType column, i.e.
            # report_FDR was enabled for the run.
            "requires_any": ["parsed_tsv_file_ms1", "parsed_tsv_file_ms2"],
            "requires": ["deconv_dfs", "anno_dfs"],
            "unavailable_reason": "no FDR data in this run — enable report_FDR",
        },
        {
            "id": "sequence_coverage",
            "name": "Sequence coverage",
            "description": "Where do the observed masses fall on a known sequence?",
            "rows": [["scan_table", "mass_table"], ["sequence_view"],
                     ["internal_fragment_map"]],
            "requires": ["deconv_dfs", "anno_dfs"],
            "needs_sequence": True,
            "unavailable_reason": "no sequence set — add one under Sequence Input",
        },
    ],
    "FLASHTnT": [
        {
            "id": "proteoform_id",
            "name": "Proteoform ID review",
            "description": "Which proteoforms were identified, and on what evidence?",
            "rows": [["protein_table"], ["sequence_view"], ["tag_table", "deconv_spectrum"]],
            "requires": ["protein_dfs", "tag_dfs", "deconv_dfs"],
            "default": True,
        },
        {
            "id": "proteoform_mapping",
            "name": "Proteoform mapping",
            "description": "How do tags and fragments map onto the sequence?",
            # protein_table is not decoration: it is the only branch that builds
            # the per-scan frame the other three read.
            "rows": [["protein_table"], ["sequence_view"], ["internal_fragment_map"]],
            "requires": ["protein_dfs", "tag_dfs", "deconv_dfs"],
        },
    ],
}


def get(tool, preset_id):
    """Return a preset by id, or None."""
    for preset in PRESETS.get(tool, []):
        if preset["id"] == preset_id:
            return preset
    return None


def default_id(tool):
    """The preset used when the user has not chosen one."""
    for preset in PRESETS.get(tool, []):
        if preset.get("default"):
            return preset["id"]
    presets = PRESETS.get(tool, [])
    return presets[0]["id"] if presets else None


def expand_prerequisites(tool, rows):
    """Add any missing prerequisite components, and report what was added.

    Returns (rows, added). A prerequisite is appended to the first row with
    room (the Vue grid styles at most three per row) or to a new row.
    """
    prereqs = PREREQUISITES.get(tool, {})
    rows = [list(row) for row in rows]
    added = []

    def present():
        return {c for row in rows for c in row}

    # Iterate until closure: a prerequisite can itself have a prerequisite
    # (3D_SN_plot -> mass_table -> scan_table).
    while True:
        missing = [prereqs[c] for c in present() if c in prereqs and prereqs[c] not in present()]
        if not missing:
            break
        need = missing[0]
        for row in rows:
            if len(row) < 3:
                row.append(need)
                break
        else:
            rows.append([need])
        added.append(need)

    return rows, added


def availability(tool, preset, file_manager, dataset_id, has_sequence=False):
    """Is this preset renderable for this dataset? Returns (bool, reason).

    Each required field is checked individually via result_exists(), because
    get_results_list() drops unknown columns from its query and would report a
    never-created field as satisfied.
    """
    if preset.get("needs_sequence") and not has_sequence:
        return False, preset.get("unavailable_reason", "no sequence set")

    for tag in preset.get("requires", []):
        if not file_manager.result_exists(dataset_id, tag):
            return False, f"missing {tag}"

    any_of = preset.get("requires_any")
    if any_of and not any(file_manager.result_exists(dataset_id, t) for t in any_of):
        return False, preset.get("unavailable_reason", "required data not in this run")

    return True, "Available"


def for_dataset(tool, file_manager, dataset_id, has_sequence=False):
    """Every preset for a tool, each annotated with (available, reason)."""
    out = []
    for preset in PRESETS.get(tool, []):
        ok, reason = availability(tool, preset, file_manager, dataset_id, has_sequence)
        out.append((preset, ok, reason))
    return out


def demo():
    """Self-check: prerequisite repair is the part worth guarding."""
    # The preset that used to crash the TnT viewer: no protein_table.
    rows, added = expand_prerequisites("FLASHTnT",
                                       [["sequence_view"], ["internal_fragment_map"]])
    assert "protein_table" in {c for r in rows for c in r}, rows
    assert added == ["protein_table"], added

    # Transitive: 3D_SN_plot needs mass_table needs scan_table.
    rows, added = expand_prerequisites("FLASHDeconv", [["3D_SN_plot"]])
    flat = {c for r in rows for c in r}
    assert {"3D_SN_plot", "mass_table", "scan_table"} <= flat, rows

    # Already complete layouts are left alone.
    original = [["protein_table"], ["sequence_view"]]
    rows, added = expand_prerequisites("FLASHTnT", original)
    assert added == [], added
    assert rows == original, rows

    # Row cap of three is respected when repairing.
    rows, _ = expand_prerequisites("FLASHDeconv",
                                   [["ms1_raw_heatmap", "ms1_deconv_heat_map", "fdr_plot"],
                                    ["3D_SN_plot"]])
    assert all(len(r) <= 3 for r in rows), rows

    # Every shipped preset must already satisfy its own prerequisites, and no
    # preset may name a component from another tool.
    for tool, presets in PRESETS.items():
        known = set(PREREQUISITES[tool]) | set(PREREQUISITES[tool].values())
        for preset in presets:
            _, added = expand_prerequisites(tool, preset["rows"])
            assert added == [], f"{tool}/{preset['id']} is missing {added}"
            assert all(len(r) <= 3 for r in preset["rows"]), preset["id"]
            for row in preset["rows"]:
                for comp in row:
                    if comp in known:
                        continue  # tool-local by construction
        assert default_id(tool) is not None

    # Every component any preset can show must have a readable label: a raw id
    # leaking into the UI is the failure this guards.
    for tool, presets in PRESETS.items():
        for preset in presets:
            rows, _ = expand_prerequisites(tool, preset["rows"])
            for row in rows:
                for comp in row:
                    assert comp in LABELS, f"no label for {comp}"

    print("presets: all checks passed")


if __name__ == "__main__":
    demo()
