import streamlit as st

from pathlib import Path

from src.Workflow import QuantWorkflow
from src.parse.quant import parseQuant
from src.common.common import page_setup, save_params
from src.data_surface import data_surface
from src.tools import TOOLS
from src import wizard

params = page_setup()

wf = QuantWorkflow()
spec = TOOLS["FLASHQuant"]

st.title("Add data")

# The wizard banner sits above everything: FLASHQuant has no Method or Run, and
# both render as "Not applicable" rather than being absent.
_files_dir = Path(wf.workflow_dir, "input-files", "mzML-files")
wizard.banner(wizard.build_steps(
    spec, wf, wf.params, _files_dir,
    wizard.selected_names(wf.params, "mzML-files")))


def parse_pending():
    """Parse whatever has been added but not yet parsed.

    Kept per-tool: parseQuant takes an optional conflict file the other two
    have no equivalent for, and the st.status phase belongs to the page that
    knows what it is parsing.
    """
    input_files = set(wf.file_manager.get_results_list(['quant_tsv', 'trace_tsv']))
    parsed = set(wf.file_manager.get_results_list(['quant_dfs']))
    conflicts = set(wf.file_manager.get_results_list(['conflict_tsv']))
    parsed_conflicts = set(wf.file_manager.get_results_list(['conflict_resolution_dfs']))
    pending = sorted((input_files - parsed) | ((conflicts - parsed_conflicts) & input_files))
    if not pending:
        return

    status = st.status(f"Parsing {len(pending)} dataset(s)…", expanded=True)
    progress = status.progress(0.0)
    for i, dataset_id in enumerate(pending):
        status.write(f"Parsing {dataset_id} ({i + 1}/{len(pending)})")
        results = wf.file_manager.get_results(dataset_id, ['quant_tsv', 'trace_tsv'])

        # FLASHQuant needs both. get_results returns only the tags whose column
        # exists, so indexing directly raised a bare KeyError — the same bug
        # FLASHTnT had.
        missing = [t for t in ('quant_tsv', 'trace_tsv') if t not in results]
        if missing:
            status.write(
                f":orange[Skipped {dataset_id} — needs both files; "
                f"missing: {', '.join(missing)}]")
            progress.progress((i + 1) / len(pending))
            continue

        conflict = None
        if wf.file_manager.result_exists(dataset_id, 'conflict_tsv'):
            conflict = wf.file_manager.get_results(
                dataset_id, ['conflict_tsv'])['conflict_tsv']

        for k, v in parseQuant(results['quant_tsv'], results['trace_tsv'],
                               conflict).items():
            wf.file_manager.store_data(dataset_id, k, v)
        progress.progress((i + 1) / len(pending))

    status.update(label=f"Parsed {len(pending)} dataset(s)", state="complete",
                  expanded=False)


data_surface(
    spec, wf, parse_pending,
    example_dir=Path("example-data", "flashquant"),
    example_globs=(
        ('*.fq.tsv', 'quant_tsv'),
        ('*.fq.mts.tsv', 'trace_tsv'),
        ('*.fq_shared.tsv', 'conflict_tsv'),
    ),
)

save_params(params)
