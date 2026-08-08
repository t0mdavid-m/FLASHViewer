import pandas as pd
import streamlit as st

from pathlib import Path

from src.Workflow import DeconvWorkflow
from src.parse.deconv import parseDeconv
from src.common.common import page_setup, desktop_file_picker
from src.workflow.StreamlitUI import DESKTOP
from src import confirm


params = page_setup()

wf = DeconvWorkflow()

st.title('FLASHDeconv - Ultrafast Deconvolution')

# Wizard banner. Mounted ABOVE st.tabs deliberately: it must not sit inside a
# tab body, because st.tabs renders every body on load and execution() depends
# on that. State is derived in src/tools.py; nothing here constructs a
# FileManager for another tool.
from src import wizard
from src.tools import TOOLS
_spec = TOOLS["FLASHDeconv"]
_files_dir = Path(wf.workflow_dir, "input-files", "mzML-files")
_selected = wizard.selected_names(wf.params, "mzML-files")
wizard.banner(wizard.build_steps(_spec, wf, wf.params, _files_dir, _selected))

t = st.tabs(["**Data**", "**Method**", "**Run**", "**Add results**"])
with t[0]:
    wf.show_file_upload_section()

with t[1]:
    wf.show_parameter_section()

with t[2]:
    wf.show_execution_section()
