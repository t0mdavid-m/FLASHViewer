import streamlit as st

from src.common.common import page_setup, save_params
from src.preset_page import render

params = page_setup()
render("FLASHTnT", ["protein_dfs", "tag_dfs", "deconv_dfs"])
save_params(params)
