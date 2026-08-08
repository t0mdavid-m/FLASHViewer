import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
import uuid
import time
from typing import Any
from pathlib import Path
from streamlit.components.v1 import html

import streamlit as st
import pandas as pd

try:
    from tkinter import Tk, filedialog

    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

from src.common.captcha_ import captcha_control
from src import confirm

# Detect system platform
OS_PLATFORM = sys.platform


def load_params(default: bool = False) -> dict[str, Any]:
    """
    Load parameters from a JSON file and return a dictionary containing them.

    If a 'params.json' file exists in the workspace, load the parameters from there.
    Otherwise, load the default parameters from 'default-parameters.json'.

    Additionally, check if any parameters have been modified by the user during the current session
    and update the values in the parameter dictionary accordingly. Also make sure that all items from
    the parameters dictionary are accessible from the session state as well.

    Args:
        default (bool): Load default parameters. Defaults to True.

    Returns:
        dict[str, Any]: A dictionary containing the parameters.
    """
    # Construct the path to the parameter file
    path = Path(st.session_state.workspace, "params.json")

    # Load the parameters from the file, or from the default file if the parameter file does not exist
    if path.exists() and not default:
        with open(path, "r", encoding="utf-8") as f:
            params = json.load(f)
    else:
        with open("default-parameters.json", "r", encoding="utf-8") as f:
            params = json.load(f)

    # Return the parameter dictionary
    return params


def save_params(params: dict[str, Any]) -> None:
    """
    Save the given dictionary of parameters to a JSON file.

    If a 'params.json' file already exists in the workspace, overwrite it with the new parameters.
    Otherwise, create a new 'params.json' file in the workspace directory and save the parameters there.

    Additionally, check if any parameters have been modified by the user during the current session
    and update the values in the parameter dictionary accordingly.

    This function should be run at the end of each page, if the parameters dictionary has been modified directly.
    Note that session states with the same keys will override any direct changes!

    Args:
        params (dict[str, Any]): A dictionary containing the parameters to be saved.

    Returns:
        dict[str, Any]: Updated parameters.
    """
    # Update the parameter dictionary with any modified parameters from the current session
    for key, value in st.session_state.items():
        if key in params.keys():
            params[key] = value

    # Save the parameter dictionary to a JSON file in the workspace directory
    path = Path(st.session_state.workspace, "params.json")
    with open(path, "w", encoding="utf-8") as outfile:
        json.dump(params, outfile, indent=4)

    return params


def valid_workspace_name(name) -> str:
    """A workspace name that is safe to join onto the workspaces directory.

    Returns "" if the value cannot be used. Workspace names reach us from a URL
    query parameter and from a sidebar text box, and both are joined into a path
    that gets created — and, for the text box, rmtree'd. An absolute path
    replaces the prefix entirely and ".." walks out of it, so anything that is
    not a single plain path component is rejected rather than sanitised.
    """
    name = str(name or "").strip()
    if not name or name in (".", ".."):
        return ""
    # Backslash is a legal filename character on POSIX but a separator on
    # Windows, and a workspace created on one may be opened on the other.
    if "/" in name or "\\" in name:
        return ""
    if name != Path(name).name:  # absolute, or otherwise not a plain component
        return ""
    if name.startswith("."):  # no hidden dirs, no surprises
        return ""
    return name


