from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class AppSpec:
    """Platform-agnostic identity of a supported AI desktop app.

    Windows: launch by AUMID; detect/monitor by PackageFamilyName (version-proof).
    macOS:   launch/detect by .app bundle name + bundle id.
    """
    id: str
    display: str
    win_aumid: str
    win_package_family: str
    mac_bundle_name: str
    mac_bundle_id: str


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
]

_BY_ID = {a.id: a for a in APP_REGISTRY}


def get_app(app_id: str) -> AppSpec:
    """Return the AppSpec for app_id, or raise KeyError if unknown."""
    return _BY_ID[app_id]
