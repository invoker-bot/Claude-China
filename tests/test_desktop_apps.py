import pytest

from src.claude_china.desktop.apps import AppSpec, APP_REGISTRY, get_app


def test_registry_has_three_known_apps():
    ids = [a.id for a in APP_REGISTRY]
    assert ids == ["claude", "codex", "grok-bot"]


def test_registry_entries_are_appspec_with_identifiers():
    claude = get_app("claude")
    assert isinstance(claude, AppSpec)
    assert claude.display == "Claude"
    assert claude.win_aumid == "Claude_pzs8sxrjxfjjc!Claude"
    assert claude.win_package_family == "Claude_pzs8sxrjxfjjc"
    assert claude.mac_bundle_name == "Claude.app"
    assert claude.mac_bundle_id == "com.anthropic.claudefordesktop"


def test_get_app_unknown_raises():
    with pytest.raises(KeyError):
        get_app("nope")
    with pytest.raises(KeyError):
        get_app("chatgpt")