with t[3]:

    def process_uploaded_files(uploaded_files):
        
        # Store all uploaded files
        for file in uploaded_files:
            if file.name.endswith("mzML"):
                if file.name.endswith('_deconv.mzML'):
                    wf.file_manager.store_file(
                        file.name.split('_deconv.mzML')[0], 'out_deconv_mzML', file
                    )
                elif file.name.endswith('_annotated.mzML'):
                    wf.file_manager.store_file(
                        file.name.split('_annotated.mzML')[0], 'anno_annotated_mzML', file
                    )
                else:
                    st.warning(f'Invalid file : {file.name}')
            elif file.name.endswith("tsv"):
                if file.name.endswith('_spec1.tsv'):
                    wf.file_manager.store_file(
                        file.name.split('_spec1.tsv')[0], 'spec1_tsv', file
                    )
                elif file.name.endswith('_spec2.tsv'):
                    wf.file_manager.store_file(
                        file.name.split('_spec2.tsv')[0], 'spec2_tsv', file
                    )
                else:
                    st.warning(f'Invalid file : {file.name}')
            else:
                st.warning(f'Invalid file : {file.name}')
        
        # Get the unparsed files
        input_files = set(wf.file_manager.get_results_list(['out_deconv_mzML', 'anno_annotated_mzML']))
        parsed_files = set(wf.file_manager.get_results_list(['deconv_dfs', 'anno_dfs']))
        unparsed_files = input_files - parsed_files

        # Get the unpared tsv files
        ms1_tsv_files = set(wf.file_manager.get_results_list(['spec1_tsv']))
        parsed_ms1_tsv_files = set(wf.file_manager.get_results_list(['parsed_tsv_file_ms1']))
        ms2_tsv_files = set(wf.file_manager.get_results_list(['spec2_tsv']))
        parsed_ms2_tsv_files = set(wf.file_manager.get_results_list(['parsed_tsv_file_ms2']))
        unparsed_tsv_files = (
            (
                (ms1_tsv_files - parsed_ms1_tsv_files) 
                | (ms2_tsv_files - parsed_ms2_tsv_files)
            ) & input_files
        )

        # Process unparsed datasets. Parsing is a phase of the work, not a
        # silent gap after it: on real data this runs for minutes.
        pending = sorted(unparsed_files | unparsed_tsv_files)
        if pending:
            _status = st.status(f"Parsing {len(pending)} dataset(s)…", expanded=True)
            _progress = _status.progress(0.0)
        for _i, unparsed_dataset in enumerate(pending):
            _status.write(f"Parsing {unparsed_dataset} ({_i + 1}/{len(pending)})")
            results = wf.file_manager.get_results(
                unparsed_dataset, 
                ['out_deconv_mzML', 'anno_annotated_mzML', 
                 'spec1_tsv', 'spec2_tsv'],
                 partial=True
            )

            parsed_data = parseDeconv(**results)

            for k, v in parsed_data.items():
                wf.file_manager.store_data(unparsed_dataset, k, v)
            _progress.progress((_i + 1) / len(pending))

        if pending:
            _status.update(label=f"Parsed {len(pending)} dataset(s)", state="complete",
                           expanded=False)

    # make directory to store deconv and anno mzML files & initialize data storage
    tabs = st.tabs(["File Upload", "Example Data"])

    # Load Example Data
    with tabs[1]:
        st.markdown("An example truncated file from the ThermoFisher Pierce Intact Protein Standard Mix dataset.")
        _, c2, _ = st.columns(3)
        if c2.button("Load Example Data", type="primary"):
            # loading and copying example files into default workspace
            for filename_postfix, name_tag in zip(
                ['*_deconv.mzML', '*_annotated.mzML', '*_spec1.tsv'],
                ["out_deconv_mzML", "anno_annotated_mzML", "spec1_tsv"]
            ):
                for file in Path("example-data", "flashdeconv").glob(filename_postfix):
                    wf.file_manager.store_file(
                        file.name.replace(filename_postfix[1:], ''), 
                        name_tag, file, remove=False
                    )
            process_uploaded_files([])
            st.success("Example files loaded!")

    with tabs[0]:
        st.subheader("**Add FLASHDeconv output files (\*_annotated.mzML & \*_deconv.mzML) or spec1/2 TSV files (ECDF Plot only)**")
        st.info(
            """
            **How to add files**

            1. Browse files on your computer or drag and drops files
            2. Click the **Add the uploaded files** button to use them in the workflows

            Select data for analysis from the uploaded files shown below.

            **Make sure that the same number of deconvolved and annotated mzML files are uploaded!**
            """
        )
        if DESKTOP:
            # No upload step: reference the files where they already are.
            picked = desktop_file_picker(
                "Add FLASHDeconv output files", ["mzML", "tsv"], key="fd_pick"
            )
            if picked:
                process_uploaded_files(picked)
                st.success(f"Added {len(picked)} file(s).")
                st.rerun()
        else:
          with st.form('input_files', clear_on_submit=True):
            uploaded_files = st.file_uploader(
                "FLASHDeconv output mzML files or TSV files", accept_multiple_files=True, type=["mzML", "tsv"]
            )
            _, c2, _ = st.columns(3)
            if c2.form_submit_button("Add files to workspace", type="primary"):
                if uploaded_files:
                    # A list of files is required, since online allows only single upload, create a list
                    if type(uploaded_files) != list:
                        uploaded_files = [uploaded_files]

                    # opening file dialog and closing without choosing a file results in None upload
                    process_uploaded_files(uploaded_files)
                    st.success("Successfully added uploaded files!")
                else:
                    st.warning("Upload some files before adding them.")

    # File Upload Table
    experiments = (
        set(wf.file_manager.get_results_list(['spec1_tsv']))
        | set(wf.file_manager.get_results_list(['spec2_tsv']))
        | set(wf.file_manager.get_results_list(['out_deconv_mzML']))
        | set(wf.file_manager.get_results_list(['anno_annotated_mzML']))
    )
    table = {
        'Experiment Name' : [],
        'Deconvolved Files' : [],
        'Annotated Files' : [],
        '(MS1 TSV Files)' : [],
        '(MS2 TSV Files)' : [],
    }
    for experiment in experiments:
        table['Experiment Name'].append(experiment)

        if wf.file_manager.result_exists(experiment, 'out_deconv_mzML'):
            table['Deconvolved Files'].append(True)
        else:
            table['Deconvolved Files'].append(False)

        if wf.file_manager.result_exists(experiment, 'anno_annotated_mzML'):
            table['Annotated Files'].append(True)
        else:
            table['Annotated Files'].append(False)

        if wf.file_manager.result_exists(experiment, 'spec1_tsv'):
            table['(MS1 TSV Files)'].append(True)
        else:
            table['(MS1 TSV Files)'].append(False)
        if wf.file_manager.result_exists(experiment, 'spec2_tsv'):
            table['(MS2 TSV Files)'].append(True)
        else:
            table['(MS2 TSV Files)'].append(False)

    st.markdown('**Uploaded experiments in current workspace**')
    st.dataframe(pd.DataFrame(table))

    # Remove files
    with st.expander("Remove datasets"):
        to_remove = st.multiselect(
            "select files", options=experiments
        )
        c1, c2 = st.columns(2)
        if c2.button(
                "Remove **selected**", type="primary", disabled=not any(to_remove)
        ):
            for dataset_id in to_remove:
                wf.file_manager.remove_results(dataset_id)
            st.rerun()

        # Unbounded and unrecoverable: clear_cache() drops both SQLite tables and
        # rmtree's <cache>/files. It had no confirmation at all.
        if c1.button("Remove **all**", icon=":material/delete_forever:"):
            st.session_state["armed_clear_FLASHDeconv"] = True
        if st.session_state.get("armed_clear_FLASHDeconv"):
            def _clear_FLASHDeconv():
                wf.file_manager.clear_cache()
                st.session_state.pop("armed_clear_FLASHDeconv", None)
                st.rerun()
            confirm.confirm_typed(
                title="Remove every FLASHDeconv dataset",
                body="This deletes every dataset in this workspace for FLASHDeconv, "
                     "including parsed results. It cannot be undone.",
                phrase="FLASHDeconv",
                confirm_label="Remove all FLASHDeconv datasets",
                on_confirm=_clear_FLASHDeconv,
            )
