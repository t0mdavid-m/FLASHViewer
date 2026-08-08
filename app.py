import streamlit as st
from pathlib import Path
# For some reason the windows version only works if this is imported here
import pyopenms

# Icons are Material Symbols, which Streamlit ships itself — one weight, one
# family, no emoji and no CDN. A CDN icon font would also be a hard external
# dependency at first paint for the offline desktop build.
if __name__ == '__main__':
    pages = {
        "FLASHApp" : [
            st.Page(Path("content", "quickstart.py"), title="Quickstart", icon=":material/waving_hand:")
        ],
        "FLASHDeconv" : [
            st.Page(Path("content", "FLASHDeconv", "FLASHDeconvWorkflow.py"), title="Workflow", icon=":material/settings:"),
            st.Page(Path("content", "FLASHDeconv", "FLASHDeconvSequenceInput.py"), title="Sequence Input", icon=":material/linear_scale:"),
            st.Page(Path("content", "FLASHDeconv", "FLASHDeconvLayoutManager.py"), title="View presets", icon=":material/dashboard_customize:"),
            st.Page(Path("content", "FLASHDeconv", "FLASHDeconvViewer.py"), title="Viewer", icon=":material/visibility:"),
            st.Page(Path("content", "FLASHDeconv", "FLASHDeconvDownload.py"), title="Download", icon=":material/download:"),
        ],
        "FLASHTnT": [
            st.Page(Path("content", "FLASHTnT", "FLASHTnTWorkflow.py"), title="Workflow", icon=":material/settings:"),
            st.Page(Path("content", "FLASHTnT", "FLASHTnTLayoutManager.py"), title="View presets", icon=":material/dashboard_customize:"),
            st.Page(Path("content", "FLASHTnT", "FLASHTnTViewer.py"), title="Viewer", icon=":material/visibility:"),
            st.Page(Path("content", "FLASHTnT", "FLASHTnTDownload.py"), title="Download", icon=":material/download:"),
        ],
        "FLASHQuant" : [
            st.Page(Path("content", "FLASHQuant", "FLASHQuantFileUpload.py"), title="Add data", icon=":material/folder_open:"),
            st.Page(Path("content", "FLASHQuant", "FLASHQuantViewer.py"), title="Viewer", icon=":material/visibility:"),
        ],
    }

    # position='top' gives the header-style navigation the redesign asks for
    # without giving up st.navigation: page URLs, browser history and
    # st.switch_page all keep working. Removing it would mean hand-rolling a
    # router over twelve page scripts and losing deep links.
    pg = st.navigation(pages, position='top')
    pg.run()
