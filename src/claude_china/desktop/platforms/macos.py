import importlib.resources
import os
import plistlib
import shlex
import shutil
import sys

from . import base
from .. import process as subprocess
from ..proxy import SystemProxyError, http_proxy_address
from .base import AppStatus

_IGNORED_RUNNING_PROCESS_NAMES = {"browser_crashpad_handler"}


class MacBackend:
    # ---- detection ----
    def detect(self, app, override_path=None) -> AppStatus:
        if override_path and os.path.exists(override_path):
            binary = self._bundle_binary(override_path) or override_path
            return AppStatus(app.id, found=True, direct=True,
                             launch_target=binary, match_root=override_path)
        bundle = self._find_bundle(app)
        if bundle:
            # Launch the bundle executable directly so per-app environment
            # variables reach it instead of being dropped by Launch Services.
            binary = self._bundle_binary(bundle)
            if binary and os.path.isfile(binary):
                return AppStatus(app.id, found=True, direct=True,
                                 launch_target=binary, match_root=bundle)
            return AppStatus(app.id, found=True, direct=False,
                             launch_target=bundle, match_root=bundle)
        return AppStatus(app.id, found=False)

    def _find_bundle(self, app) -> str:
        query = (f"kMDItemCFBundleIdentifier == '{app.mac_bundle_id}'"
                 if app.mac_bundle_id else
                 f"kMDItemFSName == '{app.mac_bundle_name}' && "
                 "kMDItemContentType == 'com.apple.application-bundle'")
        try:
            out = subprocess.check_output(
                ["mdfind", query],
                text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.endswith(".app") and os.path.exists(line):
                    return line
        except Exception:
            pass
        for base_dir in ("/Applications", os.path.expanduser("~/Applications")):
            candidate = os.path.join(base_dir, app.mac_bundle_name)
            if os.path.exists(candidate):
                return candidate
        return ""

    def _bundle_binary(self, bundle: str) -> str:
        plist = os.path.join(bundle, "Contents", "Info.plist")
        try:
            with open(plist, "rb") as f:
                data = plistlib.load(f)
            name = data.get("CFBundleExecutable")
            if name:
                return os.path.join(bundle, "Contents", "MacOS", name)
        except Exception:
            pass
        return ""

    # ---- proxy ----
    def system_http_proxy(self) -> str:
        values = self._proxy_values(self._scutil_output())
        if values.get("HTTPEnable") != "1":
            raise SystemProxyError("无法读取已启用的系统 HTTP 代理；仅有 PAC 或 SOCKS 设置不受支持。")
        return http_proxy_address(values.get("HTTPProxy"), values.get("HTTPPort"))

    @staticmethod
    def _proxy_values(output):
        values = {}
        depth = 0
        root_depth = 1 if output.lstrip().startswith("<dictionary>") else 0
        for line in output.splitlines():
            if depth == root_depth:
                name, separator, value = line.strip().partition(" : ")
                if separator and not value.startswith("<"):
                    if name in values:
                        raise SystemProxyError("系统 HTTP 代理设置包含重复字段。")
                    values[name] = value.strip()
            depth += line.count("{") - line.count("}")
        return values

    def safety_proxy(self):
        import re

        output = self._scutil_output()
        if not output:
            raise SystemProxyError("无法读取 macOS 系统代理。")
        values = self._proxy_values(output)
        if any(values.get(key) == "1" for key in (
                "ProxyAutoConfigEnable", "ProxyAutoDiscoveryEnable", "SOCKSEnable")):
            raise SystemProxyError("自动代理或 SOCKS 代理无法确认单一 HTTP 出口。")
        proxy = None
        if values.get("HTTPSEnable") == "1":
            proxy = http_proxy_address(values.get("HTTPSProxy"), values.get("HTTPSPort"))
        exclusions = re.search(r"ExceptionsList\s*:\s*<array>\s*\{([^}]*)\}", output)
        bypass = ",".join(re.findall(r"\d+\s*:\s*([^\n]+)", exclusions.group(1))) if exclusions else ""
        return {"proxy": proxy, "bypass": bypass}

    def proxy_enabled(self) -> bool:
        return self._parse_scutil(self._scutil_output())

    # ---- browser WebRTC policy ----
    def privacy_snapshot(self):
        return {"supported": False, "tun": None,
                "ipv6": {"default": None, "tunnel": None}, "policies": {}}

    def apply_webrtc_policy(self, browser, value):
        raise ValueError("当前平台暂不支持修改浏览器策略。")

    def restore_webrtc_policy(self, record):
        raise ValueError("当前平台暂不支持修改浏览器策略。")

    def _scutil_output(self) -> str:
        try:
            return subprocess.check_output(
                ["scutil", "--proxy"], text=True, stderr=subprocess.DEVNULL, timeout=3,
            )
        except Exception:
            return ""

    @staticmethod
    def _parse_scutil(text: str) -> bool:
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("HTTPEnable") or s.startswith("HTTPSEnable"):
                if s.endswith(": 1") or s.endswith(":1"):
                    return True
        return False

    # ---- launch / monitor ----
    def launch(self, status: AppStatus, env: dict) -> None:
        if status.direct:
            subprocess.Popen([status.launch_target], env=env)
        else:
            subprocess.Popen(["open", "-a", status.launch_target], env=env)

    def is_running(self, status: AppStatus) -> bool:
        if not status.match_root:
            return False
        return bool(base.any_process_under(
            [status.match_root],
            ignored_names=_IGNORED_RUNNING_PROCESS_NAMES,
        ))

    def stop(self, status: AppStatus) -> None:
        if status.match_root:
            base.stop_processes_under([status.match_root])

    # ---- file dialog filter ----
    def pick_path_filter(self) -> tuple:
        return ("Application (*.app)",)

    # ---- shortcut ----
    def _shortcut_path(self, name="Claude China"):
        return os.path.normpath(os.path.expanduser(f"~/Desktop/{name}.app"))

    @staticmethod
    def _osa_quote(value):
        """Quote a string as an AppleScript double-quoted literal.

        Backslashes and double quotes are the only metacharacters inside an
        AppleScript string literal, so escaping those two is sufficient.
        """
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def create_shortcut(self) -> str:
        app_path = self._shortcut_path()
        if os.path.exists(app_path):
            return app_path
        # shlex.quote protects the interpreter path from /bin/sh word-splitting
        # (spaces are realistic in macOS install paths); _osa_quote then wraps the
        # whole command as a safe AppleScript string literal.
        inner = (f"{shlex.quote(sys.executable)} -m claude_china.cli desktop run "
                 f"> /dev/null 2>&1 &")
        script = "do shell script " + self._osa_quote(inner)
        subprocess.run(["osacompile", "-o", app_path, "-e", script], check=False)
        plist = os.path.join(app_path, "Contents", "Info.plist")
        if os.path.isfile(plist):
            with open(plist, "rb") as stream:
                info = plistlib.load(stream)
            info.update(
                CFBundleName="Claude China",
                CFBundleDisplayName="Claude China",
                CFBundleIdentifier="com.claudechina.launcher",
            )
            with open(plist, "wb") as stream:
                plistlib.dump(info, stream)
        try:
            icon = str(importlib.resources.files("claude_china.desktop")
                       .joinpath("ui", "icon.icns"))
            dest = os.path.join(app_path, "Contents", "Resources", "applet.icns")
            if os.path.exists(icon) and os.path.isdir(os.path.dirname(dest)):
                shutil.copyfile(icon, dest)
        except Exception:
            pass
        return app_path

    def remove_shortcut(self) -> list:
        removed = []
        for name in ("Claude China", "AI Launcher"):
            app_path = self._shortcut_path(name)
            if os.path.exists(app_path):
                shutil.rmtree(app_path, ignore_errors=True)
                removed.append(app_path)
        return removed
