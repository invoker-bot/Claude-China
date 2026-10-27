import os
import pytest
from unittest.mock import patch, MagicMock
from src.claude_china.models import ApiProfile, LoginProfile
from src.claude_china.launcher import (
    ENV_MAP,
    prepare_environment,
    resolve_default_args,
    merge_launch_args,
)


@pytest.fixture(autouse=True)
def isolate_desktop_config(monkeypatch, tmp_path):
    from src.claude_china.desktop import config as desktop_config

    monkeypatch.setattr(desktop_config, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")


def test_prepare_env_api_mode():
    """Test environment preparation for API mode"""
    profile = ApiProfile(
        name="test-api",
        type="claude",
        base_url="https://api.anthropic.com",
        token="sk-ant-test"
    )

    env = prepare_environment(profile)

    assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-test"


def test_prepare_env_api_mode_clears_stale_managed_vars():
    """API mode should not inherit stale managed vars from the parent shell"""
    with patch.dict(os.environ, {
        "ANTHROPIC_BASE_URL": "https://old.url",
        "ANTHROPIC_AUTH_TOKEN": "old-token",
        "CLAUDE_CONFIG_DIR": "/tmp/old-claude",
        "OPENAI_API_KEY": "old-openai-key",
        "XAI_API_KEY": "old-xai-key",
        "GROK_CLI_CHAT_PROXY_BASE_URL": "https://old-grok.url",
        "GROK_HOME": "/tmp/old-grok",
        "HTTP_PROXY": "http://127.0.0.1:9999",
        "HTTPS_PROXY": "http://127.0.0.1:9999",
    }):
        profile = ApiProfile(
            name="test-api",
            type="claude",
            base_url="https://api.anthropic.com",
            token="sk-ant-test"
        )

        env = prepare_environment(profile)

        assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-test"
        assert "CLAUDE_CONFIG_DIR" not in env
        assert "OPENAI_API_KEY" not in env
        assert "XAI_API_KEY" not in env
        assert "GROK_CLI_CHAT_PROXY_BASE_URL" not in env
        assert "GROK_HOME" not in env
        assert "HTTP_PROXY" not in env
        assert "HTTPS_PROXY" not in env


def test_prepare_env_login_mode():
    """Test environment preparation for login mode"""
    profile = LoginProfile(
        name="test-login",
        type="claude",
        credentials_path="~/.claude-profiles/account-a"
    )

    env = prepare_environment(profile)

    # Should NOT have API environment variables
    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    # Should have CLAUDE_CONFIG_DIR with expanded path
    expected_path = os.path.expanduser("~/.claude-profiles/account-a")
    assert env["CLAUDE_CONFIG_DIR"] == expected_path


def test_prepare_env_with_proxy():
    """Test environment preparation with proxy"""
    profile = ApiProfile(
        name="test-proxy",
        type="grok",
        base_url="https://api.x.ai/v1",
        api_key="xai-test",
        proxy="http://127.0.0.1:7890"
    )

    env = prepare_environment(profile)

    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_gemini_is_not_a_supported_launcher():
    assert "gemini" not in ENV_MAP
    assert ENV_MAP["grok"]["cmd"] == "grok"

    with pytest.raises(ValueError, match="Unknown profile type 'gemini'"):
        prepare_environment(
            ApiProfile(name="legacy-gemini", type="gemini", api_key="old-key")
        )


def test_prepare_env_grok_api_mode():
    profile = ApiProfile(
        name="test-grok-api",
        type="grok",
        base_url="https://grok-proxy.example/v1",
        api_key="xai-test",
    )

    env = prepare_environment(profile)

    assert env["XAI_API_KEY"] == "xai-test"
    assert env["GROK_CLI_CHAT_PROXY_BASE_URL"] == "https://grok-proxy.example/v1"


def test_prepare_env_grok_api_mode_allows_default_endpoint():
    profile = ApiProfile(
        name="test-grok-api",
        type="grok",
        api_key="xai-test",
    )

    env = prepare_environment(profile)

    assert env["XAI_API_KEY"] == "xai-test"
    assert "GROK_CLI_CHAT_PROXY_BASE_URL" not in env


def test_prepare_env_grok_official_base_url_does_not_replace_chat_proxy():
    profile = ApiProfile(
        name="test-grok-api",
        type="grok",
        base_url="https://api.x.ai/v1",
        api_key="xai-test",
    )

    env = prepare_environment(profile)

    assert env["XAI_API_KEY"] == "xai-test"
    assert "GROK_CLI_CHAT_PROXY_BASE_URL" not in env


def test_prepare_env_grok_login_mode():
    profile = LoginProfile(
        name="test-grok-login",
        type="grok",
        credentials_path="~/.grok-profiles/account-a",
    )

    env = prepare_environment(profile)

    assert "XAI_API_KEY" not in env
    assert "GROK_CLI_CHAT_PROXY_BASE_URL" not in env
    assert env["GROK_HOME"] == os.path.expanduser("~/.grok-profiles/account-a")


def test_manual_claude_login_suppresses_browser_only_for_the_selected_profile(monkeypatch, tmp_path):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    manual = LoginProfile(name="manual", type="claude", credentials_path=str(tmp_path / "manual"),
                          manual_browser_login=True)
    automatic = LoginProfile(name="automatic", type="claude", credentials_path=str(tmp_path / "auto"),
                             manual_browser_login=False)
    original = {"BROWSER": "user-browser", "OTHER": "keep"}
    enabled = launcher.prepare_environment(manual, base_env=original)
    assert enabled["BROWSER"] == r"\\.\NUL"
    assert enabled["OTHER"] == "keep" and original["BROWSER"] == "user-browser"
    assert launcher.prepare_environment(automatic, base_env=original)["BROWSER"] == "user-browser"


@pytest.mark.parametrize('browser', [None, 'my-browser'])
def test_nested_auto_profile_restores_browser_after_manual_profile(monkeypatch, tmp_path, browser):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    manual = LoginProfile(name='manual', type='claude', credentials_path=str(tmp_path / 'manual'), manual_browser_login=True)
    automatic = LoginProfile(name='auto', type='claude', credentials_path=str(tmp_path / 'auto'), manual_browser_login=False)
    original = {'BROWSER': browser} if browser is not None else {}
    first = launcher.prepare_environment(manual, base_env=original)
    second = launcher.prepare_environment(automatic, base_env=first)
    assert second.get('BROWSER') == browser
    assert 'CLAUDEC_MANUAL_BROWSER_LOGIN' not in second
    assert 'CLAUDEC_PREVIOUS_BROWSER' not in second


def test_nested_auto_profile_keeps_a_browser_changed_by_the_child(monkeypatch, tmp_path):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    manual = LoginProfile(name='manual', type='claude', credentials_path=str(tmp_path / 'manual'), manual_browser_login=True)
    automatic = LoginProfile(name='auto', type='claude', credentials_path=str(tmp_path / 'auto'), manual_browser_login=False)
    first = launcher.prepare_environment(manual, base_env={'BROWSER': 'original'})
    first['BROWSER'] = 'changed-by-child'
    assert launcher.prepare_environment(automatic, base_env=first)['BROWSER'] == 'changed-by-child'


def test_manual_claude_login_uses_unix_null_device(monkeypatch, tmp_path):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    profile = LoginProfile(name='manual', type='claude', credentials_path=str(tmp_path / 'account'), manual_browser_login=True)
    assert launcher.prepare_environment(profile, base_env={})['BROWSER'] == '/dev/null'


def test_claude_login_defaults_to_manual_but_other_profiles_do_not(monkeypatch, tmp_path):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, 'platform', 'win32')
    original = {'BROWSER': 'my-browser'}
    claude = LoginProfile(name='claude', type='claude', credentials_path=str(tmp_path / 'claude'))
    grok = LoginProfile(name='grok', type='grok', credentials_path=str(tmp_path / 'grok'))
    assert launcher.prepare_environment(claude, base_env=original)['BROWSER'] == r'\\.\NUL'
    assert launcher.prepare_environment(grok, base_env=original)['BROWSER'] == 'my-browser'


