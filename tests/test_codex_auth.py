"""Regression coverage for profile-scoped Codex API authentication."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from unittest.mock import Mock

import pytest

from claude_china import codex_auth, config_paths, launcher
from claude_china.models import ApiProfile, LoginProfile, profile_to_dict


SECRET = "sk-test-private-credential"
COMMAND = ["node.exe", "package with spaces/codex.js"]


@pytest.fixture(autouse=True)
def isolate_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(config_paths, "config_dir", lambda: tmp_path / ".claudec")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    blocked = Mock(side_effect=AssertionError("A real Codex process must not run in this test"))
    monkeypatch.setattr(codex_auth.process, "run", blocked)
    return blocked


@pytest.fixture
def profile():
    return ApiProfile(name="codex-api", type="codex", api_key=SECRET,
                      base_url="https://api.example.test/v1")


@pytest.fixture
def env(profile):
    return launcher.prepare_environment(profile, base_env={"UNRELATED": "keep"})


def write_auth(env, key=SECRET, mode="apikey", tokens=None):
    path = Path(env["CODEX_HOME"]) / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"auth_mode": mode, "OPENAI_API_KEY": key, "tokens": tokens}),
                    encoding="utf-8")
    return path


def fake_cli(monkeypatch, status="API key configured - [redacted]", channel="stderr"):
    def run(argv, **options):
        if "--with-api-key" in argv:
            write_auth(options["env"], key=options["input"].rstrip("\n"))
            return subprocess.CompletedProcess(argv, 0, "", "API key saved.")
        assert "status" in argv
        return subprocess.CompletedProcess(argv, 0, status if channel == "stdout" else "",
                                           status if channel == "stderr" else "")

    runner = Mock(side_effect=run)
    monkeypatch.setattr(codex_auth.process, "run", runner)
    return runner


def effective_overrides(argv):
    values = {}
    for index, item in enumerate(argv[:-1]):
        if item in ("-c", "--config"):
            key, value = argv[index + 1].split("=", 1)
            values[key] = json.loads(value)
    return values


def test_environment_is_profile_scoped_without_running_or_writing_credentials(profile, isolate_auth, tmp_path):
    parent = {"CODEX_HOME": str(tmp_path / ".codex"), "OPENAI_API_KEY": "old-openai",
              "CODEX_API_KEY": "old-codex", "CODEX_ACCESS_TOKEN": "old-access-token",
              "OPENAI_FEDERATION_RULE_ID": "old-rule", "OPENAI_IDENTITY_TOKEN_FILE": "old-token-file",
              "UNRELATED": "keep"}
    original = dict(parent)
    prepared = launcher.prepare_environment(profile, base_env=parent)

    assert parent == original
    assert prepared["CODEX_HOME"] == str(config_paths.codex_api_home(profile.name).resolve())
    assert prepared["OPENAI_API_KEY"] == SECRET
    assert prepared["OPENAI_BASE_URL"] == profile.base_url
    assert prepared["UNRELATED"] == "keep"
    assert all(name not in prepared for name in
               ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_FEDERATION_RULE_ID",
                "OPENAI_IDENTITY_TOKEN_FILE"))
    assert not Path(prepared["CODEX_HOME"]).exists()
    isolate_auth.assert_not_called()


def test_profile_directories_are_stable_distinct_and_cannot_escape_config_root(tmp_path):
    names = ["first", "second", "../outside", r"..\outside", "中文配置"]
    paths = [config_paths.codex_api_home(name) for name in names]
    assert len(set(paths)) == len(names)
    assert all(path.parent == tmp_path / ".claudec" / "codex-api" for path in paths)
    assert paths == [config_paths.codex_api_home(name) for name in names]


def test_windows_clears_case_variants_of_managed_auth_environment(profile, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    parent = {"codex_home": str(tmp_path / "old-home"), "CoDeX_Api_Key": "old-key",
              "codex_access_token": "old-access-token", "openai_api_key": "old-openai-key",
              "Unrelated_Name": "preserve"}
    prepared = launcher.prepare_environment(profile, base_env=parent)
    assert prepared["CODEX_HOME"] == str(config_paths.codex_api_home(profile.name).resolve())
    assert prepared["OPENAI_API_KEY"] == SECRET
    assert all(name not in prepared for name in parent if name != "Unrelated_Name")
    assert prepared["Unrelated_Name"] == "preserve"


@pytest.mark.parametrize("key", [None, "", " ", "sk\nkey", "sk key", "sk\0key"])
def test_missing_or_multiline_key_fails_before_login(profile, key, isolate_auth):
    profile.api_key = key
    with pytest.raises(ValueError, match="api_key"):
        launcher.prepare_environment(profile, base_env={})
    isolate_auth.assert_not_called()


def test_login_profile_keeps_its_own_credentials_and_skips_api_setup(tmp_path, isolate_auth):
    home = tmp_path / "chatgpt-login"
    home.mkdir()
    cached = home / "auth.json"
    cached.write_text('{"auth_mode":"chatgpt","tokens":{"access_token":"test-only"}}', encoding="utf-8")
    original = cached.read_bytes()
    login = LoginProfile(name="subscription", type="codex", credentials_path=str(home))
    prepared = launcher.prepare_environment(login, base_env={"CODEX_API_KEY": SECRET})

    assert prepared["CODEX_HOME"] == str(home)
    assert "OPENAI_API_KEY" not in prepared and "CODEX_API_KEY" not in prepared
    assert launcher.prepare_profile_command(login, COMMAND, ["login", "status"], prepared) == (
        COMMAND + ["login", "status"])
    assert cached.read_bytes() == original
    isolate_auth.assert_not_called()


@pytest.mark.parametrize("status,channel", [
    ("API key configured - [redacted]", "stderr"),
    ("Logged in using an API key - [redacted]", "stdout"),
])
def test_initial_login_uses_stdin_and_confirms_supported_status(profile, env, monkeypatch, tmp_path,
                                                               status, channel):
    runner = fake_cli(monkeypatch, status, channel)
    result = codex_auth.prepare_command(profile, COMMAND, ["exec", "hello"], env, cwd=str(tmp_path))

    assert runner.call_count == 2
    login, check = runner.call_args_list
    assert login.args[0][:4] == COMMAND + ["login", "--with-api-key"]
    assert login.kwargs["input"] == SECRET + "\n"
    assert SECRET not in repr(login.args)
    assert login.kwargs["capture_output"] is True
    assert login.kwargs["text"] is True
    assert login.kwargs["encoding"] == "utf-8"
    assert login.kwargs["timeout"] > 0
    assert not login.kwargs.get("shell", False)
    assert login.kwargs["cwd"] == str(tmp_path)
    assert check.args[0][:4] == COMMAND + ["login", "status"]
    assert "input" not in check.kwargs
    assert check.kwargs["stdin"] == codex_auth.process.DEVNULL
    expected = {"model_provider": "openai", "forced_login_method": "api",
                "cli_auth_credentials_store": "file", "openai_base_url": profile.base_url}
    assert effective_overrides(result) == expected
    assert effective_overrides(login.args[0]) == expected
    assert effective_overrides(check.args[0]) == expected
    assert result[:4] == COMMAND + ["exec", "hello"]


@pytest.mark.parametrize("mode", ["apikey", None])
def test_matching_cached_key_is_rechecked_without_relogging(profile, env, monkeypatch, mode):
    write_auth(env, mode=mode)
    runner = fake_cli(monkeypatch)
    codex_auth.prepare_command(profile, COMMAND, [], env)
    assert runner.call_count == 1
    assert runner.call_args.args[0][:4] == COMMAND + ["login", "status"]


def test_login_child_can_exclusively_lock_its_credential_file(profile, env, monkeypatch, tmp_path):
    fake = tmp_path / "fake_codex.py"
    fake.write_text(textwrap.dedent("""
        import json
        import os
        from pathlib import Path
        import sys

        home = Path(os.environ["CODEX_HOME"])
        if "--with-api-key" in sys.argv:
            key = sys.stdin.read().strip()
            with (home / "auth.json.lock").open("a+b") as lock:
                lock.seek(0, os.SEEK_END)
                if not lock.tell():
                    lock.write(b"\\0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                (home / "auth.json").write_text(
                    json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": key}),
                    encoding="utf-8",
                )
            print("API key saved.", file=sys.stderr)
        elif "status" in sys.argv:
            print("API key configured - test-only", file=sys.stderr)
        else:
            raise SystemExit("Unexpected fake CLI operation")
        """), encoding="utf-8")
    child_env = dict(env, PYTHONIOENCODING="utf-8")
    if "SystemRoot" in os.environ:
        child_env["SystemRoot"] = os.environ["SystemRoot"]
    # Execute only this temporary Python fixture; no real Codex or user secrets.
    monkeypatch.setattr(codex_auth.process, "run", subprocess.run)
    command = [sys.executable, str(fake)]

    result = codex_auth.prepare_command(profile, command, ["exec", "hello"],
                                       child_env, cwd=str(tmp_path))

    auth = json.loads((Path(env["CODEX_HOME"]) / "auth.json").read_text(encoding="utf-8"))
    assert auth == {"auth_mode": "apikey", "OPENAI_API_KEY": SECRET}
    assert result[:4] == command + ["exec", "hello"]


@pytest.mark.parametrize("old_auth", ["rotated-key", "chatgpt", "corrupt", "non-mapping", "tokens"])
def test_stale_or_invalid_cache_is_replaced_with_selected_key(profile, env, monkeypatch, old_auth):
    path = write_auth(env)
    if old_auth == "rotated-key":
        write_auth(env, key="sk-old-test-key")
    elif old_auth == "chatgpt":
        write_auth(env, mode="chatgpt", tokens={"access_token": "old-test-token"})
    elif old_auth == "tokens":
        write_auth(env, tokens={"access_token": "stale-test-token"})
    else:
        path.write_text("{" if old_auth == "corrupt" else "[]", encoding="utf-8")
    runner = fake_cli(monkeypatch)

    codex_auth.prepare_command(profile, COMMAND, [], env)

    assert runner.call_count == 2
    assert "--with-api-key" in runner.call_args_list[0].args[0]
    assert json.loads(path.read_text(encoding="utf-8"))["OPENAI_API_KEY"] == SECRET


def test_login_failure_stops_without_exposing_output(profile, env, monkeypatch, capsys):
    runner = Mock(return_value=subprocess.CompletedProcess(COMMAND, 1, SECRET, SECRET))
    monkeypatch.setattr(codex_auth.process, "run", runner)
    with pytest.raises(ValueError, match="login failed") as error:
        codex_auth.prepare_command(profile, COMMAND, ["exec"], env)
    assert runner.call_count == 1
    assert SECRET not in str(error.value)
    assert SECRET not in repr(capsys.readouterr())


@pytest.mark.parametrize("cached_key", [False, True])
def test_config_access_error_is_reported_without_exposing_cli_output(
    profile, env, monkeypatch, capsys, cached_key
):
    if cached_key:
        write_auth(env)
    config_path = Path(env["CODEX_HOME"]) / "config.toml"
    stderr = (f"Error loading configuration: Failed to read config file {config_path}: "
              f"Access is denied. (os error 5)\n{SECRET}\n")
    runner = Mock(return_value=subprocess.CompletedProcess(COMMAND, 1, "", stderr))
    monkeypatch.setattr(codex_auth.process, "run", runner)

    with pytest.raises(ValueError, match=r"could not load its configuration.*config\.toml") as error:
        codex_auth.prepare_command(profile, COMMAND, ["exec"], env)

    assert runner.call_count == 1
    assert str(config_path) in str(error.value)
    assert SECRET not in str(error.value)
    assert SECRET not in repr(capsys.readouterr())


@pytest.mark.parametrize("stored", ["missing", "wrong-key", "chatgpt"])
def test_success_exit_without_correct_persisted_credentials_fails(profile, env, monkeypatch, stored):
    def run(argv, **options):
        if stored == "wrong-key":
            write_auth(env, key="another-test-key")
        elif stored == "chatgpt":
            write_auth(env, mode="chatgpt")
        return subprocess.CompletedProcess(argv, 0, "", "API key saved.")
    runner = Mock(side_effect=run)
    monkeypatch.setattr(codex_auth.process, "run", runner)
    with pytest.raises(ValueError, match="login failed"):
        codex_auth.prepare_command(profile, COMMAND, [], env)
    assert runner.call_count == 1


@pytest.mark.parametrize("output,code", [
    ("Logged in using ChatGPT", 0),
    ("API key configured - [redacted]", 1),
    ("An unrecognized authentication state", 0),
])
def test_unconfirmed_status_blocks_launch(profile, env, monkeypatch, capsys, output, code):
    write_auth(env)
    runner = Mock(return_value=subprocess.CompletedProcess(COMMAND, code, SECRET, output))
    monkeypatch.setattr(codex_auth.process, "run", runner)
    with pytest.raises(ValueError, match="did not confirm") as error:
        codex_auth.prepare_command(profile, COMMAND, ["exec"], env)
    assert runner.call_count == 1
    assert SECRET not in str(error.value)
    assert SECRET not in repr(capsys.readouterr())


@pytest.mark.parametrize("error", [
    OSError(SECRET),
    subprocess.TimeoutExpired(COMMAND, 30, output=SECRET, stderr=SECRET),
    subprocess.CalledProcessError(1, COMMAND, output=SECRET, stderr=SECRET),
])
def test_process_errors_are_private_and_fail_closed(profile, env, monkeypatch, capsys, error):
    runner = Mock(side_effect=error)
    monkeypatch.setattr(codex_auth.process, "run", runner)
    with pytest.raises(ValueError, match="session was not started") as caught:
        codex_auth.prepare_command(profile, COMMAND, ["exec"], env)
    assert runner.call_count == 1
    assert SECRET not in str(caught.value)
    assert caught.value.__suppress_context__
    assert SECRET not in repr(capsys.readouterr())


def test_credential_change_during_status_check_is_rejected(profile, env, monkeypatch):
    write_auth(env)

    def changed(argv, **options):
        write_auth(env, mode="chatgpt")
        return subprocess.CompletedProcess(argv, 0, "", "API key configured - [redacted]")

    monkeypatch.setattr(codex_auth.process, "run", changed)
    with pytest.raises(ValueError, match="did not confirm"):
        codex_auth.prepare_command(profile, COMMAND, [], env)


def test_wrong_home_or_unwritable_directory_never_falls_back(profile, env, isolate_auth, tmp_path):
    wrong = dict(env, CODEX_HOME=str(tmp_path / ".codex"))
    with pytest.raises(ValueError, match="does not match"):
        codex_auth.prepare_command(profile, COMMAND, [], wrong)
    home = Path(env["CODEX_HOME"])
    home.parent.mkdir(parents=True)
    home.write_text("occupied by a regular file", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot prepare"):
        codex_auth.prepare_command(profile, COMMAND, [], env)
    isolate_auth.assert_not_called()


def test_auth_overrides_win_and_prompt_after_double_dash_is_preserved(profile, env, monkeypatch):
    fake_cli(monkeypatch)
    arguments = ["exec", "-c", 'forced_login_method="chatgpt"',
                 "--config", 'model_provider="other"', "--",
                 "--remote", "-c", 'forced_login_method="chatgpt"']
    original = list(arguments)
    result = codex_auth.prepare_command(profile, COMMAND, arguments, env)
    boundary = result.index("--")
    assert result[boundary:] == original[original.index("--"):]
    assert effective_overrides(result[:boundary])["forced_login_method"] == "api"
    assert effective_overrides(result[:boundary])["model_provider"] == "openai"
    assert arguments == original


@pytest.mark.parametrize("argument", [
    "--oss", "--local-provider=ollama", "--remote", "--remote-auth-token-env=TOKEN",
])
def test_conflicting_provider_options_fail_before_login(profile, env, isolate_auth, argument):
    with pytest.raises(ValueError, match="local OpenAI-compatible"):
        codex_auth.prepare_command(profile, COMMAND, [argument], env)
    isolate_auth.assert_not_called()


def quiet_launch_environment(monkeypatch):
    from claude_china.desktop import cli_guard, config, playwright_guard

    monkeypatch.setattr(config, "load_desktop_config", lambda: {})
    monkeypatch.setattr(config, "get_safety_settings", lambda data: {"enabled": False, "router_mode": False})
    monkeypatch.setattr(cli_guard, "enabled", lambda data: False)
    monkeypatch.setattr(cli_guard, "prepare", lambda argv, env, data=None: (list(argv), dict(env)))
    monkeypatch.setattr(playwright_guard, "prepare_environment", lambda env, **kwargs: dict(env))


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_cli_launch_authenticates_before_starting_the_session(profile, env, monkeypatch, platform):
    from claude_china.desktop import terminal_host

    quiet_launch_environment(monkeypatch)
    monkeypatch.setattr(launcher.sys, "platform", platform)
    monkeypatch.setattr(launcher, "find_command", lambda kind: "codex.cmd" if platform == "win32" else "codex")
    monkeypatch.setattr(terminal_host, "resolve_cli_argv", lambda kind: COMMAND)
    monkeypatch.setattr(launcher, "prepare_environment", lambda selected: dict(env))
    runner = fake_cli(monkeypatch)
    final = Mock(return_value=subprocess.CompletedProcess([], 0))
    if platform == "win32":
        monkeypatch.setattr(launcher.subprocess, "run", final)
    else:
        monkeypatch.setattr(launcher.os, "execvpe", final)
    calls = Mock()
    calls.attach_mock(runner, "auth")
    calls.attach_mock(final, "session")
    record = profile_to_dict(profile)
    record["default_args"] = ["-c", 'forced_login_method="chatgpt"']

    if platform == "win32":
        with pytest.raises(SystemExit) as result:
            launcher.launch(record, ["exec", "hello"])
        assert result.value.code == 0
        actual = final.call_args.args[0]
        assert not final.call_args.kwargs.get("shell", False)
    else:
        launcher.launch(record, ["exec", "hello"])
        actual = final.call_args.args[1]

    assert [call[0] for call in calls.mock_calls] == ["auth", "auth", "session"]
    assert effective_overrides(actual)["forced_login_method"] == "api"


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_cli_auth_failure_prevents_model_process(profile, env, monkeypatch, capsys, platform):
    from claude_china.desktop import terminal_host

    quiet_launch_environment(monkeypatch)
    monkeypatch.setattr(launcher.sys, "platform", platform)
    monkeypatch.setattr(launcher, "find_command", lambda kind: "codex")
    monkeypatch.setattr(terminal_host, "resolve_cli_argv", lambda kind: COMMAND)
    monkeypatch.setattr(launcher, "prepare_environment", lambda selected: dict(env))
    runner = fake_cli(monkeypatch, "Logged in using ChatGPT")
    final = Mock()
    if platform == "win32":
        monkeypatch.setattr(launcher.subprocess, "run", final)
    else:
        monkeypatch.setattr(launcher.os, "execvpe", final)

    with pytest.raises(SystemExit) as result:
        launcher.launch(profile_to_dict(profile), ["exec", "hello"])

    assert result.value.code == 1
    assert runner.call_count == 2
    final.assert_not_called()
    output = capsys.readouterr()
    assert "did not confirm API key authentication" in output.err
    assert SECRET not in output.err


@pytest.mark.parametrize("resuming", [False, True])
def test_desktop_new_and_resumed_sessions_use_shared_auth(profile, monkeypatch, tmp_path, resuming):
    from claude_china.desktop import config, egress, terminals

    quiet_launch_environment(monkeypatch)
    record = profile_to_dict(profile)
    monkeypatch.setattr(terminals, "_read", lambda: {"profiles": {profile.name: record}})
    monkeypatch.setattr(terminals, "resolve_cli_argv", lambda kind: COMMAND)
    prepare = launcher.prepare_environment
    monkeypatch.setattr(terminals, "prepare_environment",
                        lambda selected, base_env=None: prepare(selected, base_env={}))
    monkeypatch.setattr(config, "get_common_env", lambda data: {})
    monkeypatch.setattr(config, "get_check_system_proxy", lambda data: False)
    monkeypatch.setattr(config, "get_auto_proxy_env", lambda data: False)
    monkeypatch.setattr(config, "launch_settings_changed", lambda old, new: False)
    monkeypatch.setattr(egress, "tun_enabled", lambda *args: False)
    runner = fake_cli(monkeypatch)
    service = terminals.TerminalService(Mock())
    session_id = "12345678-1234-1234-1234-123456789abc"
    monkeypatch.setattr(service, "_session", lambda record, selected: {"directory": str(tmp_path)})

    argv, prepared = service.prepare(profile.name, str(tmp_path), session_id=session_id if resuming else None)

    assert runner.call_count == 2
    assert all(call.kwargs["cwd"] == str(tmp_path.resolve()) for call in runner.call_args_list)
    assert prepared["CODEX_HOME"] == str(config_paths.codex_api_home(profile.name).resolve())
    assert effective_overrides(argv)["forced_login_method"] == "api"
    if resuming:
        assert argv[:4] == COMMAND + ["resume", session_id]


@pytest.mark.parametrize("changed", ["profile", "settings"])
def test_desktop_rejects_configuration_changed_while_authenticating(profile, monkeypatch, tmp_path, changed):
    from claude_china.desktop import config, egress, terminals

    quiet_launch_environment(monkeypatch)
    record = profile_to_dict(profile)
    settings = {"safety_check": False}
    monkeypatch.setattr(terminals, "_read", lambda: {"profiles": {profile.name: record}})
    monkeypatch.setattr(terminals, "resolve_cli_argv", lambda kind: COMMAND)
    prepare = launcher.prepare_environment
    monkeypatch.setattr(terminals, "prepare_environment",
                        lambda selected, base_env=None: prepare(selected, base_env={}))
    monkeypatch.setattr(config, "load_desktop_config", lambda: dict(settings))
    monkeypatch.setattr(config, "get_common_env", lambda data: {})
    monkeypatch.setattr(config, "get_check_system_proxy", lambda data: False)
    monkeypatch.setattr(config, "get_auto_proxy_env", lambda data: False)
    monkeypatch.setattr(config, "launch_settings_changed", lambda old, new: old != new)
    monkeypatch.setattr(egress, "tun_enabled", lambda *args: False)
    runner = fake_cli(monkeypatch)
    authenticate = runner.side_effect

    def change_during_check(argv, **options):
        result = authenticate(argv, **options)
        if "status" in argv:
            if changed == "profile":
                record["api_key"] = "sk-test-new-profile-key"
            else:
                settings["safety_check"] = True
        return result

    runner.side_effect = change_during_check
    with pytest.raises(ValueError, match="配置发生变化"):
        terminals.TerminalService(Mock()).prepare(profile.name, str(tmp_path))
    assert runner.call_count == 2
