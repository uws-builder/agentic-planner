"""Streamlit entry point:  .venv/bin/streamlit run app.py

This tiny launcher lives at the repo root on purpose. Streamlit only watches
modules inside the script's own folder (or on PYTHONPATH) for changes, so a
script buried in src/planner/ui/ never notices edits to src/planner/*.py and
keeps running stale code after a change. From here, everything under src/ is
watched, so edits show up without restarting the server.
"""

import runpy

runpy.run_module("planner.ui.streamlit_app", run_name="__main__")
