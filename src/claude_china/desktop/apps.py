from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class AppSpec:
    """Platform-agnostic identity of a supported AI desktop app.

    Windows: MSIX identity or a registered/per-user executable.
    macOS:   .app bundle name, with a bundle id when known.
    Linux:   known desktop commands, never the terminal CLI with the same brand.
    """
    id: str
    display: str
    win_aumid: str
    win_package_family: str
    mac_bundle_name: str
    mac_bundle_id: str
    win_executable: str = ""
    win_uninstall_key: str = ""
    linux_commands: Tuple[str, ...] = ()


APP_REGISTRY: List[AppSpec] = [
    AppSpec(
        id="claude",
        display="Claude",
        win_aumid="Claude_pzs8sxrjxfjjc!Claude",
        win_package_family="Claude_pzs8sxrjxfjjc",
        mac_bundle_name="Claude.app",
        mac_bundle_id="com.anthropic.claudefordesktop",
    ),
    AppSpec(
        id="codex",
        display="Codex",
        win_aumid="OpenAI.Codex_2p2nqsd0c76g0!App",
        win_package_family="OpenAI.Codex_2p2nqsd0c76g0",
        mac_bundle_name="Codex.app",
        mac_bundle_id="com.openai.codex",
    ),
    AppSpec(
        id="grok-bot",
        display="Grok Bot",
        win_aumid="",
        win_package_family="",
        mac_bundle_name="Grok Bot.app",
        mac_bundle_id="",
        win_executable="Grok Bot.exe",
        win_uninstall_key="8db316bb-b3e2-5dd2-9554-ecccb62be362",
        linux_commands=("grok-bot",),
    ),
]

_BY_ID = {a.id: a for a in APP_REGISTRY}


def get_app(app_id: str) -> AppSpec:
    """Return the AppSpec for app_id, or raise KeyError if unknown."""
    return _BY_ID[app_id]
