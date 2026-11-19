import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.claude_china import cli
from src.claude_china.cli import UPGRADE_PACKAGES


@pytest.fixture(autouse=True)
def verified_commands(monkeypatch):
    monkeypatch.setattr(cli, '_verify_cli', lambda kind, env: 'fixture-version')
    monkeypatch.setattr(cli, '_upgrade_native', lambda provider, env: SimpleNamespace(returncode=0))


@pytest.fixture(autouse=True)
def installed_grok(monkeypatch, tmp_path):
    installation = SimpleNamespace(command=str(tmp_path / "npm-grok"), version="1.0.46")
    monkeypatch.setattr(cli, "find_npm_installation", lambda: installation)
    monkeypatch.setattr(cli, "load_config", lambda: {"profiles": {}})
    checks = []
    monkeypatch.setattr(cli, "check_grok_version", lambda command, env, version: checks.append((command, env, version)))
    return installation, checks


def test_upgrade_packages_use_official_grok_cli_instead_of_gemini():
    assert "@xai-official/grok" in UPGRADE_PACKAGES
    assert "@google/gemini-cli" not in UPGRADE_PACKAGES


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_upgrade_refreshes_each_grok_login_home(monkeypatch, tmp_path, platform, installed_grok):
    homes = [str(tmp_path / "account-a"), str(tmp_path / "account-b")]
    monkeypatch.setattr(cli.sys, "platform", platform)
    monkeypatch.setenv("GROK_HOME", homes[0])
    monkeypatch.setattr(cli, "load_config", lambda: {
        "profiles": {
            "grok-a": {"type": "grok", "mode": "login", "credentials_path": homes[0]},
            "grok-b": {"type": "grok", "mode": "login", "credentials_path": homes[1]},
            "grok-api": {"type": "grok", "mode": "api"},
            "claude": {"type": "claude", "mode": "login", "credentials_path": str(tmp_path / "claude")},
        },
    })
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        cli.upgrade()

    assert exc.value.code == 0
    assert len(calls) == 3
    assert "GROK_HOME" not in calls[0][1]["env"]
    assert [call[1]["env"]["GROK_HOME"] for call in calls[1:]] == homes
    if platform == "win32":
        assert calls[0][0] == "npm install -g --ignore-scripts=false " + " ".join(UPGRADE_PACKAGES)
        assert all(call[1]["shell"] for call in calls)
        assert [call[0] for call in calls[1:]] == ["npm rebuild -g --ignore-scripts=false --foreground-scripts @xai-official/grok"] * 2
    else:
        assert calls[0][0] == ["npm", "install", "-g", "--ignore-scripts=false"] + UPGRADE_PACKAGES
        assert [call[0] for call in calls[1:]] == [["npm", "rebuild", "-g", "--ignore-scripts=false", "--foreground-scripts", "@xai-official/grok"]] * 2
    installation, checks = installed_grok
    binary_name = "grok.exe" if platform == "win32" else "grok"
    assert [check[0] for check in checks] == [
        installation.command,
        os.path.join(os.path.expanduser("~/.grok"), "bin", binary_name),
        os.path.join(homes[0], "bin", binary_name),
        os.path.join(homes[1], "bin", binary_name),
    ]
    assert all(check[2] == "1.0.46" for check in checks)
    assert os.environ["GROK_HOME"] == homes[0]


def test_upgrade_expands_and_deduplicates_grok_login_homes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    home = str(tmp_path / "account-a")
    monkeypatch.setattr(cli, "load_config", lambda: {
        "profiles": {
            "grok-a": {"type": "grok", "mode": "login", "credentials_path": "~/account-a"},
            "grok-alias": {"type": "grok", "mode": "login", "credentials_path": home},
            "grok-default": {"type": "grok", "mode": "login", "credentials_path": "~/.grok"},
        },
    })
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs["env"].get("GROK_HOME"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        cli.upgrade()

    assert exc.value.code == 0
    assert calls == [None, os.path.expanduser("~/account-a")]


def test_upgrade_without_grok_login_profiles_only_installs_packages(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: {"profiles": {}})
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        cli.upgrade()

    assert exc.value.code == 0
    assert len(calls) == 1


def test_upgrade_stops_when_global_install_fails(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=7))

    def unexpected_load():
        pytest.fail("Profiles must not be refreshed after a failed package install")

    monkeypatch.setattr(cli, "load_config", unexpected_load)

    with pytest.raises(SystemExit) as exc:
        cli.upgrade()

    assert exc.value.code == 7


