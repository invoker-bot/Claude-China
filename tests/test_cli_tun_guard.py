from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.claude_china.desktop import cli_guard, egress, playwright_guard


TUNNEL = {"guid": "769f00ba-f302-4549-a337-7d2f44f8e8b1", "luid": 123,
          "index": 42, "name": "test", "addresses": ["198.18.44.1"]}
SETTINGS = {"network_guard": {"playwright": True}, "network_guard_include_cli": True}


def test_guarded_node_is_private_and_changes_with_the_source(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_guard, "runtime_dir", lambda: tmp_path / "guarded")
    node = tmp_path / "node.exe"
    node.write_bytes(b"first runtime")
    first = cli_guard.guarded_node(node, create=True)
    assert first != node and first.read_bytes() == node.read_bytes()
    assert cli_guard.guarded_node(node) == first
    node.write_bytes(b"updated runtime")
    with pytest.raises(egress.GuardError):
        cli_guard.guarded_node(node)
    second = cli_guard.guarded_node(node, create=True)
    assert second != first and second.read_bytes() == node.read_bytes()


def test_guarded_cli_uses_registered_node_and_drops_proxy_variables(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_guard, "runtime_dir", lambda: tmp_path / "guarded")
    node = tmp_path / "node.exe"
    node.write_bytes(b"runtime")
    guarded = cli_guard.guarded_node(node, create=True)
    policies = {"playwright": {"mode": "tun", "executables": [str(guarded)], "tunnel": TUNNEL}}

    class Store:
        def read(self):
            return deepcopy(policies)

        def verify(self, value):
            return value == policies

    monkeypatch.setattr(egress, "_store", Store)
    monkeypatch.setattr(playwright_guard, "tunnel_live", lambda tunnel: True)
    argv, env = cli_guard.prepare([str(node), "wrapper.js"],
                                  {"HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "bad",
                                   "CLAUDEC_BROWSER_GUARD_HELPER": "helper",
                                   "NODE_OPTIONS": "--require=" + json.dumps(playwright_guard.HOOK.resolve().as_posix())}, SETTINGS)
    assert argv == [str(guarded), "wrapper.js"]
    assert "HTTP_PROXY" not in env and "ALL_PROXY" not in env
    assert env["NO_PROXY"] == "*" and env["CLAUDEC_CLI_GUARD"] == "1"

    with pytest.raises(egress.GuardError):
        cli_guard.prepare([str(node), "wrapper.js"], {}, SETTINGS)
    policies["playwright"]["executables"] = []
    with pytest.raises(egress.GuardError):
        cli_guard.prepare([str(node), "wrapper.js"], env, SETTINGS)


def test_guarded_cli_cannot_start_after_the_tunnel_disconnects(tmp_path, monkeypatch):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"cli")
    policy = {"playwright": {"mode": "tun", "executables": [str(exe)], "tunnel": TUNNEL}}
    monkeypatch.setattr(egress, "_store", lambda: type("Store", (), {
        "read": lambda self: deepcopy(policy), "verify": lambda self, p: True})())
    monkeypatch.setattr(playwright_guard, "tunnel_live", lambda tunnel: False)
    with pytest.raises(egress.GuardError):
        cli_guard.prepare([str(exe)], {"CLAUDEC_BROWSER_GUARD_HELPER": "helper",
                          "NODE_OPTIONS": "--require=" + json.dumps(playwright_guard.HOOK.resolve().as_posix())}, SETTINGS)


def test_disabling_cli_guard_removes_inherited_cli_preload_marker():
    argv, env = cli_guard.prepare(["node.exe", "wrapper.js"],
                                  {"CLAUDEC_CLI_GUARD": "1", "OTHER": "keep"},
                                  {"network_guard": {"playwright": True}, "network_guard_include_cli": False})
    assert argv == ["node.exe", "wrapper.js"]
    assert env == {"OTHER": "keep"}


def test_discover_registers_native_cli_and_a_private_node_not_the_shared_node(tmp_path, monkeypatch):
    from src.claude_china import config as cli_config
    from src.claude_china.desktop import terminal_host

    monkeypatch.setattr(cli_guard, "runtime_dir", lambda: tmp_path / "guarded")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    claude = tmp_path / "claude.exe"
    node = tmp_path / "node.exe"
    codex_entry = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    codex_exe = codex_entry.parent.parent / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
    grok_entry = tmp_path / "node_modules" / "@xai-official" / "grok" / "bin" / "grok"
    grok_exe = tmp_path / "grok-profile" / "bin" / "grok.exe"
    for path in (claude, node, codex_entry, codex_exe, grok_entry, grok_exe):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    monkeypatch.setattr(terminal_host, "resolve_cli_argv", lambda kind: {
        "claude": [str(claude)], "codex": [str(node), str(codex_entry)],
        "grok": [str(node), str(grok_entry)]}[kind])
    monkeypatch.setattr(cli_config, "load_config", lambda: {"profiles": {
        "login": {"type": "grok", "credentials_path": str(grok_exe.parent.parent)}}})
    targets = set(cli_guard.discover(create=True))
    assert targets == {str(path.resolve()) for path in (claude, codex_exe, grok_exe,
                                                         cli_guard.guarded_node(node))}
    assert str(node.resolve()) not in targets
