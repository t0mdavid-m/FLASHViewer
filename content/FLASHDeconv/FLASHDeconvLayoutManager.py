import streamlit as st

from src.common.common import page_setup, save_params
from src.preset_page import render

params = page_setup()
render("FLASHDeconv", ["deconv_dfs", "anno_dfs"])
save_params(params)
