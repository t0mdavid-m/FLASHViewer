import numpy as np
import pandas as pd
import streamlit as st

from pathlib import Path

from src.common.common import page_setup, save_params
from src.masstable import getMSSignalDF, getSpectraTableDF
from src.components import PlotlyHeatmap, PlotlyLineplot, Plotly3Dplot, Tabulator, SequenceView, InternalFragmentMap, \
                           FlashViewerComponent, flash_viewer_grid_component, FDRPlotly
from src.sequence import getFragmentDataFromSeq, getInternalFragmentDataFromSeq
from src.workflow.FileManager import FileManager
from src import preset_page


DEFAULT_LAYOUT = [['ms1_deconv_heat_map'], ['scan_table', 'mass_table'],
                  ['anno_spectrum', 'deconv_spectrum'], ['3D_SN_plot']]


def sendDataToJS(selected_data, layout_info_per_exp, grid_key='flash_viewer_grid'):

    # Get data
    results = file_manager.get_results(
        selected_data, 
        ['anno_dfs', 'deconv_dfs', 'parsed_tsv_file_ms1', 'parsed_tsv_file_ms2'],
        partial=True
    )
    spec_df = results['deconv_dfs']
    anno_df = results['anno_dfs']

    fdr_dfs = []
    if 'parsed_tsv_file_ms1' in results:
        fdr_dfs.append(results['parsed_tsv_file_ms1'])
    if 'parsed_tsv_file_ms2' in results:
        fdr_dfs.append(results['parsed_tsv_file_ms2'])
    if len(fdr_dfs) > 0:
        fdr_dfs = pd.concat(fdr_dfs, axis=0, ignore_index=True)
    else:
        fdr_dfs = None

    components = []
    data_to_send = {}
    per_scan_contents = {'mass_table': False, 'anno_spec': False, 'deconv_spec': False, '3d': False}
    for row in layout_info_per_exp:
        components_of_this_row = []
        for col_index, comp_name in enumerate(row):
            component_arguments = None

            # prepare component arguments
            if comp_name == 'ms1_raw_heatmap':
                data_to_send['raw_heatmap_df'] = getMSSignalDF(anno_df)
                component_arguments = PlotlyHeatmap(title="Raw MS1 Heatmap")
            elif comp_name == 'ms1_deconv_heat_map':
                data_to_send['deconv_heatmap_df'] = getMSSignalDF(spec_df)
                component_arguments = PlotlyHeatmap(title="Deconvolved MS1 Heatmap")
            elif comp_name == 'scan_table':
                data_to_send['per_scan_data'] = getSpectraTableDF(spec_df)
                component_arguments = Tabulator('ScanTable')
            elif comp_name == 'deconv_spectrum':
                per_scan_contents['deconv_spec'] = True
                component_arguments = PlotlyLineplot(title="Deconvolved Spectrum")
            elif comp_name == 'anno_spectrum':
                per_scan_contents['anno_spec'] = True
                component_arguments = PlotlyLineplot(title="Annotated Spectrum")
            elif comp_name == 'mass_table':
                per_scan_contents['mass_table'] = True
                component_arguments = Tabulator('MassTable')
            elif comp_name == '3D_SN_plot':
                per_scan_contents['3d'] = True
                component_arguments = Plotly3Dplot(title="Precursor Signals")
            elif comp_name == 'sequence_view':
                data_to_send['sequence_data'] = {0: getFragmentDataFromSeq(st.session_state.input_sequence)}
                component_arguments = SequenceView()
            elif comp_name == 'internal_fragment_map':
                data_to_send['internal_fragment_data'] = {0: getInternalFragmentDataFromSeq(st.session_state.input_sequence)}
                component_arguments = InternalFragmentMap()
            elif comp_name == 'fdr_plot':
                if fdr_dfs is not None:
                    ecdf_target, ecdf_decoy = ecdf(fdr_dfs)
                    data_to_send['ecdf_target'] = ecdf_target
                    data_to_send['ecdf_decoy'] = ecdf_decoy
                component_arguments = FDRPlotly()

            components_of_this_row.append(FlashViewerComponent(component_arguments))
        components.append(components_of_this_row)

    if any(per_scan_contents.values()):
        scan_table = data_to_send['per_scan_data']
        dfs = [scan_table]
        for key, exist in per_scan_contents.items():
            if not exist: continue

            if key == 'mass_table':
                tmp_df = spec_df[['mzarray', 'intarray', 'MinCharges', 'MaxCharges', 'MinIsotopes', 'MaxIsotopes',
                                  'cos', 'snr', 'qscore']].copy()
                tmp_df.rename(columns={'mzarray': 'MonoMass', 'intarray': 'SumIntensity', 'cos': 'CosineScore',
                                       'snr': 'SNR', 'qscore': 'QScore'},
                              inplace=True)
            elif key == 'deconv_spec':
                if per_scan_contents['mass_table']: continue  # deconv_spec shares same data with mass_table

                tmp_df = spec_df[['mzarray', 'intarray']].copy()
                tmp_df.rename(columns={'mzarray': 'MonoMass', 'intarray': 'SumIntensity'}, inplace=True)
            elif key == 'anno_spec':
                tmp_df = anno_df[['mzarray', 'intarray']].copy()
                tmp_df.rename(columns={'mzarray': 'MonoMass_Anno', 'intarray': 'SumIntensity_Anno'}, inplace=True)
            elif key == '3d':
                tmp_df = spec_df[['PrecursorScan', 'SignalPeaks', 'NoisyPeaks']].copy()
            else:  # shouldn't come here
                continue

            dfs.append(tmp_df)
        data_to_send['per_scan_data'] = pd.concat(dfs, axis=1)

    # if Internal fragment map was selected, but sequence view was not
    if ('internal_fragment_data' in data_to_send) and ('sequence_data' not in data_to_send):
        data_to_send['sequence_data'] = {0 : getFragmentDataFromSeq(st.session_state.input_sequence)}
    data_to_send['dataset'] = selected_data

    flash_viewer_grid_component(components=components, data=data_to_send, component_key=grid_key)

