"""The commit safeguards: ignore rules, the pre-commit hook, and the pre-push hook.

Each test builds a throwaway git repo with the real hooks switched on, so it exercises
exactly what runs when you commit. Fake secrets are assembled from pieces at run time so
this file itself never contains a key-shaped string (the hook would block committing it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "githooks"

NOREPLY = "12345+someone@users.noreply.github.com"
FAKE_ANTHROPIC = "sk-ant-" + "api03-" + "A" * 24
FAKE_GITHUB = "ghp_" + "B" * 30
FAKE_AWS = "AKIA" + "C" * 16
FAKE_PERSONAL_EMAIL = "someone" + "@" + "gmail" + ".com"
FAKE_KEY_BLOCK = "-----BEGIN " + "RSA PRIVATE KEY-----"


def run(cwd: Path, *args: str, input: str | None = None, check: bool = False):
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,  # ignore the developer's own git config
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(cwd),
    }
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, input=input, capture_output=True, text=True
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def make_repo(tmp_path: Path, email: str = NOREPLY, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    run(repo, "init", "-q", check=True)
    run(repo, "config", "user.name", "someone", check=True)
    run(repo, "config", "user.email", email, check=True)
    shutil.copytree(HOOKS, repo / "githooks")
    run(repo, "config", "core.hooksPath", "githooks", check=True)
    return repo


def stage(repo: Path, relpath: str, content: str = "hello\n") -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    run(repo, "add", "-f", relpath, check=True)


def commit(repo: Path, *extra: str):
    return run(repo, "commit", "-q", "-m", "test", *extra)


# ---- the hook files themselves ---------------------------------------------


@pytest.mark.parametrize("name", ["pre-commit", "pre-push"])
def test_hooks_exist_are_executable_and_use_bash(name):
    path = HOOKS / name
    assert path.is_file() and os.access(path, os.X_OK)
    assert path.read_text().startswith("#!/bin/bash")


def test_no_hook_contains_a_personal_email_or_key():
    text = "".join((HOOKS / n).read_text() for n in ("pre-commit", "pre-push"))
    for needle in ("eick", "jayden", "sk-ant-api"):
        assert needle not in text.lower()


# ---- ignore rules ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", ".env.production", ".streamlit/secrets.toml", "deploy/key.pem",
     "id_rsa", "x/id_ed25519.pub", "server.key"],
)
def test_secret_files_are_ignored(path):
    assert run(ROOT, "check-ignore", "-q", path).returncode == 0, path


@pytest.mark.parametrize("path", [".env.example", ".streamlit/config.toml", "src/planner/rules.py"])
def test_normal_files_are_not_ignored(path):
    assert run(ROOT, "check-ignore", "-q", path).returncode == 1, path


# ---- pre-commit: allowed ---------------------------------------------------


def test_a_clean_commit_with_a_private_identity_goes_through(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, "notes.txt", "nothing secret here\n")
    assert commit(repo).returncode == 0


def test_the_blank_env_template_is_allowed(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, ".env.example", "ANTHROPIC_API_KEY=\n# PLANNER_MODEL=some-model\n")
    assert commit(repo).returncode == 0


def test_a_placeholder_value_is_not_mistaken_for_a_key(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, "README.md", 'export ANTHROPIC_API_KEY="your-key-here"\n')
    assert commit(repo).returncode == 0


def test_deleting_a_file_is_never_blocked(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, "old.txt", "stuff\n")
    assert commit(repo).returncode == 0
    run(repo, "rm", "-q", "old.txt", check=True)
    assert commit(repo).returncode == 0


# ---- pre-commit: blocked files ---------------------------------------------


@pytest.mark.parametrize(
    "path",
    [".env", ".env.local", "config/.env", ".streamlit/secrets.toml", "ssh/id_rsa", "k.pem", "server.key"],
)
def test_secret_files_are_refused_even_when_forced_past_gitignore(tmp_path, path):
    repo = make_repo(tmp_path)
    stage(repo, path, "X=1\n")  # `git add -f` bypasses .gitignore, as a careless 'add all' might
    result = commit(repo)
    assert result.returncode != 0
    assert "secrets file" in result.stderr and "nothing was committed" in result.stderr
    assert run(repo, "log").returncode != 0  # no commit exists


# ---- pre-commit: blocked content -------------------------------------------


@pytest.mark.parametrize(
    "content,label",
    [
        (f"key = '{FAKE_ANTHROPIC}'\n", "Anthropic API key"),
        (f"token = '{FAKE_GITHUB}'\n", "GitHub token"),
        (f"aws = '{FAKE_AWS}'\n", "AWS access key"),
        (f"{FAKE_KEY_BLOCK}\nabc\n", "private key block"),
        (f"ANTHROPIC_API_KEY={'x' * 30}\n", "API key assigned to a variable"),
        (f"contact me at {FAKE_PERSONAL_EMAIL}\n", "personal mail provider"),
    ],
)
def test_secret_looking_content_is_refused_without_echoing_it(tmp_path, content, label):
    repo = make_repo(tmp_path)
    stage(repo, "app.py", content)
    result = commit(repo)
    assert result.returncode != 0
    assert label in result.stderr
    for secret in (FAKE_ANTHROPIC, FAKE_GITHUB, FAKE_AWS, FAKE_PERSONAL_EMAIL):
        assert secret not in result.stderr  # the message says WHAT, never the value


def test_a_safe_example_address_is_allowed(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, "fixtures.txt", "someone@example.com and rfp@summitridgeoutdoors.example\n")
    assert commit(repo).returncode == 0


# ---- pre-commit: identity --------------------------------------------------


@pytest.mark.parametrize("email", ["someone@example.com", FAKE_PERSONAL_EMAIL, "me@work.org"])
def test_a_non_private_author_email_is_refused(tmp_path, email):
    repo = make_repo(tmp_path, email=email)
    stage(repo, "notes.txt")
    result = commit(repo)
    assert result.returncode != 0
    assert "not a GitHub private (noreply) address" in result.stderr
    assert "git config user.email" in result.stderr  # tells you how to fix it


def test_the_legacy_noreply_form_is_accepted(tmp_path):
    repo = make_repo(tmp_path, email="someone@users.noreply.github.com")
    stage(repo, "notes.txt")
    assert commit(repo).returncode == 0


def test_no_verify_is_a_deliberate_bypass(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, ".env", "X=1\n")
    assert commit(repo).returncode != 0
    assert commit(repo, "--no-verify").returncode == 0


# ---- pre-push --------------------------------------------------------------


def make_remote(tmp_path: Path, repo: Path) -> None:
    remote = tmp_path / "remote.git"
    run(tmp_path, "init", "-q", "--bare", str(remote), check=True)
    run(repo, "remote", "add", "origin", str(remote), check=True)


def test_pushing_private_commits_is_allowed(tmp_path):
    repo = make_repo(tmp_path)
    make_remote(tmp_path, repo)
    stage(repo, "a.txt")
    assert commit(repo).returncode == 0
    assert run(repo, "push", "-q", "origin", "HEAD:refs/heads/main").returncode == 0


def test_pushing_a_commit_with_a_personal_email_is_refused(tmp_path):
    repo = make_repo(tmp_path)
    make_remote(tmp_path, repo)
    run(repo, "config", "user.email", "someone@example.com", check=True)
    stage(repo, "a.txt")
    assert commit(repo, "--no-verify").returncode == 0  # slipped past pre-commit
    result = run(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    assert result.returncode != 0
    assert "non-private author email" in result.stderr and "nothing was pushed" in result.stderr
    assert "someone@example.com" not in result.stderr  # reports the commit, not the address
    assert run(tmp_path / "remote.git", "rev-list", "--all").stdout.strip() == ""  # nothing arrived


def test_only_new_commits_are_checked_not_old_ones(tmp_path):
    repo = make_repo(tmp_path)
    make_remote(tmp_path, repo)
    stage(repo, "a.txt")
    assert commit(repo).returncode == 0
    assert run(repo, "push", "-q", "origin", "HEAD:refs/heads/main").returncode == 0
    stage(repo, "b.txt")
    assert commit(repo).returncode == 0
    assert run(repo, "push", "-q", "origin", "HEAD:refs/heads/main").returncode == 0


def test_pre_push_has_its_own_bypass(tmp_path):
    repo = make_repo(tmp_path)
    make_remote(tmp_path, repo)
    run(repo, "config", "user.email", "someone@example.com", check=True)
    stage(repo, "a.txt")
    assert commit(repo, "--no-verify").returncode == 0
    assert run(repo, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main").returncode == 0
