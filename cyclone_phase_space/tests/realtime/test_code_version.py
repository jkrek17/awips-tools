"""collect_daily.code_version: the short HEAD hash, "-dirty" for uncommitted
changes to tracked files outside the collection outputs, "unknown" without
git or a repository."""

from __future__ import annotations

import shutil
import subprocess

import pytest

import collect_daily as cd

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "code.py").write_text("x = 1\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "log.csv").write_text("cycle\n")
    (tmp_path / "watch.json").write_text("{}\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@needs_git
def test_clean_tree_gives_the_short_hash(repo):
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()
    assert cd.code_version(repo) == head
    (repo / "untracked.txt").write_text("new file\n")
    assert cd.code_version(repo) == head


@needs_git
def test_tracked_change_is_dirty_but_outputs_are_not(repo):
    clean = cd.code_version(repo)
    (repo / "data" / "log.csv").write_text("cycle\n2026101712\n")
    (repo / "watch.json").write_text('{"storms": []}\n')
    assert cd.code_version(repo) == clean
    (repo / "code.py").write_text("x = 2\n")
    assert cd.code_version(repo) == clean + "-dirty"


def test_no_repository_is_unknown(tmp_path):
    assert cd.code_version(tmp_path) == "unknown"


def test_no_git_is_unknown(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(cd.subprocess, "run", missing)
    assert cd.code_version(tmp_path) == "unknown"
