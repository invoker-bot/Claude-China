"""Find known desktop executables and launch explicitly configured ones."""

import ast
import os
from pathlib import Path
import shutil
from subprocess import CalledProcessError

from . import base
from .base import AppStatus
from .. import process as subprocess
from ..proxy import SystemProxyError, http_proxy_address, http_proxy_url


class LinuxBackend:
    def detect(self, app, override_path=None) -> AppStatus:
        # Names in linux_commands identify desktop packages, not terminal CLIs.
        candidates = ([override_path] if override_path else
                      [shutil.which(command) for command in app.linux_commands])
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser().resolve()
            if path.is_file() and os.access(str(path), os.X_OK):
                return AppStatus(app.id, found=True, direct=True,
                                 launch_target=str(path), match_root=str(path))
        return AppStatus(app.id)

    def launch(self, status: AppStatus, env: dict) -> None:
        subprocess.Popen([status.launch_target], env=env, start_new_session=True)

    def is_running(self, status: AppStatus) -> bool:
        return bool(status.match_root and base.any_process_under([status.match_root]))

    def stop(self, status: AppStatus) -> None:
        if status.match_root:
            base.stop_processes_under([status.match_root])

    def proxy_enabled(self) -> bool:
        if any(os.environ.get(key) for key in (
            "http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        )):
            return True
        try:
            mode = subprocess.check_output(
                ["gsettings", "get", "org.gnome.system.proxy", "mode"],
                text=True, stderr=subprocess.DEVNULL, timeout=3,
            )
            return mode.strip().strip("'\"") in ("manual", "auto")
        except (OSError, subprocess.SubprocessError):
            return False

    def system_http_proxy(self) -> str:
        # Match conventional Unix HTTP proxy precedence. An invalid explicit
        # value must not silently fall through to another configuration source.
        for key in ("http_proxy", "HTTP_PROXY"):
            if key in os.environ:
                return http_proxy_url(os.environ[key])
        try:
            mode = ast.literal_eval(self._proxy_setting("mode"))
            if mode != "manual":
                raise SystemProxyError("系统未配置静态 HTTP 代理；PAC 自动配置不受支持。")
            if self._proxy_setting("use-authentication", "http") != "false":
                raise SystemProxyError("系统 HTTP 代理要求认证，请关闭自动添加并手动配置代理环境变量。")
            host = ast.literal_eval(self._proxy_setting("host", "http"))
            port = self._proxy_setting("port", "http")
            return http_proxy_address(host, port)
        except SystemProxyError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, SyntaxError):
            raise SystemProxyError("无法读取系统 HTTP 代理；请配置 http_proxy 或 GNOME 手动代理。") from None

    @staticmethod
    def _proxy_setting(key, protocol=""):
        schema = "org.gnome.system.proxy" + ("." + protocol if protocol else "")
        return subprocess.check_output(
            ["gsettings", "get", schema, key], text=True,
            stderr=subprocess.DEVNULL, timeout=3,
        ).strip()

    def safety_proxy(self):
        # Environment variables are resolved separately from the GNOME settings.
        try:
            mode = ast.literal_eval(self._proxy_setting("mode"))
        except (FileNotFoundError, CalledProcessError):
            return {"proxy": None}  # No GNOME proxy schema on this desktop.
        if mode == "none":
            return {"proxy": None}
        if mode != "manual":
            raise SystemProxyError("自动代理无法确认单一出口。")
        same = self._proxy_setting("use-same-proxy") == "true"
        protocol = "http" if same else "https"
        if same and self._proxy_setting("use-authentication", "http") != "false":
            raise SystemProxyError("无法读取系统代理认证信息。")
        host = ast.literal_eval(self._proxy_setting("host", protocol))
        proxy = http_proxy_address(host, self._proxy_setting("port", protocol)) if host else None
        bypass = ast.literal_eval(self._proxy_setting("ignore-hosts"))
        return {"proxy": proxy, "bypass": ",".join(bypass)}

    def pick_path_filter(self) -> tuple:
        return ("Executable files (*)",)
