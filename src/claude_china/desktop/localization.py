"""Shared desktop message catalogs. UI language never changes the launch environment."""

from functools import lru_cache
import json
import locale
import os
from pathlib import Path
import plistlib
import re
import sys

LANGUAGES = ("system", "zh-CN", "zh-TW", "en")


def system_language():
    try:
        if sys.platform == "win32":
            import ctypes
            return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "en")
        if sys.platform == "darwin":
            with (Path.home() / "Library/Preferences/.GlobalPreferences.plist").open("rb") as stream:
                preferred = plistlib.load(stream).get("AppleLanguages", [])
            if preferred and isinstance(preferred[0], str):
                return preferred[0]
        return (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
                or os.environ.get("LANGUAGE", "").split(":")[0]
                or os.environ.get("LANG") or locale.getlocale()[0] or "en")
    except (OSError, ValueError, AttributeError, TypeError):
        return "en"


def resolve_language(selected, system=None):
    if selected in ("zh-CN", "zh-TW", "en"):
        return selected
    value = (system_language() if system is None else system) or "en"
    parts = value.replace("_", "-").split(".")[0].split("@")[0].lower().split("-")
    if parts[0] != "zh":
        return "en"
    if "hans" in parts:
        return "zh-CN"
    return "zh-TW" if any(part in parts for part in ("hant", "tw", "hk", "mo")) else "zh-CN"


@lru_cache(maxsize=1)
def catalogs():
    return json.loads((Path(__file__).parent / "ui/locales.json").read_text(encoding="utf-8"))


def locale_data(selected):
    resolved = resolve_language(selected)
    return {"language": selected, "resolved": resolved,
            "messages": dict(catalogs().get(resolved, {}))}


def translate(source, language, *values):
    message = catalogs().get(language, {}).get(source, source)
    # Substitute once; literal braces and message-like user values stay intact.
    return re.sub(r"\{(\d+)\}", lambda match: str(values[int(match[1])])
                  if int(match[1]) < len(values) else match[0], message)


def translate_message(source, language, depth=0):
    """Render a completed diagnostic at native/terminal presentation boundaries."""
    if language == 'zh-CN' or depth > 4:
        return source
    messages = catalogs().get(language, {})
    if source in messages:
        return messages[source]
    nested = ('安全检查未通过：{0} 已取消启动。', '安全检查未通过：{0}',
              '{0} 已取消启动。', '{0}已取消启动。',
              '出口位于统一禁止地区：{0}，禁止启动。', '{0}格式无效。', '请填写{0}。')
    for template in sorted(messages, key=len, reverse=True):
        if not re.search(r'\{\d+\}', template):
            continue
        indices = re.findall(r'\{(\d+)\}', template)
        pattern = ''.join('(.*?)' if re.fullmatch(r'\{\d+\}', part) else re.escape(part)
                          for part in re.split(r'(\{\d+\})', template))
        match = re.fullmatch(pattern, source, flags=re.DOTALL)
        if match:
            values = {index: value for index, value in zip(indices, match.groups())}
            if template in nested:
                values = {index: translate_message(value, language, depth + 1)
                          for index, value in values.items()}
            return re.sub(r'\{(\d+)\}', lambda item: values[item[1]], messages[template])
    return source


def display_message(source):
    from . import config
    try:
        language = resolve_language(config.get_language(config.load_desktop_config()))
        return translate_message(source, language)
    except Exception:
        # A display-language failure must never conceal the original launch error.
        return source


NATIVE_MESSAGES = {
    "global.quitConfirmation": "确定退出吗？", "global.ok": "确定",
    "global.quit": "退出", "global.cancel": "取消", "global.saveFile": "保存文件",
    "cocoa.menu.about": "关于", "cocoa.menu.services": "服务", "cocoa.menu.view": "显示",
    "cocoa.menu.edit": "编辑", "cocoa.menu.hide": "隐藏", "cocoa.menu.hideOthers": "隐藏其他应用",
    "cocoa.menu.showAll": "显示全部", "cocoa.menu.quit": "退出", "cocoa.menu.fullscreen": "进入全屏",
    "cocoa.menu.cut": "剪切", "cocoa.menu.copy": "复制", "cocoa.menu.paste": "粘贴",
    "cocoa.menu.selectAll": "全选", "windows.fileFilter.allFiles": "所有文件",
    "windows.fileFilter.otherFiles": "其他文件类型", "linux.openFile": "打开文件",
    "linux.openFiles": "打开文件", "linux.openFolder": "打开文件夹",
}


def native_labels(translator):
    return {key: translator(source) for key, source in NATIVE_MESSAGES.items()}