def test_prepare_env_login_clears_api_vars():
    """Test that login mode clears API environment variables"""
    # Set up environment with existing API variables
    with patch.dict(os.environ, {
        "ANTHROPIC_BASE_URL": "https://old.url",
        "ANTHROPIC_AUTH_TOKEN": "old-token"
    }):
        profile = LoginProfile(
            name="test-login",
            type="claude",
            credentials_path="~/.claude-profiles/account-a"
        )

        env = prepare_environment(profile)

        # Should be cleared
        assert "ANTHROPIC_BASE_URL" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_prepare_env_codex_api_mode():
    """Test environment preparation for codex API mode"""
    profile = ApiProfile(
        name="test-codex-api",
        type="codex",
        base_url="https://api.openai.com/v1",
        api_key="sk-test"
    )

    env = prepare_environment(profile)

    # Should have both OPENAI_API_KEY and OPENAI_BASE_URL
    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["OPENAI_BASE_URL"] == "https://api.openai.com/v1"


def test_prepare_env_codex_login_mode():
    """Test environment preparation for codex login mode"""
    profile = LoginProfile(
        name="test-codex-login",
        type="codex",
        credentials_path="~/.codex-profiles/account-a"
    )

    env = prepare_environment(profile)

    # Should NOT have API environment variables
    assert "OPENAI_API_KEY" not in env
    # Should have CODEX_HOME with expanded path
    expected_path = os.path.expanduser("~/.codex-profiles/account-a")
    assert env["CODEX_HOME"] == expected_path


