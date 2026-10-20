import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from src.claude_china import grok


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_find_npm_installation_uses_active_prefix(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(grok.sys, "platform", platform)
    command = tmp_path / ("grok.cmd" if platform == "win32" else "bin/grok")
    package = tmp_path / ("node_modules" if platform == "win32" else "lib/node_modules") / "@xai-official/grok"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text("launcher", encoding="utf-8")
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@xai-official/grok", "version": "1.0.46"}))
    monkeypatch.setattr(grok.shutil, "which", lambda name: "npm.cmd" if platform == "win32" else "npm")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n", stderr="")

    monkeypatch.setattr(grok.subprocess, "run", run)
    installation = grok.find_npm_installation()

    assert installation.command == str(command)
    assert installation.version == "1.0.46"
    assert calls[0][0][1:] == ["prefix", "-g"]
    assert calls[0][1]["timeout"] == 10


def test_find_npm_installation_returns_none_when_npm_is_missing(monkeypatch):
    monkeypatch.setattr(grok.shutil, "which", lambda name: None)
    assert grok.find_npm_installation() is None


def test_find_npm_installation_returns_none_when_prefix_query_fails(monkeypatch):
    monkeypatch.setattr(grok.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(grok.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="unavailable"))
    assert grok.find_npm_installation() is None


def test_find_npm_installation_does_not_treat_an_empty_prefix_as_cwd(monkeypatch):
    monkeypatch.setattr(grok.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(grok.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="\n", stderr=""))
    assert grok.find_npm_installation() is None


def test_check_version_rejects_stale_binary_despite_successful_exit(monkeypatch):
    monkeypatch.setattr(grok.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="grok 0.2.118 (old)\n", stderr=""))
    with pytest.raises(RuntimeError, match="0.2.118.*1.0.46"):
        grok.check_version("/profile/bin/grok", {}, "1.0.46")


def test_check_version_uses_profile_environment(monkeypatch):
    calls = []
    env = {"GROK_HOME": "/profile"}

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="grok 1.0.46 (current)\n", stderr="")

    monkeypatch.setattr(grok.subprocess, "run", run)
    grok.check_version("/profile/bin/grok", env, "1.0.46")
    assert calls[0][0] == ["/profile/bin/grok", "--version"]
    assert calls[0][1]["env"] is env


def test_check_version_reports_missing_binary(monkeypatch):
    def run(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(grok.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="/profile/bin/grok"):
        grok.check_version("/profile/bin/grok", {}, "1.0.46")


def test_home_binary_uses_platform_filename(monkeypatch):
    monkeypatch.setattr(grok.sys, "platform", "darwin")
    assert grok.home_binary("/profile") == os.path.join("/profile", "bin", "grok")
    monkeypatch.setattr(grok.sys, "platform", "win32")
    assert grok.home_binary("/profile") == os.path.join("/profile", "bin", "grok.exe")
