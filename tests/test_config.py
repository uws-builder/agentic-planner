from planner.config import load_env


def test_loads_values_without_overriding_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "A_KEY=from_file\n"
        'export B_KEY="quoted"\n'
        "ALREADY_SET=from_file\n"
        "EMPTY=\n"
        "not a pair\n"
    )
    for name in ("A_KEY", "B_KEY", "EMPTY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALREADY_SET", "from_shell")

    loaded = load_env(env_file)

    import os

    assert sorted(loaded) == ["A_KEY", "B_KEY"]
    assert os.environ["A_KEY"] == "from_file"
    assert os.environ["B_KEY"] == "quoted"
    assert os.environ["ALREADY_SET"] == "from_shell"
    assert "EMPTY" not in os.environ
    monkeypatch.delenv("A_KEY")
    monkeypatch.delenv("B_KEY")


def test_missing_file_is_fine(tmp_path):
    assert load_env(tmp_path / "nope.env") == []