# ---------------------------------------------------------------------------
# default_args handling
# ---------------------------------------------------------------------------

def test_resolve_default_args_none():
    assert resolve_default_args(None) == []


def test_resolve_default_args_empty():
    assert resolve_default_args("") == []
    assert resolve_default_args([]) == []


def test_resolve_default_args_list_passthrough():
    assert resolve_default_args(["--model", "opus"]) == ["--model", "opus"]


def test_resolve_default_args_string_split():
    assert resolve_default_args("--model claude-opus-4-5 -p hi") == [
        "--model", "claude-opus-4-5", "-p", "hi"
    ]


def test_resolve_default_args_string_with_quotes():
    # POSIX shlex preserves quoted whitespace as a single token
    assert resolve_default_args('--prompt "hello world"') == [
        "--prompt", "hello world"
    ]


def test_resolve_default_args_invalid_type_raises():
    with pytest.raises(TypeError):
        resolve_default_args(42)


def test_merge_launch_args_no_defaults():
    """No profile defaults → returns extra_args unchanged."""
    assert merge_launch_args(["--resume"], None) == ["--resume"]


def test_merge_launch_args_only_defaults():
    """No CLI extras, only profile defaults."""
    assert merge_launch_args([], ["--model", "opus"]) == ["--model", "opus"]


def test_merge_launch_args_order_b_extras_before_defaults():
    """Q3 design = B: command-line first, defaults appended (defaults win)."""
    result = merge_launch_args(
        ["--model", "sonnet"],
        ["--model", "opus", "--dangerously-skip-permissions"],
    )
    assert result == [
        "--model", "sonnet",
        "--model", "opus", "--dangerously-skip-permissions",
    ]


def test_merge_launch_args_string_form_defaults():
    """default_args as string is shlex-split before merging."""
    result = merge_launch_args(["-p", "hi"], "--model opus")
    assert result == ["-p", "hi", "--model", "opus"]


def test_merge_launch_args_use_default_false_skips():
    """--no-default-args escape hatch: defaults dropped entirely."""
    result = merge_launch_args(
        ["--model", "sonnet"],
        ["--model", "opus"],
        use_default_args=False,
    )
    assert result == ["--model", "sonnet"]


# ---------------------------------------------------------------------------
# Windows launch encoding fix (TDD verification)
# ---------------------------------------------------------------------------

