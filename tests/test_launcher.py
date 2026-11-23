"""The root-level launcher (app.py).

Streamlit only watches modules inside the script's own folder (or on PYTHONPATH). A
script under src/planner/ui/ therefore never noticed edits to src/planner/*.py and kept
running stale code, which showed up as 'unexpected keyword argument' errors after a
change. The launcher lives at the repo root so everything under src/ is watched."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from streamlit.testing.v1 import AppTest

import planner.context
import planner.rules
import planner.summarize

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "app.py"


def test_the_launcher_exists_at_the_repo_root():
    assert LAUNCHER.is_file()


def test_every_planner_module_is_inside_the_launchers_folder():
    """If this fails, Streamlit would stop noticing edits to those modules."""
    folder = LAUNCHER.parent
    paths = {m.__name__: m.__file__ for m in (planner.context, planner.rules, planner.summarize)}
    # find_spec locates the UI module without importing it (the launcher runs it itself)
    paths["planner.ui.streamlit_app"] = importlib.util.find_spec("planner.ui.streamlit_app").origin
    for name, path in paths.items():
        assert folder in Path(path).resolve().parents, name


def test_the_launcher_runs_the_app(monkeypatch):
    monkeypatch.setenv("PLANNER_DEMO_DELAY", "0")
    at = AppTest.from_file(str(LAUNCHER), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert at.button(key="build").label == "Build media plan"
    at.button(key="build").click().run()
    assert not at.exception, at.exception
    assert {"back_to_input", "create_plan"} <= {b.key for b in at.button if b.key}


def test_the_app_only_listens_on_localhost():
    """Real-model mode spends the API key from .env. If Streamlit listened on every
    interface, anyone on the same network could open the app and use that key."""
    import tomllib

    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["server"]["address"] in ("localhost", "127.0.0.1")


def test_no_launch_option_widens_the_binding():
    import json

    config = json.loads((ROOT / ".claude" / "launch.json").read_text())
    for entry in config["configurations"]:
        args = " ".join(entry["runtimeArgs"])
        assert "0.0.0.0" not in args and "--server.address" not in args


def test_launch_config_points_at_the_launcher():
    import json

    config = json.loads((ROOT / ".claude" / "launch.json").read_text())
    args = config["configurations"][0]["runtimeArgs"]
    assert "app.py" in args and not any("streamlit_app.py" in a for a in args)
