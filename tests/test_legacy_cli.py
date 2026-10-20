import runpy
import sys
import types
from pathlib import Path

import pytest

from src.claude_china import __version__
from src.claude_china.cli import app


LEGACY_CLI = (
    Path(__file__).resolve().parents[1]
    / "compat" / "ai-code-switcher" / "src" / "code_ai" / "cli.py"
)


@pytest.fixture
def legacy_cli(monkeypatch):
    target = types.ModuleType("claude_china.cli")
    target.app = app
    monkeypatch.setitem(sys.modules, "claude_china.cli", target)
    return runpy.run_path(str(LEGACY_CLI))


def test_legacy_version_warns_on_stderr_without_changing_stdout(
    legacy_cli, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["code-ai", "--version"])
    with pytest.raises(SystemExit) as exc:
        legacy_cli["main"]()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"claudec {__version__}"
    assert "deprecated" in captured.err
    assert "ai-code-switcher" in captured.err
    assert "code-ai" in captured.err
    assert "python -m pip install --upgrade claude-china" in captured.err
    assert "claudec" in captured.err


def test_legacy_cli_preserves_invalid_command_exit_code(legacy_cli, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["code-ai", "not-a-command"])
    with pytest.raises(SystemExit) as exc:
        legacy_cli["main"]()
    assert exc.value.code == 2
    assert "deprecated" in capsys.readouterr().err


def test_legacy_cli_forwards_arguments_and_exit_status(legacy_cli, monkeypatch):
    argv = ["code-ai", "run", "my-profile", "--model", "some model", "--", "-p", "a b"]
    monkeypatch.setattr(sys, "argv", argv)
    calls = []

    def target_app(**kwargs):
        calls.append((list(sys.argv), kwargs))
        raise SystemExit(17)

    monkeypatch.setattr(sys.modules["claude_china.cli"], "app", target_app)
    with pytest.raises(SystemExit) as exc:
        legacy_cli["main"]()
    assert exc.value.code == 17
    assert calls == [(argv, {"prog_name": "claudec"})]


def test_legacy_desktop_shortcut_can_run_without_console(legacy_cli, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        sys.modules["claude_china.cli"], "app", lambda **kwargs: calls.append(kwargs)
    )
    # pythonw.exe has no stderr; old desktop shortcuts must still open the app.
    monkeypatch.setitem(
        legacy_cli["main"].__globals__, "sys", types.SimpleNamespace(stderr=None)
    )
    legacy_cli["main"]()
    assert calls == [{"prog_name": "claudec"}]
    assert capsys.readouterr().out == ""


def test_legacy_python_module_entrypoint_warns_and_delegates(
    legacy_cli, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["code_ai.cli", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(LEGACY_CLI), run_name="__main__")
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"claudec {__version__}"
    assert "deprecated" in captured.err