def test_launch_on_windows_uses_powershell_wrapper():
    """Verify the encoding wrapper is used on Windows (TDD test for the fix)."""
    with patch("src.claude_china.launcher.sys.platform", "win32"):
        with patch("src.claude_china.launcher.shutil.which", return_value="claude.cmd"):
            with patch("src.claude_china.launcher.subprocess.run") as mock_run:
                from src.claude_china.launcher import launch
                with patch("sys.exit"):
                    launch(
                        {"type": "claude", "name": "fox-claude", "base_url": None, "token": None},
                        ["--model", "opus"],
                        use_default_args=True,
                    )
                args, kwargs = mock_run.call_args
                cmd = args[0]
                assert cmd == (
                    'powershell.exe -NoProfile -Command '
                    '"$OutputEncoding = [console]::OutputEncoding = [Text.Encoding]::UTF8; '
                    '& claude.cmd --model opus"'
                )
                assert kwargs["shell"] is True


def test_launch_on_non_windows_uses_execvpe():
    """Unix launches the target with the prepared environment."""
    with patch("src.claude_china.launcher.sys.platform", "linux"):
        with patch("src.claude_china.launcher.shutil.which", return_value="claude"):
            with patch("src.claude_china.launcher.os.execvpe") as mock_exec:
                from src.claude_china.launcher import launch
                with patch("sys.exit"):
                    launch(
                        {"type": "claude", "name": "fox-claude", "base_url": None, "token": None},
                        [],
                        use_default_args=True,
                    )
                mock_exec.assert_called_once()


def test_unix_launch_passes_clean_environment_without_leaking_parent_values(monkeypatch):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    monkeypatch.setattr(launcher, 'find_command', lambda _: '/usr/bin/claude')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'stale-parent-token')
    with patch.object(launcher.os, 'execvp') as old_exec, patch.object(launcher.os, 'execvpe') as new_exec:
        launcher.launch({'name': 'test', 'type': 'claude', 'mode': 'api'}, [])
    old_exec.assert_not_called()
    env = new_exec.call_args.args[2]
    assert 'ANTHROPIC_AUTH_TOKEN' not in env


def test_launch_windows_passes_env_correctly():
    """Env vars set by prepare_environment reach the PowerShell wrapper."""
    with patch("src.claude_china.launcher.sys.platform", "win32"):
        with patch("src.claude_china.launcher.shutil.which", return_value="claude.cmd"):
            with patch("src.claude_china.launcher.subprocess.run") as mock_run:
                from src.claude_china.launcher import launch
                with patch("sys.exit"):
                    launch(
                        {"type": "claude", "name": "fox-claude", "base_url": "https://example.com", "token": "sk-xxx"},
                        [],
                        use_default_args=True,
                    )
                env = mock_run.call_args[1]["env"]
                assert env["ANTHROPIC_BASE_URL"] == "https://example.com"
                assert "ANTHROPIC_AUTH_TOKEN" in env


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_launch_grok_uses_updated_npm_entry_instead_of_shadowing_path(monkeypatch, tmp_path, platform):
    from types import SimpleNamespace
    from src.claude_china import launcher

    profile_home = str(tmp_path / "grok-account")
    npm_command = str(tmp_path / "npm-prefix" / "bin" / "grok")
    monkeypatch.setattr(launcher.sys, "platform", platform)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/old-install/grok")
    monkeypatch.setattr(launcher, "find_npm_installation", lambda: SimpleNamespace(command=npm_command, version="1.0.46"))
    with patch.object(launcher.os, "execvpe") as execute:
        launcher.launch({"type": "grok", "mode": "login", "name": "grok-account", "credentials_path": profile_home}, ["--version"])
    assert execute.call_args.args[:2] == (npm_command, [npm_command, "--version"])
    assert execute.call_args.args[2]["GROK_HOME"] == profile_home


def test_launch_grok_without_npm_preserves_native_install(monkeypatch, tmp_path):
    from src.claude_china import launcher

    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/native/bin/grok")
    monkeypatch.setattr(launcher, "find_npm_installation", lambda: None)
    with patch.object(launcher.os, "execvpe") as execute:
        launcher.launch({"type": "grok", "mode": "login", "credentials_path": str(tmp_path / "native-account")}, ["--version"])
    assert execute.call_args.args[:2] == ("/native/bin/grok", ["/native/bin/grok", "--version"])
