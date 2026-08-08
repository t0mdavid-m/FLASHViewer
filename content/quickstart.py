from pathlib import Path
import streamlit as st

from src.common.common import page_setup, v_space

page_setup(page="main")

st.markdown("# Quick Start")
st.markdown("## FLASHApp")


# main content
st.markdown('#### FLASHApp: A Platform for Your Favorite FLASH\* Tools!')

st.info("""
    **How to run FLASHApp**
    1. Pick a tool in the top navigation, then use its **Workflow** page to run an analysis,\
        or its **Add results** tab to bring in FLASHDeconv output files (\*_annotated.mzML & \*_deconv.mzML)
    2. Open that tool's **Viewer** to explore the results.
    """)

if Path("OpenMS-App.zip").exists():
    st.subheader(
        """
Download the latest version for Windows here by clicking the button below.
"""
    )
    with open("OpenMS-App.zip", "rb") as file:
        st.download_button(
            label="Download for Windows",
            data=file,
            file_name="OpenMS-App.zip",
            mime="archive/zip",
            type="primary",
        )
    st.markdown(
        """
Extract the zip file and run the installer (.msi) file to install the app. The app can then be launched using the corresponding desktop icon.
"""
    )

c1, c2 = st.columns(2)
# The share/bookmark line is only true on a hosted deployment. The desktop app
# starts Streamlit on a random port bound to 127.0.0.1, so the URL means nothing
# to anyone else and differs on the next launch.
whats_new = ["- FLASHViewer is now FLASHApp"]
if st.session_state.settings.get("online_deployment", False):
    whats_new.append(
        "- Want to save your progress or share it with your team? Simply bookmark / share the URL!"
    )
c1.markdown("## New\n\n" + "\n".join(whats_new) + "\n")
c2.image("assets/pyopenms_transparent_background.png", width=300)
