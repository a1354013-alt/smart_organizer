"""Stable Streamlit entrypoint for Smart Organizer."""

import streamlit as st

from app_main import main
from startup import run_with_startup_boundary
from version import APP_TITLE  # noqa: F401

run_with_startup_boundary(st, main)
