import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from . import base
from .. import process as subprocess
from ..proxy import SystemProxyError, http_proxy_url
from .windows_shell import launcher_icon_path, set_shortcut_app_id
from .base import AppStatus

try:
    import winreg  # Windows-only; absent on macOS/Linux.
except ImportError:  # pragma: no cover - non-Windows import path
    winreg = None


# CREATE_NO_WINDOW suppresses the console-window flash that console child
# processes (PowerShell, etc.) would otherwise show when the launcher runs
# under pythonw.exe. getattr keeps this importable on non-Windows, where the
# flag is absent (value 0 = no-op).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_IGNORED_PROCESS_NAMES = {
    # Claude keeps this service alive under the package install directory even
    # when the desktop window is closed. It is not a GUI-app running signal.
    "claude": ("cowork-svc.exe",),
}

_DESKTOP_PYTHON_ENV = "CLAUDEC_DESKTOP_PYTHON"

_WEBRTC_POLICY_NAME = "WebRtcIPHandlingPolicy"
_WEBRTC_POLICY_VALUE = "disable_non_proxied_udp"
_WEBRTC_POLICY_PATHS = {
    "chrome": r"Software\Policies\Google\Chrome",
    "edge": r"Software\Policies\Microsoft\Edge",
}
_TUN_MARKERS = re.compile(
    r"(?:^|[^a-z])(?:tun|tap|wireguard|wintun|clash|mihomo|sing-box|tailscale|openvpn|vpn)(?:[^a-z]|$)"
)
_VIRTUAL_SWITCH_MARKERS = ("hyper-v", "vmware", "virtualbox", "loopback")


def _policy_state(value):
    if value is None:
        return "unset"
    return {
        "disable_non_proxied_udp": "disabled",
        "default_public_interface_only": "public_only",
        "default_public_and_private_interfaces": "exposed",
        "default": "default",
    }.get(value, "custom")


