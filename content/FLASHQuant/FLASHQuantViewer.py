import streamlit as st

from pathlib import Path

from src.workflow.FileManager import FileManager
from src.common.common import page_setup, save_params
from src.components import flash_viewer_grid_component, FlashViewerComponent, FLASHQuant


# page initialization
params = page_setup()

st.title('Viewer')

# Get available results
file_manager = FileManager(
    st.session_state["workspace"],
    Path(st.session_state['workspace'], 'flashquant', 'cache')
)
results = file_manager.get_results_list(
    ['quant_dfs']
)

### if no input file is given, show blank page
if len(results) == 0:
    # Not an error, and not conditional on a run this app performed:
    # finished FLASH* output added under 'Add results' is equally valid.
    st.info(
        "**Nothing to explore in this workspace yet.**\n\n"
        "Either run an analysis on the FLASHQuant **Workflow** page, or add "
        "finished FLASH\\* output under its **Add results** tab — the viewer "
        "treats both the same."
    )
    st.stop()

# Map names to index
name_to_index = {n : i for i, n in enumerate(results)}


# for only single experiment on one view
st.selectbox("choose experiment", results, key="selected_experiment0_quant")
selected_exp0 = st.session_state.selected_experiment0_quant

# Get data
quant_df = file_manager.get_results(selected_exp0, 'quant_dfs')['quant_dfs']

component = [[FlashViewerComponent(FLASHQuant())]]
flash_viewer_grid_component(components=component, data={'quant_data': quant_df, 'dataset': selected_exp0}, component_key='flash_viewer_grid')

save_params(params)