def page_setup(page: str = "") -> dict[str, Any]:
    """
    Set up the Streamlit page configuration and determine the workspace for the current session.

    This function should be run at the start of every page for setup and to get the parameters dictionary.

    Args:
        page (str, optional): The name of the current page, by default "".

    Returns:
        dict[str, Any]: A dictionary containing the parameters loaded from the parameter file.
    """
    if "settings" not in st.session_state:
        with open("settings.json", "r") as f:
            st.session_state.settings = json.load(f)

    # Set Streamlit page configurations
    st.set_page_config(
        page_title=st.session_state.settings["app-name"],
        page_icon="assets/OpenMS.png",
        layout="wide",
        initial_sidebar_state="auto",
        menu_items=None,
    )

    # Expand sidebar navigation
    st.markdown(
        """
        <style>
            .stMultiSelect [data-baseweb=select] span{
                max-width: 500px;
                font-size: 1rem;
            }
            div[data-testid='stSidebarNav'] ul {max-height:none}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.logo("assets/pyopenms_transparent_background.png")

    # Create google analytics if consent was given
    if (
        ("tracking_consent" not in st.session_state) 
        or (st.session_state.tracking_consent is None)
        or (not st.session_state.settings['online_deployment'])
    ):
        st.session_state.tracking_consent = None
    else:
        if (st.session_state.settings["analytics"]["google-analytics"]["enabled"]) and (
            st.session_state.tracking_consent["google-analytics"] == True
        ):
            html(
                """
                <!DOCTYPE html>
                <html lang="en">
                    <head></head>
                    <body><script>
                    window.parent.gtag('consent', 'update', {
                    'analytics_storage': 'granted'
                    });
                    </script></body>
                </html>
                """,
                width=1,
                height=1,
            )
        if (st.session_state.settings["analytics"]["piwik-pro"]["enabled"]) and (
            st.session_state.tracking_consent["piwik-pro"] == True
        ):
            html(
                """
                <!DOCTYPE html>
                <html lang="en">
                    <head></head>
                    <body><script>
                    var consentSettings = {
                        analytics: { status: 1 } // Set Analytics consent to 'on' (1 for on, 0 for off)
                    };
                    window.parent.ppms.cm.api('setComplianceSettings', { consents: consentSettings }, function() {
                        console.log("PiwikPro Analytics consent set to on.");
                    }, function(error) {
                        console.error("Failed to set PiwikPro analytics consent:", error);
                    });
                    </script></body>
                </html>
                """,
                width=1,
                height=1,
            )

    # Determine the workspace for the current session
    if ("workspace" not in st.session_state) or (
        ("workspace" in st.query_params)
        and (st.query_params.workspace != st.session_state.workspace.name)
    ):
        # Clear any previous caches
        st.cache_data.clear()
        st.cache_resource.clear()
        # Check location
        if not st.session_state.settings["online_deployment"]:
            st.session_state.location = "local"
            st.session_state["previous_dir"] = os.getcwd()
            st.session_state["local_dir"] = ""
        else:
            st.session_state.location = "online"
        # if we run the packaged windows version, we start within the Python directory -> need to change working directory to ..\streamlit-template
        if "windows" in sys.argv:
            os.chdir("../streamlit-template")
        # Define the directory where all workspaces will be stored
        workspaces_dir = Path("..", "workspaces-" + st.session_state.settings["repository-name"])
        if "workspace" in st.query_params:
            # ?workspace= is user-controlled and lands straight in a filesystem
            # path. An empty value silently resolved to the workspaces directory
            # itself, which then failed in render_sidebar with
            # "'workspaces-FLASHViewer' is not in list"; "..' or an absolute path
            # would escape the directory entirely.
            st.session_state.workspace = Path(
                workspaces_dir, valid_workspace_name(st.query_params.workspace) or "default"
            )
        elif st.session_state.location == "online":
            workspace_id = str(uuid.uuid1())
            st.session_state.workspace = Path(workspaces_dir, workspace_id)
            st.query_params.workspace = workspace_id
        else:
            st.session_state.workspace = Path(workspaces_dir, "default")
            st.query_params.workspace = "default"

        if st.session_state.location != "online":
            # not any captcha so, controllo should be true
            st.session_state["controllo"] = True

    if "workspace" not in st.query_params:
        st.query_params.workspace = st.session_state.workspace.name

    # Make sure the necessary directories exist
    st.session_state.workspace.mkdir(parents=True, exist_ok=True)
    Path(st.session_state.workspace, "mzML-files").mkdir(parents=True, exist_ok=True)

    # Render the sidebar
    params = render_sidebar(page)
    
    captcha_control()  

    return params


def render_sidebar(page: str = "") -> None:
    """
    Renders the sidebar on the Streamlit app, which includes the workspace switcher,
    the mzML file selector, the logo, and settings.

    Args:
        params (dict): A dictionary containing the initial parameters of the app.
            Used in the sidebar to display the following settings:
            - selected-mzML-files : str
                A string containing the selected mzML files.
            - image-format : str
                A string containing the image export format.
        page (str): A string indicating the current page of the Streamlit app.

    Returns:
        None
    """
    params = load_params()

    # Navigation moved to the top bar, which leaves the sidebar holding nothing
    # but this expander. Workspace management is environment configuration, not
    # navigation, so it belongs in a dialog rather than a permanent rail.
    @st.dialog("Settings · Workspace", width="large")
    def _workspace_dialog():
        _render_workspace_controls()

    if st.button("Settings", icon=":material/settings:", key="open_settings"):
        _workspace_dialog()

    return params


def _render_workspace_controls():
    """The workspace switcher and create/delete controls."""
    params = load_params()
    if True:
        if True:
            # Define workspaces directory outside of repository
            workspaces_dir = Path("..", "workspaces-" + st.session_state.settings["repository-name"])
            # Online: show current workspace name in info text and option to change to other existing workspace
            if st.session_state.location == "local":
                # Define callback function to change workspace
                def change_workspace():
                    for key in params.keys():
                        if key in st.session_state.keys():
                            del st.session_state[key]
                    st.session_state.workspace = Path(
                        workspaces_dir, st.session_state["chosen-workspace"]
                    )
                    st.query_params.workspace = st.session_state["chosen-workspace"]

                # Get all available workspaces as options
                options = [
                    file.name for file in workspaces_dir.iterdir() if file.is_dir()
                ]
                # Let user chose an already existing workspace
                st.selectbox(
                    "choose existing workspace",
                    options,
                    index=options.index(str(st.session_state.workspace.stem)),
                    on_change=change_workspace,
                    key="chosen-workspace",
                )
                # Create or Remove workspaces
                create_remove = st.text_input("create/remove workspace", "")
                # This value is joined into a path that Delete then rmtree's, so
                # it must be a single name. An absolute path replaces the
                # workspaces prefix outright and ".." walks out of it — either
                # would delete a directory the user never named.
                safe_name = valid_workspace_name(create_remove)
                path = Path(workspaces_dir, safe_name) if safe_name else None
                if create_remove and not safe_name:
                    st.error("Workspace names must be a single name — no slashes, no '..'.")
                # Create new workspace
                if st.button("**Create Workspace**", disabled=not safe_name):
                    path.mkdir(parents=True, exist_ok=True)
                    st.session_state.workspace = path
                    st.query_params.workspace = safe_name
                    # Temporary as the query update takes a short amount of time
                    time.sleep(1)
                    st.rerun()
                # Remove existing workspace and fall back to default.
                # Confirms INLINE, not in a dialog: this already runs inside
                # @st.dialog("Settings · Workspace") and Streamlit permits one
                # dialog at a time — nesting raises.
                if st.button("Delete Workspace", disabled=not safe_name,
                             icon=":material/delete_forever:"):
                    st.session_state["armed_delete_workspace"] = safe_name

                if safe_name and st.session_state.get("armed_delete_workspace") == safe_name:
                    if safe_name == "default":
                        st.error("The default workspace cannot be deleted.")
                    elif not path.exists():
                        st.error(f"No workspace named {safe_name}.")
                    else:
                        def _delete_workspace():
                            # valid_workspace_name() still guards the join above;
                            # this confirmation is a second layer, never a
                            # replacement for the validation that fixed the bug
                            # where an absolute path deleted that directory.
                            shutil.rmtree(path)
                            st.session_state.pop("armed_delete_workspace", None)
                            st.session_state.workspace = Path(workspaces_dir, "default")
                            st.query_params.workspace = "default"
                            st.rerun()

                        confirm.confirm_typed_inline(
                            title="Delete workspace",
                            body=(f"Deletes {path} and everything in it: parameters, "
                                  "all three tool caches, and every dataset. "
                                  "This cannot be undone."),
                            phrase=safe_name,
                            confirm_label=f"Delete {safe_name}",
                            on_confirm=_delete_workspace,
                            key="confirm_delete_workspace",
                        )

    return params


def v_space(n: int, col=None) -> None:
    """
    Prints empty strings to create vertical space in the Streamlit app.

    Args:
        n (int): An integer representing the number of empty lines to print.
        col: A streamlit column can be passed to add vertical space there.

    Returns:
        None
    """
    for _ in range(n):
        if col:
            col.write("#")
        else:
            st.write("#")


def display_large_dataframe(
    df, chunk_sizes: list[int] = [10, 100, 1_000, 10_000], **kwargs
):
    """
    Displays a large DataFrame in chunks with pagination controls and row selection.

    Args:
        df: The DataFrame to display.
        chunk_sizes: A list of chunk sizes to choose from.
        ...: Additional keyword arguments to pass to the `st.dataframe` function. See: https://docs.streamlit.io/develop/api-reference/data/st.dataframe

    Returns:
        Index of selected row.
    """

    # Dropdown for selecting chunk size
    chunk_size = st.selectbox("Select Number of Rows to Display", chunk_sizes)

    # Calculate total number of chunks
    total_chunks = (len(df) + chunk_size - 1) // chunk_size

    if total_chunks > 1:
        page = int(st.number_input("Select Page", 1, total_chunks, 1, step=1))
    else:
        page = 1

    # Function to get the current chunk of the DataFrame
    def get_current_chunk(df, chunk_size, chunk_index):
        start = chunk_index * chunk_size
        end = min(
            start + chunk_size, len(df)
        )  # Ensure end does not exceed dataframe length
        return df.iloc[start:end], start, end

    # Display the current chunk
    current_chunk_df, start_row, end_row = get_current_chunk(df, chunk_size, page - 1)

    event = st.dataframe(current_chunk_df, **kwargs)

    st.write(
        f"Showing rows {start_row + 1} to {end_row} of {len(df)} ({get_dataframe_mem_useage(current_chunk_df):.2f} MB)"
    )

    rows = event["selection"]["rows"]
    if not rows:
        return None
    # Calculate the index based on the current page and chunk size
    base_index = (page - 1) * chunk_size
    return base_index + rows[0]



def show_table(df: pd.DataFrame, download_name: str = "") -> None:
    """
    Displays a pandas dataframe using Streamlit's `dataframe` function and
    provides a download button for the same table.

    Args:
        df (pd.DataFrame): The pandas dataframe to display.
        download_name (str): The name to give to the downloaded file. Defaults to empty string.

    Returns:
        df (pd.DataFrame): The possibly edited dataframe.
    """
    # Show dataframe using container width
    st.dataframe(df, use_container_width=True)
    # Show download button with the given download name for the table if name is given
    if download_name:
        st.download_button(
            "Download Table",
            df.to_csv(sep="\t").encode("utf-8"),
            download_name.replace(" ", "-") + ".tsv",
        )
    return df


def show_fig(
    fig,
    download_name: str,
    container_width: bool = True,
    selection_session_state_key: str = "",
) -> None:
    """
    Displays a Plotly chart and adds a download button to the plot.

    Args:
        fig (plotly.graph_objs._figure.Figure): The Plotly figure to display.
        download_name (str): The name for the downloaded file.
        container_width (bool, optional): If True, the figure will use the container width. Defaults to True.
        selection_session_state_key (str, optional): If set, save the rectangular selection to session state with this key.

    Returns:
        None
    """
    if not selection_session_state_key:
        st.plotly_chart(
            fig,
            use_container_width=container_width,
            config={
                "displaylogo": False,
                "modeBarButtonsToRemove": [
                    "zoom",
                    "pan",
                    "select",
                    "lasso",
                    "zoomin",
                    "autoscale",
                    "zoomout",
                    "resetscale",
                ],
                "toImageButtonOptions": {
                    "filename": download_name,
                    "format": st.session_state["image-format"],
                },
            },
        )
    else:
        st.plotly_chart(
            fig,
            key=selection_session_state_key,
            selection_mode=["points", "box"],
            on_select="rerun",
            config={
                "displaylogo": False,
                "modeBarButtonsToRemove": [
                    "zoom",
                    "pan",
                    "lasso",
                    "zoomin",
                    "autoscale",
                    "zoomout",
                    "resetscale",
                    "select",
                ],
                "toImageButtonOptions": {
                    "filename": download_name,
                    "format": st.session_state["image-format"],
                },
            },
            use_container_width=True,
        )


def reset_directory(path: Path) -> None:
    """
    Remove the given directory and re-create it.

    Args:
        path (Path): Path to the directory to be reset.

    Returns:
        None
    """
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def get_dataframe_mem_useage(df):
    """
    Get the memory usage of a pandas DataFrame in megabytes.

    Args:
        df (pd.DataFrame): The DataFrame to calculate the memory usage for.

    Returns:
        float: The memory usage of the DataFrame in megabytes.
    """
    # Calculate the memory usage of the DataFrame in bytes
    memory_usage_bytes = df.memory_usage(deep=True).sum()
    # Convert bytes to megabytes
    memory_usage_mb = memory_usage_bytes / (1024**2)
    return memory_usage_mb


def tk_directory_dialog(title: str = "Select Directory", parent_dir: str = os.getcwd()):
    """
    Creates a Tkinter directory dialog for selecting a directory.

    Args:
        title (str): The title of the directory dialog.
        parent_dir (str): The path to the parent directory of the directory dialog.

    Returns:
        str: The path to the selected directory.

    Warning:
        This function is not avaliable in a streamlit cloud context.
    """
    root = Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    file_path = filedialog.askdirectory(title=title, initialdir=parent_dir)
    root.destroy()
    return file_path


def electron_dialog(file_types=None, title="Select files", directory=False):
    """Ask the Electron shell to open a native file dialog.

    Returns a list of Paths, or [] if cancelled/unavailable.

    Not tkinter: on macOS Tk aborts the entire process when constructed off the
    main thread ("NSException", libc++abi terminate), and Streamlit runs page
    code in a ScriptRunner thread — so every Tk dialog killed the Python
    process rather than opening. Electron owns the main thread, so it opens the
    dialog and we ask it over localhost.
    """
    port = os.environ.get("FLASHAPP_DIALOG_PORT")
    token = os.environ.get("FLASHAPP_DIALOG_TOKEN")
    if not port or not token:
        return []

    query = urllib.parse.urlencode({
        "token": token,
        "title": title,
        "types": ",".join(file_types or []),
        "directory": "1" if directory else "0",
    })
    try:
        # The dialog is modal: the user may take a while.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/pick?{query}", timeout=600
        ) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user below
        st.error(f"Could not open the file dialog: {exc}")
        return []
    return [Path(p) for p in payload.get("paths", [])]


def desktop_file_picker(label: str, file_types: list[str], key: str):
    """Pick files from this machine, for the desktop app.

    Returns a list of Paths, or [] if nothing was chosen. The desktop app has no
    upload step: files stay where they are and only their paths are recorded, so
    there is no size ceiling and no second copy on disk.

    A text box is offered alongside the dialog, because typing or pasting a path
    is often faster and it is the only route if the dialog is unavailable.
    """
    picked = []
    c1, c2 = st.columns([1, 2])

    if c1.button(label, key=key, type="primary"):
        picked = electron_dialog(file_types=file_types, title=label)
        if not picked:
            st.info("Nothing selected.")

    typed = c2.text_input(
        "or paste a file or folder path",
        key=f"{key}_path",
        placeholder="/path/to/data",
    )
    # An explicit action, not "there is text in the box". A keyed text_input
    # keeps its value across reruns, so firing on presence re-ingested on every
    # rerun and raced the st.rerun() the callers do — which is why pasting a
    # path appeared to do nothing at all.
    if c2.button("Add from path", key=f"{key}_path_add", disabled=not typed):
        source = Path(typed).expanduser()
        if not source.exists():
            c2.error(f"No such file or folder: {source}")
        elif source.is_dir():
            matched = sorted(
                p for ext in file_types for p in source.glob(f"*.{ext}")
            )
            if not matched:
                c2.error(f"No .{'/.'.join(file_types)} files in {source}")
            picked = matched
        else:
            picked = [source]

    if picked:
        st.session_state["previous_dir"] = str(picked[0].parent)
    return picked


def tk_file_dialog(
    title: str = "Select File",
    file_types: list[tuple] = [],
    parent_dir: str = os.getcwd(),
    multiple: bool = True,
):
    """
    Creates a Tkinter file dialog for selecting a file.

    Args:
        title (str): The title of the file dialog.
        file_types (list(tuple)): The file types to filter the file dialog.
        parent_dir (str): The path to the parent directory of the file dialog.
        multiple (bool): If True, multiple files can be selected.

    Returns:
        str: The path to the selected file.

    Warning:
        This function is not avaliable in a streamlit cloud context.
    """
    root = Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    file_types.extend([("All files", "*.*")])
    file_path = filedialog.askopenfilename(
        title=title, filetypes=file_types, initialdir=parent_dir, multiple=True
    )
    root.destroy()
    return file_path


# General warning/error messages
WARNINGS = {
    "missing-mzML": "Upload or select some mzML files first!",
}

ERRORS = {
    "general": "Something went wrong.",
    "workflow": "Something went wrong during workflow execution.",
    "visualization": "Something went wrong during visualization of results.",
}