class WindowsBackend:
    def network_guard_targets(self, status):
        """Enumerate this installation's EXEs, including bundled network helpers.

        Shared runtimes outside this root are not silently claimed as covered.
        Symlinks/junctions cannot widen the protected directory to another app.
        """
        root = Path(status.match_root).resolve(strict=True)
        if root.is_file():
            root = root.parent
        if not root.is_dir() or len(root.parts) < 3:
            raise ValueError("无法确定应用安装目录。")
        if root.name.casefold() in {"windows", "system32", "syswow64", "program files",
                                   "program files (x86)", "programs", "bin", "desktop"}:
            raise ValueError("请选择独立的应用安装目录，无法保护共享运行时目录。")
        targets = []
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = [name for name in folders if not Path(directory, name).is_symlink()
                          and not getattr(os.path, "isjunction", lambda _: False)(str(Path(directory, name)))]
            for name in files:
                path = Path(directory, name)
                if name.lower().endswith(".exe") and not path.is_symlink():
                    targets.append(str(path.resolve(strict=True)))
                    if len(targets) > 128:
                        raise ValueError("应用目录包含过多程序，请选择独立的应用安装目录。")
        if not targets:
            raise ValueError("应用安装目录中未找到可保护的 EXE。")
        return sorted(set(targets), key=str.casefold)

    # ---- detection ----
    def detect(self, app, override_path=None) -> AppStatus:
        if override_path and os.path.exists(override_path):
            return AppStatus(app.id, found=True, direct=True,
                             launch_target=override_path, match_root=override_path)
        if app.win_executable:
            executable = self._find_executable(app)
            if executable:
                return AppStatus(app.id, found=True, direct=True,
                                 launch_target=executable, match_root=executable)
        if not app.win_package_family or not app.win_aumid:
            return AppStatus(app.id, found=False)
        family = app.win_package_family.lower()
        for pkg in self._query_packages():
            if str(pkg.get("PackageFamilyName", "")).lower() == family:
                loc = pkg.get("InstallLocation") or ""
                return AppStatus(app.id, found=True, direct=False,
                                 launch_target=app.win_aumid, match_root=loc)
        return AppStatus(app.id, found=False)

    def _find_executable(self, app) -> str:
        """Find a conventional installer without treating its CLI as the app."""
        if winreg is not None and app.win_uninstall_key:
            for root, prefix in (
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            ):
                try:
                    key = winreg.OpenKey(root, prefix + "\\" + app.win_uninstall_key)
                except OSError:
                    continue
                try:
                    for field in ("InstallLocation", "DisplayIcon"):
                        try:
                            value, _ = winreg.QueryValueEx(key, field)
                        except OSError:
                            continue
                        if not isinstance(value, str) or not value.strip():
                            continue
                        value = os.path.expandvars(value.strip())
                        if field == "InstallLocation":
                            candidate = os.path.join(value.strip('"'), app.win_executable)
                        else:
                            # A DisplayIcon may be quoted and end with an icon
                            # index. Commas inside the actual path are valid.
                            filename, separator, index = value.rpartition(",")
                            if separator and index.strip().lstrip("-").isdigit():
                                value = filename
                            candidate = value.strip().strip('"')
                        if (os.path.normcase(os.path.basename(candidate))
                                == os.path.normcase(app.win_executable)
                                and os.path.isfile(candidate)):
                            return os.path.abspath(candidate)
                finally:
                    winreg.CloseKey(key)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidate = os.path.join(local, "Programs", app.display, app.win_executable)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return ""

    def _query_packages(self):
        ps = ("Get-AppxPackage | Select-Object Name,PackageFamilyName,"
              "InstallLocation | ConvertTo-Json -Compress")
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps],
                text=True, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
            )
            data = json.loads(out)
        except Exception:
            return []
        if isinstance(data, dict):
            data = [data]
        return data if isinstance(data, list) else []

    # ---- proxy ----
    def system_http_proxy(self) -> str:
        if winreg is None:
            raise SystemProxyError("无法读取 Windows 系统代理设置。")
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if enabled != 1:
                    raise SystemProxyError("系统 HTTP 代理未开启；仅有 PAC 自动配置不能生成代理环境变量。")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            finally:
                winreg.CloseKey(key)
        except OSError:
            raise SystemProxyError("无法读取系统 HTTP 代理，请检查系统代理设置。") from None
        return self._http_proxy_server(server)

    @staticmethod
    def _http_proxy_server(server, protocol="http"):
        if not isinstance(server, str) or any(ord(c) < 32 for c in server):
            raise SystemProxyError("系统代理地址格式无效。")
        proxies = {}
        wanted = protocol
        for entry in re.split(r"[; ]+", server.strip(" ;")):
            match = re.fullmatch(r"([a-zA-Z]+)=(.+)", entry)
            protocol, value = (match.group(1).lower(), match.group(2)) if match else ("default", entry)
            if protocol in proxies or protocol not in ("default", "http", "https", "ftp", "socks"):
                raise SystemProxyError("系统代理列表格式无效或包含重复协议。")
            # Validate structure even for protocols we do not select.
            if not value or ("=" in entry and not match and "://" not in entry):
                raise SystemProxyError("系统代理列表格式无效。")
            proxies[protocol] = value
        selected = proxies.get(wanted, proxies.get("default"))
        if selected is None:
            raise SystemProxyError("系统代理未配置 HTTP 端口，无法自动添加代理环境变量。")
        return http_proxy_url(selected)

    def safety_proxy(self):
        """HTTPS route for the regional probe, including proxy exclusions."""
        if winreg is None:
            raise SystemProxyError("无法读取 Windows 系统代理。")
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            def value(name, default=""):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return default
            if value("AutoConfigURL") or value("AutoDetect", 0):
                raise SystemProxyError("自动代理无法确认单一出口。")
            if value("ProxyEnable", 0) != 1:
                return {"proxy": None}
            return {"proxy": self._http_proxy_server(value("ProxyServer"), "https"),
                    "bypass": value("ProxyOverride")}
        finally:
            winreg.CloseKey(key)

    def proxy_enabled(self) -> bool:
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "ProxyEnable")
            finally:
                winreg.CloseKey(key)
            return int(value) == 1
        except Exception:
            return False

    # ---- browser WebRTC policy / routing ----
    def privacy_snapshot(self):
        if winreg is None:
            return {"supported": False, "tun": None,
                    "ipv6": {"default": None, "tunnel": None}, "policies": {}}
        route = self._default_route("0.0.0.0/0")
        ipv6_route = self._default_route("::/0")
        route_known = bool(route and (route.get("Name") or route.get("Description")))
        ipv6_known = bool(ipv6_route and (ipv6_route.get("Name") or ipv6_route.get("Description")))
        return {
            "supported": True,
            "tun": self._is_tunnel(route) if route_known else None,
            "ipv6": {
                "default": True if ipv6_known else None,
                "tunnel": self._is_tunnel(ipv6_route) if ipv6_known else None,
            },
            "policies": {browser: self._read_policy_state(browser)
                         for browser in _WEBRTC_POLICY_PATHS},
        }

    def _default_route(self, prefix):
        """Return the lowest-metric default route's adapter, or None."""
        script = (
            "$r = Get-NetRoute -DestinationPrefix '" + prefix + "' -ErrorAction SilentlyContinue | "
            "Sort-Object RouteMetric | Select-Object -First 1; "
            "if ($r) { $a = Get-NetAdapter -InterfaceIndex $r.ifIndex -ErrorAction SilentlyContinue; "
            "[pscustomobject]@{Name=$a.Name; Description=$a.InterfaceDescription} | "
            "ConvertTo-Json -Compress }"
        )
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", script],
                text=True, stderr=subprocess.DEVNULL, timeout=4,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            return None
        if not output.strip():
            return None
        try:
            value = json.loads(output)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _is_tunnel(route):
        text = f"{route.get('Name', '')} {route.get('Description', '')}".lower()
        if any(marker in text for marker in _VIRTUAL_SWITCH_MARKERS):
            return False
        return bool(_TUN_MARKERS.search(text))

    def _policy_key_exists(self, browser):
        path = _WEBRTC_POLICY_PATHS[browser]
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        try:
            return True
        finally:
            winreg.CloseKey(key)

    def _read_policy_value(self, root, path):
        if winreg is None:
            return None
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            return None
        try:
            try:
                value, _kind = winreg.QueryValueEx(key, _WEBRTC_POLICY_NAME)
            except OSError:
                return None
            return value if isinstance(value, str) and value else None
        finally:
            winreg.CloseKey(key)

    def _read_policy_state(self, browser):
        if winreg is None:
            return {"value": None, "source": None, "state": "unknown", "editable": False}
        path = _WEBRTC_POLICY_PATHS[browser]
        machine = self._read_policy_value(winreg.HKEY_LOCAL_MACHINE, path)
        user = self._read_policy_value(winreg.HKEY_CURRENT_USER, path)
        if machine is not None:
            value, source = machine, "machine"
        elif user is not None:
            value, source = user, "user"
        else:
            value, source = None, None
        return {"value": value, "source": source,
                "state": _policy_state(value), "editable": source != "machine"}

    def apply_webrtc_policy(self, browser, value):
        if winreg is None:
            raise ValueError("当前平台暂不支持修改浏览器策略。")
        path = _WEBRTC_POLICY_PATHS.get(browser)
        if path is None:
            raise ValueError("不支持的浏览器。")
        state = self._read_policy_state(browser)
        if state["source"] == "machine":
            if state["value"] == value:
                raise ValueError("浏览器策略已由组织限制，无需修改。")
            raise ValueError("浏览器策略由组织管理，无法在此修改。")
        if state["value"] == value:
            return {"applied": False, "already": True, "created_key": False,
                    "previous": {"exists": True, "value": state["value"]}}
        if state["value"] is not None:
            raise ValueError("已存在其他 WebRTC 策略，请先手动检查。")

        created = not self._policy_key_exists(browser)
        key = None
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            winreg.SetValueEx(key, _WEBRTC_POLICY_NAME, 0, winreg.REG_SZ, value)
        except OSError:
            if key is not None:
                try:
                    winreg.CloseKey(key)
                except OSError:
                    pass
                key = None
            if created:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
                except OSError:
                    pass
            raise ValueError("无法写入浏览器策略，请检查权限后重试。") from None
        finally:
            if key is not None:
                winreg.CloseKey(key)
        return {"applied": True, "already": False, "created_key": created,
                "previous": {"exists": False, "value": None}}

    def restore_webrtc_policy(self, record):
        if winreg is None:
            raise ValueError("当前平台暂不支持修改浏览器策略。")
        browser = record.get("browser")
        path = _WEBRTC_POLICY_PATHS.get(browser)
        if path is None:
            raise ValueError("不支持的浏览器。")
        state = self._read_policy_state(browser)
        if state["source"] == "machine":
            return {"restored": False, "conflict": True, "current": state["value"]}
        if state["value"] != record.get("value"):
            return {"restored": False, "conflict": True, "current": state["value"]}

        previous = record.get("previous") or {}
        key = None
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            if previous.get("exists") and isinstance(previous.get("value"), str):
                winreg.SetValueEx(key, _WEBRTC_POLICY_NAME, 0, winreg.REG_SZ, previous["value"])
            else:
                try:
                    winreg.DeleteValue(key, _WEBRTC_POLICY_NAME)
                except FileNotFoundError:
                    pass
        except OSError:
            raise ValueError("无法还原浏览器策略，请检查权限后重试。") from None
        finally:
            if key is not None:
                winreg.CloseKey(key)

        if not previous.get("exists") and record.get("created_key"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass
        return {"restored": True, "conflict": False}

    # ---- launch / monitor ----
    @staticmethod
    def _safe_parse_xml(path):
        """Parse XML with any DTD refused (defense-in-depth).

        AppxManifest.xml is an OS-trusted, signed, admin-only file that never
        contains a DTD. A DTD is the prerequisite for XXE and entity-expansion
        ("billion laughs") attacks, so rejecting one (raising ValueError, which
        the caller turns into a broker fallback) defangs both classes without a
        defusedxml dependency. ElementTree never resolves external entities, so
        no DTD means no reachable attack surface.
        """
        with open(path, "rb") as fh:
            data = fh.read()
        if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            raise ValueError("DTD/DOCTYPE not allowed in manifest")
        return ET.ElementTree(ET.fromstring(data))

    def _resolve_exe(self, status: AppStatus):
        """Resolve a brokered MSIX app's real executable from its manifest.

        Returns the absolute exe path, or None when it can't be resolved (no
        install dir, unreadable manifest, missing binary) so the caller can
        fall back to the OS broker. The Application is matched by the AUMID's
        app id (the part after '!'); its <Application Executable="..."> value
        is joined onto the package InstallLocation (status.match_root).
        """
        root = status.match_root
        if not root or not os.path.isdir(root):
            return None
        manifest = os.path.join(root, "AppxManifest.xml")
        if not os.path.isfile(manifest):
            return None
        want_id = (status.launch_target.split("!", 1)[1]
                   if "!" in status.launch_target else "")
        try:
            tree = self._safe_parse_xml(manifest)
        except (ET.ParseError, OSError, ValueError):
            return None
        # Namespace-agnostic: the manifest's default xmlns prefixes every tag.
        apps = [e for e in tree.iter() if e.tag.rsplit("}", 1)[-1] == "Application"]
        chosen = next((e for e in apps if e.get("Id") == want_id), None)
        if chosen is None and apps:
            chosen = apps[0]
        if chosen is None:
            return None
        executable = chosen.get("Executable")
        if not executable:
            return None
        exe = os.path.join(root, *executable.replace("\\", "/").split("/"))
        return exe if os.path.isfile(exe) else None

    def launch(self, status: AppStatus, env: dict) -> None:
        if status.direct:
            subprocess.Popen([status.launch_target], env=env,
                             creationflags=_NO_WINDOW)
            return
        if status.app_id == "codex":
            # Codex's Windows app starts its own sandbox helpers from the MSIX
            # package. Launching through the OS broker preserves package
            # activation context and avoids direct WindowsApps process quirks.
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{status.launch_target}"],
                env=env, creationflags=_NO_WINDOW,
            )
            return
        # Brokered MSIX: launch the real binary directly when resolvable, so the
        # injected env actually reaches the app. Shell activation (explorer
        # shell:AppsFolder) runs it under an OS broker that strips our custom
        # environment. Fall back to the broker only if resolution/launch fails.
        exe = self._resolve_exe(status)
        if exe:
            try:
                subprocess.Popen([exe], env=env, creationflags=_NO_WINDOW)
                return
            except OSError:
                pass
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{status.launch_target}"],
            env=env, creationflags=_NO_WINDOW,
        )

    def is_running(self, status: AppStatus) -> bool:
        if not status.match_root:
            return False
        return bool(base.any_process_under(
            [status.match_root],
            ignored_names=_IGNORED_PROCESS_NAMES.get(status.app_id),
        ))

    def stop(self, status: AppStatus) -> None:
        if status.match_root:
            base.stop_processes_under(
                [status.match_root],
                ignored_names=_IGNORED_PROCESS_NAMES.get(status.app_id),
            )

    # ---- file dialog filter ----
    def pick_path_filter(self) -> tuple:
        return ("Executable (*.exe)",)

    # ---- shortcut ----
    def _shortcut_paths(self, name="Claude China"):
        paths = [os.path.join(os.path.expanduser("~"), "Desktop", f"{name}.lnk")]
        appdata = os.environ.get("APPDATA")
        if appdata:
            paths.append(os.path.join(
                appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                f"{name}.lnk",
            ))
        return paths

    def _icon_path(self):
        try:
            return launcher_icon_path()
        except OSError:
            return ""

    @staticmethod
    def _shortcut_python():
        override = os.environ.get(_DESKTOP_PYTHON_ENV) or os.environ.get("CODE_AI_DESKTOP_PYTHON")
        if override:
            candidate = os.path.expandvars(os.path.expanduser(override.strip('"')))
            if os.path.basename(candidate).lower() == "python.exe":
                pythonw = os.path.join(os.path.dirname(candidate), "pythonw.exe")
                if os.path.exists(pythonw):
                    return pythonw
            if os.path.exists(candidate):
                return candidate
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        return pythonw

    def create_shortcut(self) -> str:
        pythonw = self._shortcut_python()
        icon = self._icon_path()
        paths = self._shortcut_paths()
        # Idempotent: if any shortcut already exists, do nothing (no shell-out).
        for path in paths:
            if os.path.exists(path):
                return path
        created = []
        for path in paths:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._write_lnk(path, pythonw, "-m claude_china.cli desktop run", icon)
            created.append(path)
        return created[0] if created else ""

    @staticmethod
    def _ps_quote(value):
        """Quote a string as a PowerShell single-quoted literal.

        Single quotes prevent $-expansion and backtick escapes; embedded
        single quotes are doubled per PowerShell literal-string rules.
        """
        return "'" + str(value).replace("'", "''") + "'"

    def _write_lnk(self, path, target, args, icon):
        icon_line = (
            f"$s.IconLocation = {self._ps_quote(icon)}\n"
            if os.path.exists(icon) else ""
        )
        script = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({self._ps_quote(path)})\n"
            f"$s.TargetPath = {self._ps_quote(target)}\n"
            f"$s.Arguments = {self._ps_quote(args)}\n"
            f"{icon_line}"
            "$s.Save()\n"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       check=False, creationflags=_NO_WINDOW)
        if os.path.isfile(path):
            # The same ID on the process and .lnk preserves taskbar grouping
            # and makes pinning/relaunching use the launcher command and icon.
            set_shortcut_app_id(path)

    def remove_shortcut(self) -> list:
        removed = []
        paths = self._shortcut_paths() + self._shortcut_paths("AI Launcher")
        for path in paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError:
                    pass
        return removed