def test_upgrade_reports_grok_home_refresh_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: {
        "profiles": {
            "grok-a": {"type": "grok", "mode": "login", "credentials_path": str(tmp_path / "account-a")},
        },
    })
    results = iter([0, 9])
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=next(results)))

    with pytest.raises(SystemExit) as exc:
        cli.upgrade()

    assert exc.value.code == 9
    assert "grok-a" in capsys.readouterr().err


def test_upgrade_rejects_successful_rebuild_that_leaves_profile_binary_old(monkeypatch, tmp_path, capsys):
    home = str(tmp_path / "account-a")
    monkeypatch.setattr(cli, "load_config", lambda: {"profiles": {
        "grok-a": {"type": "grok", "mode": "login", "credentials_path": home},
    }})
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    def check(command, env, version):
        if env.get("GROK_HOME") == home:
            raise RuntimeError("Grok CLI is still 0.2.118; expected 1.0.46")

    monkeypatch.setattr(cli, "check_grok_version", check, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.upgrade()
    assert exc.value.code == 1
    assert "0.2.118" in capsys.readouterr().err


def test_upgrade_rejects_stale_default_binary(monkeypatch, capsys, installed_grok):
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    installation, _ = installed_grok

    def check(command, env, version):
        if command != installation.command:
            raise RuntimeError("Grok CLI is still 0.2.118; expected 1.0.46")

    monkeypatch.setattr(cli, "check_grok_version", check, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.upgrade()
    assert exc.value.code == 1
    assert "0.2.118" in capsys.readouterr().err


def test_upgrade_fails_when_npm_installation_cannot_be_found(monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli, "find_npm_installation", lambda: None, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.upgrade()
    assert exc.value.code == 1
    assert "npm" in capsys.readouterr().err


def test_upgrade_can_select_only_requested_npm_tools(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: calls.append(args[0]) or SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit) as exc:
        cli.upgrade(tools=['claude', 'codex'])
    assert exc.value.code == 0
    assert len(calls) == 1
    command = calls[0] if isinstance(calls[0], list) else calls[0].split()
    assert '@anthropic-ai/claude-code' in command and '@openai/codex' in command
    assert '@xai-official/grok' not in command


def test_upgrade_exclusions_preserve_all_other_tools(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: calls.append(args[0]) or SimpleNamespace(returncode=0))
    native = []
    monkeypatch.setattr(cli, '_upgrade_native', lambda provider, env: native.append(provider.id) or SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit) as exc:
        cli.upgrade(exclude=['grok'])
    assert exc.value.code == 0
    assert native == ['antigravity']
    command = calls[0] if isinstance(calls[0], list) else calls[0].split()
    assert '@xai-official/grok' not in command


def test_upgrade_native_tool_does_not_run_npm(monkeypatch):
    run = Mock(side_effect=AssertionError('npm must not run'))
    monkeypatch.setattr(cli.subprocess, 'run', run)
    native = []
    monkeypatch.setattr(cli, '_upgrade_native', lambda provider, env: native.append(provider.id) or SimpleNamespace(returncode=0))
    with pytest.raises(SystemExit) as exc:
        cli.upgrade(tools=['antigravity'])
    assert exc.value.code == 0 and native == ['antigravity']


def test_upgrade_rejects_unknown_or_empty_selection():
    with pytest.raises(ValueError, match='Unknown'):
        cli.upgrade(tools=['unknown'])
    with pytest.raises(ValueError, match='No CLI'):
        cli.upgrade(tools=['claude'], exclude=['claude'])
