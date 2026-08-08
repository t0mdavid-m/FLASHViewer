import pandas as pd
import streamlit as st

from pathlib import Path

from src.parse.tnt import parseTnT
from src.Workflow import TagWorkflow
from src.common.common import page_setup, desktop_file_picker
from src.workflow.StreamlitUI import DESKTOP
from src import confirm


params = page_setup()

wf = TagWorkflow()

st.title('FLASHTnT - Tag and Extend')

# Wizard banner. Mounted ABOVE st.tabs deliberately: it must not sit inside a
# tab body, because st.tabs renders every body on load and execution() depends
# on that. State is derived in src/tools.py; nothing here constructs a
# FileManager for another tool.
from src import wizard
from src.tools import TOOLS
_spec = TOOLS["FLASHTnT"]
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
                if file.name.endswith('_tagged.tsv'):
                    wf.file_manager.store_file(
                        file.name.split('_tagged.tsv')[0], 'tags_tsv', file
                    )
                elif file.name.endswith('_protein.tsv'):
                    wf.file_manager.store_file(
                        file.name.split('_protein.tsv')[0], 'protein_tsv', file
                    )
                else:
                    st.warning(f'Invalid file : {file.name}')
            else:
                st.warning(f'Invalid file : {file.name}')
        
        # Get the unparsed files
        input_files = set(wf.file_manager.get_results_list(
            ['out_deconv_mzML', 'anno_annotated_mzML', 'tags_tsv', 'protein_tsv']
        ))
        parsed_files = set(wf.file_manager.get_results_list(
            ['deconv_dfs', 'anno_dfs', 'tag_dfs', 'protein_dfs']
        ))
        unparsed_files = input_files - parsed_files

        # Process unparsed datasets. Parsing is a phase of the work, not a
        # silent gap after it: on real data this runs for minutes.
        pending = sorted(unparsed_files)
        if pending:
            _status = st.status(f"Parsing {len(pending)} dataset(s)…", expanded=True)
            _progress = _status.progress(0.0)
        REQUIRED = ['out_deconv_mzML', 'anno_annotated_mzML', 'tags_tsv', 'protein_tsv']
        for _i, unparsed_dataset in enumerate(pending):
            _status.write(f"Parsing {unparsed_dataset} ({_i + 1}/{len(pending)})")
            results = wf.file_manager.get_results(unparsed_dataset, REQUIRED)

            # get_results only returns tags whose column exists, and
            # get_results_list drops absent columns from its AND query — so a
            # dataset with only the two mzMLs reaches this point and used to
            # raise a bare KeyError: 'tags_tsv'. FLASHTnT needs all four.
            missing = [tag for tag in REQUIRED if tag not in results]
            if missing:
                _status.write(
                    f":orange[Skipped {unparsed_dataset} — FLASHTnT needs all four "
                    f"files; missing: {', '.join(missing)}]"
                )
                _progress.progress((_i + 1) / len(pending))
                continue

            parsed_data = parseTnT(
                results['out_deconv_mzML'], results['anno_annotated_mzML'],
                results['tags_tsv'], results['protein_tsv']
            )

            for k, v in parsed_data.items():
                wf.file_manager.store_data(unparsed_dataset, k, v)
            _progress.progress((_i + 1) / len(pending))

        if pending:
            _status.update(label=f"Parsed {len(pending)} dataset(s)", state="complete",
                           expanded=False)

    tabs = st.tabs(["File Upload", "Example Data"])

    # Load Example Data
    with tabs[1]:
        # TODO: Adde xplanations for example data
        #st.markdown("An example truncated file from the E. coli dataset.")
        _, c2, _ = st.columns(3)
        if c2.button("Load Example Data", type="primary"):
            # loading and copying example files into default workspace
            for filename_postfix, name_tag in zip(
                ['*_deconv.mzML', '*_annotated.mzML', '*_tagged.tsv', '*_protein.tsv'],
                ['out_deconv_mzML', 'anno_annotated_mzML', 'tags_tsv', 'protein_tsv']
            ):
                for file in Path("example-data", "flashtagger").glob(filename_postfix):
                    wf.file_manager.store_file(
                        file.name.replace(filename_postfix[1:], ''), 
                        name_tag, file, remove=False
                    )
            process_uploaded_files([])
            # parsing the example files is done in parseUploadedFiles later
            st.success("Example files loaded!")

    # Upload files via upload widget
    with tabs[0]:
        st.subheader("**Upload FLASHDeconv & FLASHTagger output files (\*_annotated.mzML, \*_deconv.mzML, \*_tagged.tsv & \*_protein.tsv)**")
        # Display info how to upload files
        st.info(
            """
        **How to upload files**
        
        1. Browse files on your computer or drag and drops files
        2. Click the **Add files to workspace** button to use them in the viewer
        
        Select data for analysis from the uploaded files shown below.
        
        **Make sure that the same number of deconvolved and annotated mzML and FLASHTagger output files files are uploaded!**
        """
        )
        if DESKTOP:
            # No upload step: reference the files where they already are.
            picked = desktop_file_picker(
                "Add FLASHDeconv & FLASHTagger output files", ["mzML", "tsv"],
                key="tnt_pick",
            )
            if picked:
                process_uploaded_files(picked)
                st.success(f"Added {len(picked)} file(s).")
                st.rerun()
        else:
          with st.form('input_mzML', clear_on_submit=True):
            uploaded_file = st.file_uploader(
                "FLASHDeconv & FLASHTagger output files", accept_multiple_files=True, type=["mzML", "tsv"]
            )
            _, c2, _ = st.columns(3)
            # User needs to click button to upload selected files
            if c2.form_submit_button("Add files to workspace", type="primary"):
                if uploaded_file:
                    # A list of files is required, since online allows only single upload, create a list
                    if type(uploaded_file) != list:
                        uploaded_file = [uploaded_file]

                    # opening file dialog and closing without choosing a file results in None upload
                    process_uploaded_files(uploaded_file)
                    st.success("Successfully added uploaded files!")
                else:
                    st.warning("Upload some files before adding them.")

    # File Upload Table
    experiments = (
        set(wf.file_manager.get_results_list(['tags_tsv']))
        | set(wf.file_manager.get_results_list(['protein_tsv']))
        | set(wf.file_manager.get_results_list(['out_deconv_mzML']))
        | set(wf.file_manager.get_results_list(['anno_annotated_mzML']))
    )
    table = {
        'Experiment Name' : [],
        'Deconvolved Files' : [],
        'Annotated Files' : [],
        'Protein Files' : [],
        'Tag Files' : [],
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

        if wf.file_manager.result_exists(experiment, 'protein_tsv'):
            table['Protein Files'].append(True)
        else:
            table['Protein Files'].append(False)

        if wf.file_manager.result_exists(experiment, 'tags_tsv'):
            table['Tag Files'].append(True)
        else:
            table['Tag Files'].append(False)

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
            st.session_state["armed_clear_FLASHTnT"] = True
        if st.session_state.get("armed_clear_FLASHTnT"):
            def _clear_FLASHTnT():
                wf.file_manager.clear_cache()
                st.session_state.pop("armed_clear_FLASHTnT", None)
                st.rerun()
            confirm.confirm_typed(
                title="Remove every FLASHTnT dataset",
                body="This deletes every dataset in this workspace for FLASHTnT, "
                     "including parsed results. It cannot be undone.",
                phrase="FLASHTnT",
                confirm_label="Remove all FLASHTnT datasets",
                on_confirm=_clear_FLASHTnT,
            )