def ecdf(df):
    target_qscores = df[df['TargetDecoyType'] == 0]['Qscore']
    decoy_qscores = df[df['TargetDecoyType'] > 0]['Qscore']

    ecdf_target = pd.DataFrame({
        'x' : np.sort(target_qscores),
        'y' : np.arange(1, len(target_qscores) + 1) / len(target_qscores)
    })
    ecdf_decoy = pd.DataFrame({
        'x' : np.sort(decoy_qscores),
        'y' : np.arange(1, len(decoy_qscores) + 1) / len(decoy_qscores)
    })
    return ecdf_target, ecdf_decoy

def setSequenceViewInDefaultView():
    if 'input_sequence' in st.session_state and st.session_state.input_sequence:
        global DEFAULT_LAYOUT
        DEFAULT_LAYOUT = DEFAULT_LAYOUT + [['sequence_view']]


def select_experiment():
    st.session_state.selected_experiment0 = st.session_state.selected_experiment_dropdown
    # Slot count is whichever is larger: a custom layout's slots, or the
    # comparison count set on the presets page.
    custom = st.session_state.get("saved_layout_setting")
    slots = max(len(custom) if custom else 1, preset_page.compare_count("FLASHDeconv"))
    for exp_index in range(1, slots):
        if st.session_state.get(f'selected_experiment_dropdown_{exp_index}') is None:
            continue
        st.session_state[f"selected_experiment{exp_index}"] = st.session_state[f'selected_experiment_dropdown_{exp_index}']





# page initialization
params = page_setup()

st.title("Viewer")
setSequenceViewInDefaultView()

# Get available results
file_manager = FileManager(
    st.session_state["workspace"],
    Path(st.session_state['workspace'], 'flashdeconv', 'cache')
)
results = file_manager.get_results_list(['deconv_dfs', 'anno_dfs'])

### if no input file is given, show blank page
if len(results) == 0:
    # Not an error, and not conditional on a run this app performed:
    # finished FLASH* output added under 'Add results' is equally valid.
    st.info(
        "**Nothing to explore in this workspace yet.**\n\n"
        "Either run an analysis on the FLASHDeconv **Workflow** page, or add "
        "finished FLASH\\* output under its **Add results** tab — the viewer "
        "treats both the same."
    )
    st.stop()

# Map names to index
name_to_index = {n : i for i, n in enumerate(results)}

### for only single experiment on one view
st.selectbox(
    "choose experiment", results, 
    key="selected_experiment_dropdown", 
    index=name_to_index[st.session_state.selected_experiment0] if 'selected_experiment0' in st.session_state else None,
    on_change=select_experiment
)

if 'selected_experiment0' in st.session_state:
    # A saved custom layout wins; otherwise the chosen view preset, whose
    # prerequisites are already expanded. DEFAULT_LAYOUT remains the last resort.
    layout_info = preset_page.selected_rows("FLASHDeconv") or DEFAULT_LAYOUT
    if "saved_layout_setting" in st.session_state:  # hand-built layout
        layout_info = st.session_state["saved_layout_setting"][0]
    with st.spinner('Loading component...'):
        sendDataToJS(st.session_state.selected_experiment0, layout_info)


### for multiple experiments on one view
# Slot count comes from the presets page. A hand-built layout may still carry
# its own per-slot layouts, in which case those win, which is what the old
# "#Experiments to view at once" produced.
custom = st.session_state.get("saved_layout_setting")
slot_count = len(custom) if custom and len(custom) > 1 else preset_page.compare_count("FLASHDeconv")

for exp_index in range(1, slot_count):
    st.divider()  # horizontal line

    st.selectbox(
        "choose experiment", results,
        key=f'selected_experiment_dropdown_{exp_index}',
        index = name_to_index[st.session_state[f'selected_experiment{exp_index}']] if f'selected_experiment{exp_index}' in st.session_state else None,
        on_change=select_experiment
    )
    # if #experiment input files are less than #layouts, all the pre-selection will be the first experiment
    if f"selected_experiment{exp_index}" in st.session_state:
        if custom and exp_index < len(custom):
            layout_info = custom[exp_index]
        else:
            layout_info = preset_page.selected_rows("FLASHDeconv") or DEFAULT_LAYOUT
        with st.spinner('Loading component...'):
            sendDataToJS(st.session_state["selected_experiment%d" % exp_index], layout_info, 'flash_viewer_grid_%d' % exp_index)

save_params(params)
