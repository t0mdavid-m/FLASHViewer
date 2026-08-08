import pyopenms as poms
import json

from src.tools import record_intent

import shutil
import streamlit as st
from pathlib import Path


def method_only(params):
    """params.json minus the input-file selections.

    select_input_file writes the chosen inputs into the same file as the method
    parameters, so a whole-file diff marked "Method: changed from defaults" the
    moment a user picked an mzML file on the Data step. Input selections are
    recognised by their value -- paths under the workspace's own input-files/ --
    rather than by a key naming convention or a widget registration order that
    render order controls.
    """
    def is_selection(value):
        # An empty list counts too: that is the "nothing chosen yet" state the
        # selection starts in, and without it the very first pick still reads as
        # a change. The cost is that a genuine method parameter holding an empty
        # list carries no intent — no such parameter exists in any of the three
        # tools, and under-reporting here is the safe direction.
        items = value if isinstance(value, list) else [value]
        return all(isinstance(v, str) and "input-files" in v for v in items)

    return {k: v for k, v in params.items() if not is_selection(v)}

class ParameterManager:
    """
    Manages the parameters for a workflow, including saving parameters to a JSON file,
    loading parameters from the file, and resetting parameters to defaults. This class
    specifically handles parameters related to TOPP tools in a pyOpenMS context and
    general parameters stored in Streamlit's session state.

    Attributes:
        ini_dir (Path): Directory path where .ini files for TOPP tools are stored.
        params_file (Path): Path to the JSON file where parameters are saved.
        param_prefix (str): Prefix for general parameter keys in Streamlit's session state.
        topp_param_prefix (str): Prefix for TOPP tool parameter keys in Streamlit's session state.
    """
    # Methods related to parameter handling
    def __init__(self, workflow_dir: Path):
        self.ini_dir = Path(workflow_dir, "ini")
        self.ini_dir.mkdir(parents=True, exist_ok=True)
        self.params_file = Path(workflow_dir, "params.json")
        self.param_prefix = f"{workflow_dir.stem}-param-"
        self.topp_param_prefix = f"{workflow_dir.stem}-TOPP-"

    def save_parameters(self) -> None:
        """
        Saves the current parameters from Streamlit's session state to a JSON file.
        It handles both general parameters and parameters specific to TOPP tools,
        ensuring that only non-default values are stored.
        """
        # Everything in session state which begins with self.param_prefix is saved to a json file
        json_params = {
            k.replace(self.param_prefix, ""): v
            for k, v in st.session_state.items()
            if k.startswith(self.param_prefix)
        }

        # Merge with parameters from json
        # Advanced parameters are only in session state if the view is active
        json_params = self.get_parameters_from_json() | json_params

        # get a list of TOPP tools which are in session state
        current_topp_tools = list(
            set(
                [
                    k.replace(self.topp_param_prefix, "").split(":1:")[0]
                    for k in st.session_state.keys()
                    if k.startswith(f"{self.topp_param_prefix}")
                ]
            )
        )
        # for each TOPP tool, open the ini file
        for tool in current_topp_tools:
            if tool not in json_params:
                json_params[tool] = {}
            # load the param object
            param = poms.Param()
            poms.ParamXMLFile().load(str(Path(self.ini_dir, f"{tool}.ini")), param)
            # get all session state param keys and values for this tool
            for key, value in st.session_state.items():
                if key.startswith(f"{self.topp_param_prefix}{tool}:1:"):
                    # get ini_key
                    ini_key = key.replace(self.topp_param_prefix, "").encode()
                    # get ini (default) value by ini_key
                    ini_value = param.getValue(ini_key)
                    # check if value is different from default
                    if (
                        (ini_value != value) 
                        or (key.split(":1:")[1] in json_params[tool])
                    ):
                        # store non-default value
                        json_params[tool][key.split(":1:")[1]] = value
        # Record deliberate parameter change — but ONLY when the dict actually
        # differs from what is already on disk. This method runs on every widget
        # render (input_widget / input_TOPP call it unconditionally), so the mere
        # existence of params.json proves nothing about user intent; that is why
        # the wizard cannot derive "Method configured" from the file existing.
        previous = None
        if self.params_file.exists():
            try:
                previous = json.loads(self.params_file.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                previous = None

        # Save to json file
        with open(self.params_file, "w", encoding="utf-8") as f:
            json.dump(json_params, f, indent=4)

        # Only a genuine METHOD change counts; see method_only().
        if previous is not None and method_only(json_params) != method_only(previous):
            record_intent(self.params_file.parent, "method")

    def get_parameters_from_json(self) -> None:
        """
        Loads parameters from the JSON file if it exists and returns them as a dictionary.
        If the file does not exist, it returns an empty dictionary.

        Returns:
            dict: A dictionary containing the loaded parameters. Keys are parameter names,
                and values are parameter values.
        """
        # Check if parameter file exists
        if not Path(self.params_file).exists():
            return {}
        else:
            # Load parameters from json file
            try:
                with open(self.params_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                st.error("**ERROR**: Attempting to load an invalid JSON parameter file. Reset to defaults.")
                return {}

    def reset_to_default_parameters(self) -> None:
        """
        Resets the parameters to their default values by deleting the custom parameters
        JSON file.
        """
        # Delete custom params json file
        self.params_file.unlink(missing_ok=True)