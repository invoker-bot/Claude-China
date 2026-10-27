import logging
import os
import threading

from .apps import APP_REGISTRY, get_app
from . import config as cfg
from . import egress, privacy, router, safety
from .env import merge_env
from .proxy import SystemProxyError


class LauncherBridge:
    """pywebview js_api. Pure-Python and headless-testable.

    The GUI layer (app.py) attaches the pywebview window after creation.
    Runtime handles stay private so pywebview does not recursively expose
    native window objects as JS API members.
    """

    # Keep the window clear of the taskbar/dock when it grows to fit content.
    _SCREEN_MARGIN = 60
    _MIN_HEIGHT = 200

    def __init__(self, backend, apps=APP_REGISTRY, base_env=None):
        self._backend = backend
        self._apps = apps
        self._base_env = base_env
        self._window = None
        self._open_dialog = 20  # pywebview OPEN_DIALOG; overridden in app.py
        self._screen_height = None
        self._status = {}
        self._activity = None
        self._updater = None
        self._window_controls = None
        self._language_changed = None
        self._usage_service = None
        self._usage_lock = threading.Lock()
        self._refresh_detection()

    def _attach_window(self, window, open_dialog, screen_height=None):
        self._window = window
        self._open_dialog = open_dialog
        self._screen_height = screen_height

    # ---- detection cache ----
    def _refresh_detection(self):
        data = cfg.load_desktop_config()
        for app in self._apps:
            override = cfg.get_app_path(data, app.id)
            self._status[app.id] = self._backend.detect(app, override)

    def _running(self, app_id):
        st = self._status.get(app_id)
        if not st or not st.found:
            return False
        try:
            return bool(self._backend.is_running(st))
        except Exception:
            return False

    def _statuses(self):
        return {a.id: self._running(a.id) for a in self._apps}

    # ---- queries exposed to JS ----
    def get_update_status(self):
        return self._updater.status() if self._updater else {
            "phase": "idle", "current": "", "message": "更新服务未连接。",
            "can_install": False, "reason": "",
        }

    def check_for_updates(self):
        self._notify_activity()
        return self._updater.check() if self._updater else self.get_update_status()

    def download_update(self):
        return self._updater.fetch() if self._updater else self.get_update_status()

    def cancel_update(self):
        return self._updater.cancel() if self._updater else self.get_update_status()

    def install_update(self):
        return self._updater.install() if self._updater else self.get_update_status()

    def open_release_page(self):
        return self._updater.open_release() if self._updater else {"ok": False}

    def list_apps(self, refresh=False):
        if refresh:
            self._refresh_detection()
        return [
            {"id": a.id, "display": a.display,
             "found": self._status[a.id].found, "running": self._running(a.id)}
            for a in self._apps
        ]

    # ---- actions ----
    def _notify_activity(self):
        if self._activity is not None:
            try:
                self._activity()
            except Exception:
                logging.getLogger(__name__).debug("Icon activity failed", exc_info=True)

    def launch_app(self, app_id):
        self._notify_activity()
        data = cfg.load_desktop_config()
        settings = cfg.get_safety_settings(data)
        router_mode = settings.get("router_mode") is True
        if router_mode:
            try:
                router.check_ready(app_id, data, self._backend)
            except router.RouterError as exc:
                return {"ok": False, "error": str(exc)}
        try:
            tun_mode = egress.tun_enabled(app_id, data)
        except egress.GuardError as exc:
            return {"ok": False, "error": str(exc)}
        if not router_mode and not tun_mode and cfg.get_check_system_proxy(data) and not self._backend.proxy_enabled():
            return {"ok": False, "error": "系统代理未开启，已取消启动"}
        proxy_url = None
        if not router_mode and not tun_mode and cfg.get_auto_proxy_env(data):
            try:
                proxy_url = self._backend.system_http_proxy()
            except SystemProxyError as exc:
                return {"ok": False, "error": f"{exc} 已取消启动。"}
            except Exception:
                # System sources and third-party tools can include credentials
                # in exceptions; only show our own safe diagnostics.
                return {"ok": False, "error": "无法解析系统代理，请检查 HTTP 代理地址和端口。已取消启动。"}
        app = get_app(app_id)
        override = cfg.get_app_path(data, app_id)
        status = self._backend.detect(app, override)
        self._status[app_id] = status
        if not status.found:
            return {"ok": False, "error": "未检测到应用，请先配置路径"}
        env = merge_env(os.environ if self._base_env is None else self._base_env,
                        cfg.get_common_env(data),
                        cfg.get_app_env(data, app_id), proxy_url=proxy_url)
        if router_mode:
            env = router.direct_environment(env)
        try:
            guard = egress.ensure(app_id, self._backend, status, data=data)
            if guard["enabled"]:
                # Ignore stale per-app proxy/bypass settings under a guard.
                for key in list(env):
                    if key.lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy"):
                        env.pop(key)
                if guard.get("mode") != "tun":
                    env = merge_env(env, {}, {}, proxy_url=self._backend.system_http_proxy())
        except egress.GuardError as exc:
            return {"ok": False, "error": str(exc) + " 已取消启动。"}
        except Exception:
            return {"ok": False, "error": "无法验证系统网络防护，已取消启动。"}
        report = None
        if settings["enabled"] or router_mode:
            report = self._check_safety(app_id, env, status, settings)
            if not report["allowed"]:
                return {"ok": False, "error": "安全检查未通过：" + report.get("reason", "无法确认支持状态。") + " 已取消启动。",
                        "safety": report}
            if cfg.launch_settings_changed(data, cfg.load_desktop_config()):
                return {"ok": False, "error": "检测期间启动设置发生变化，已取消启动，请重试。"}
            if router_mode:
                try:
                    router.check_ready(app_id, data, self._backend)
                except router.RouterError as exc:
                    return {"ok": False, "error": str(exc)}
        try:
            self._backend.stop(status)
        except Exception as exc:
            return {"ok": False, "error": f"中止失败: {exc}"}
        try:
            self._backend.launch(status, env)
        except Exception as exc:
            return {"ok": False, "error": f"启动失败: {exc}"}
        return {"ok": True, "safety": report} if report else {"ok": True}

    def stop_app(self, app_id):
        self._notify_activity()
        status = self._status.get(app_id)
        if not status or not status.found:
            return {"ok": False, "error": "未检测到应用"}
        try:
            self._backend.stop(status)
        except Exception as exc:
            return {"ok": False, "error": f"中止失败: {exc}"}
        return {"ok": True}

    # ---- settings ----
    def get_locale(self):
        from .localization import locale_data
        return locale_data(cfg.get_language(cfg.load_desktop_config()))

    def set_language(self, language):
        from .localization import LANGUAGES
        if not isinstance(language, str) or language not in LANGUAGES:
            return {"ok": False, "error": "不支持此界面语言。"}
        try:
            with cfg.CONFIG_LOCK:
                data = cfg.load_desktop_config()
                data["language"] = language
                cfg.save_desktop_config(data)
        except (OSError, ValueError):
            return {"ok": False, "error": "无法保存语言设置，请重试。"}
        if self._language_changed:
            try:
                self._language_changed()
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh native language labels")
        return {"ok": True, "data": self.get_locale()}

    def _terminal_request(self, action, **values):
        from .terminals import TerminalService
        try:
            result = action(TerminalService(self._backend))
            return {'ok': True, **values, 'data': result}
        except ValueError as exc:
            return {'ok': False, 'error': str(exc)}
        except Exception:
            # Do not expose YAML contents or subprocess output containing keys.
            return {'ok': False, 'error': '无法完成终端操作，请检查 CLI 配置或安装后重试。'}

    def list_cli_profiles(self):
        return self._terminal_request(lambda service: {**service.workspace(), 'profiles': service.list_profiles()})

    def get_cli_profile(self, name):
        return self._terminal_request(lambda service: service.get_profile(name))

    def save_cli_profile(self, payload, original_name=None, revision=None):
        return self._terminal_request(lambda service: service.save_profile(payload, original_name, revision))

    def copy_cli_profile(self, name, revision):
        return self._terminal_request(lambda service: service.copy_profile(name, revision))

    def delete_cli_profile(self, name, revision):
        return self._terminal_request(lambda service: service.delete_profile(name, revision))

    def open_terminal(self, profile_name=None, directory=''):
        return self._terminal_request(lambda service: service.launch(profile_name, directory))

    def list_cli_history(self, profile_name):
        return self._terminal_request(lambda service: service.history(profile_name))

    def _usage(self):
        from .usage import UsageService
        with self._usage_lock:
            if self._usage_service is None:
                self._usage_service = UsageService()
            return self._usage_service

    def start_usage_scan(self):
        try:
            return {'ok': True, 'data': self._usage().start()}
        except Exception:
            return {'ok': False, 'error': '无法读取统计索引，请检查本机文件权限。'}

    def get_usage_report(self, days=30, tool='all', project='', model='all'):
        try:
            return {'ok': True, 'data': self._usage().report(days, tool, project, model)}
        except ValueError:
            return {'ok': False, 'error': '无效的统计筛选条件。'}
        except Exception:
            return {'ok': False, 'error': '无法读取统计索引，请检查本机文件权限。'}

    def open_usage_price_source(self, model):
        import webbrowser
        from .usage_pricing import lookup_price
        if not isinstance(model, str):
            return {'ok': False}
        price = lookup_price(model)
        return {'ok': bool(price and webbrowser.open(price['source']))}

    def resume_cli_session(self, profile_name, session_id):
        return self._terminal_request(lambda service: service.resume_session(profile_name, session_id))

    def set_terminal_favorite(self, directory, favorite):
        return self._terminal_request(lambda service: service.set_favorite(directory, favorite))

    def open_project_folder(self, directory):
        from .terminal_host import open_directory
        return self._terminal_request(lambda service: open_directory(directory))

    def pick_terminal_directory(self):
        if self._window is None:
            return {'ok': False, 'cancelled': True}
        try:
            import webview
            selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            return {'ok': True, 'path': selected[0]} if selected else {'ok': False, 'cancelled': True}
        except Exception:
            return {'ok': False, 'error': '无法打开文件夹选择窗口。'}

    def get_takeover_status(self, app_id='grok-bot'):
        from .takeover import get_status
        from .platforms.base import AppStatus
        try:
            app = get_app(app_id)
            data = cfg.load_desktop_config()
            status = self._backend.detect(app, cfg.get_app_path(data, app_id))
        except (KeyError, TypeError, ValueError, OSError):
            status = AppStatus(app_id)
        try:
            return get_status(app_id, status)
        except (KeyError, TypeError, ValueError, OSError):
            return {'app_id': app_id, 'supported': False, 'enabled': False,
                    'can_disable': False, 'message': '无法读取此应用的接管状态。'}

    def set_grok_takeover(self, enabled):
        # Preserve the API used by an already open UI from the previous release.
        return self.set_takeover('grok-bot', enabled)

    def set_takeover(self, app_id, enabled):
        from .takeover import set_enabled
        from .platforms.base import AppStatus
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "无效的接管设置。"}
        try:
            app = get_app(app_id)
        except (KeyError, TypeError):
            return {"ok": False, "error": "未知的接管应用。"}
        try:
            status = AppStatus(app_id)
            if enabled:
                data = cfg.load_desktop_config()
                status = self._backend.detect(app, cfg.get_app_path(data, app_id))
            return {"ok": True, "state": set_enabled(app_id, enabled, status)}
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def get_safety_settings(self):
        return {**cfg.get_safety_settings(cfg.load_desktop_config()),
                "policy": safety.region_policy(),
                "environment": safety.local_environment()}

    def open_safety_source(self, app_id):
        import webbrowser

        source = safety.SOURCES.get(app_id)
        return {"ok": bool(source and webbrowser.open(source))}

    def save_safety_settings(self, payload):
        self._notify_activity()
        with cfg.CONFIG_LOCK:
            data = cfg.load_desktop_config()
            cfg.set_safety_settings(data, payload)
            cfg.save_desktop_config(data)
        return {"ok": True}

    def _check_safety(self, app_id, env, status, settings):
        try:
            if settings.get("router_mode"):
                router.check_ready(app_id, cfg.load_desktop_config(), self._backend)
                report = router.inspect(app_id, self._backend)
            else:
                report = safety.inspect_environment(app_id, env, self._backend, status)
        except router.RouterError as exc:
            report = {"app_id": app_id, "status": "unsupported", "reason": str(exc)}
        except Exception:
            report = {"app_id": app_id, "status": "unknown", "reason": "环境检查失败，无法确认支持状态。"}
        report["allowed"] = safety.launch_allowed(report, settings)
        return report

    def check_safety(self, app_id):
        self._notify_activity()
        app = get_app(app_id)
        data = cfg.load_desktop_config()
        status = self._backend.detect(app, cfg.get_app_path(data, app_id))
        proxy_url = None
        if not cfg.get_safety_settings(data).get("router_mode") and cfg.get_auto_proxy_env(data):
            try:
                proxy_url = self._backend.system_http_proxy()
            except Exception:
                return {"app_id": app_id, "status": "unknown", "allowed": False,
                        "environment": safety.local_environment(),
                        "reason": "无法解析系统 HTTP 代理，自动添加代理环境变量将阻止启动。"}
        env = merge_env(os.environ, cfg.get_common_env(data), cfg.get_app_env(data, app_id), proxy_url=proxy_url)
        return self._check_safety(app_id, env, status, cfg.get_safety_settings(data))

    # ---- browser WebRTC privacy ----
    def _guard_detect(self, app_id, data):
        if app_id == "playwright":
            from .platforms.base import AppStatus
            return AppStatus(app_id, found=True)
        return self._backend.detect(get_app(app_id), cfg.get_app_path(data, app_id))

    def get_network_guard(self, app_id):
        try:
            data = cfg.load_desktop_config()
            detected = self._guard_detect(app_id, data)
            return {"ok": True, "state": egress.status(app_id, self._backend, detected)}
        except Exception:
            return {"ok": False, "error": "无法读取系统网络防护状态。"}

    def apply_network_guard(self, app_id, options=None):
        self._notify_activity()
        try:
            data = cfg.load_desktop_config()
            detected = self._guard_detect(app_id, data)
            state = egress.apply(app_id, self._backend, detected, options)
            return {"ok": True, "state": state}
        except egress.GuardError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "无法应用系统网络防护。"}

    def restore_network_guard(self, app_id):
        self._notify_activity()
        try:
            egress.restore(app_id)
            return self.get_network_guard(app_id)
        except egress.GuardError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "无法还原系统网络防护。"}

    def check_privacy(self):
        self._notify_activity()
        try:
            report = privacy.inspect(self._backend,
                                     self._base_env if self._base_env is not None else os.environ)
        except Exception:
            report = privacy.unknown_report("检查失败，请重试。")
        try:
            repairs = privacy.list_repairs()
        except privacy.PrivacyError as exc:
            return {"ok": True, "report": report, "repairs": [], "warning": str(exc)}
        except Exception:
            repairs = []
        return {"ok": True, "report": report, "repairs": repairs}

    def apply_privacy_fix(self, browser):
        self._notify_activity()
        try:
            result = privacy.apply(self._backend, browser,
                                   self._base_env if self._base_env is not None else os.environ)
        except privacy.PrivacyError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "无法应用浏览器策略，请检查权限后重试。"}
        try:
            repairs = privacy.list_repairs()
        except Exception:
            repairs = []
        return {"ok": True, "result": result, "repairs": repairs}

    def restore_privacy_fix(self, browser):
        self._notify_activity()
        try:
            result = privacy.restore(self._backend, browser)
        except privacy.PrivacyError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "还原失败，请重试。"}
        try:
            repairs = privacy.list_repairs()
        except Exception:
            repairs = []
        return {"ok": True, "result": result, "repairs": repairs}

    def get_privacy_repairs(self):
        try:
            return {"ok": True, "repairs": privacy.list_repairs()}
        except privacy.PrivacyError as exc:
            return {"ok": False, "error": str(exc)}

    def get_settings(self):
        data = cfg.load_desktop_config()
        return {"check_system_proxy": cfg.get_check_system_proxy(data),
                "auto_proxy_env": cfg.get_auto_proxy_env(data),
                "env_vars": cfg.get_common_env(data)}

    def save_settings(self, payload):
        self._notify_activity()
        with cfg.CONFIG_LOCK:
            data = cfg.load_desktop_config()
            cfg.set_check_system_proxy(data, bool(payload.get("check_system_proxy", True)))
            cfg.set_auto_proxy_env(data, payload.get("auto_proxy_env", cfg.get_auto_proxy_env(data)))
            cfg.set_common_env(data, dict(payload.get("env_vars", {})))
            cfg.save_desktop_config(data)
        return {"ok": True}

    def get_app_settings(self, app_id):
        data = cfg.load_desktop_config()
        return {"env_vars": cfg.get_app_env(data, app_id),
                "path": cfg.get_app_path(data, app_id) or ""}

    def save_app_settings(self, app_id, payload):
        self._notify_activity()
        with cfg.CONFIG_LOCK:
            data = cfg.load_desktop_config()
            cfg.set_app_env(data, app_id, dict(payload.get("env_vars", {})))
            if "path" in payload:
                cfg.set_app_path(data, app_id, payload["path"] or "")
            cfg.save_desktop_config(data)
        if "path" in payload:
            self._refresh_detection()
        return {"ok": True}

    # ---- window ----
    def get_window_state(self):
        return self._window_controls.state() if self._window_controls else {
            "custom_titlebar": False, "maximized": False,
        }

    def window_action(self, action):
        return self._window_controls.action(action) if self._window_controls else {"ok": False}

    def begin_window_resize(self, edge):
        return self._window_controls.resize(edge) if self._window_controls else {"ok": False}

    def move_window(self, dx, dy, start=False):
        return self._window_controls.move(dx, dy, start) if self._window_controls else {"ok": False}

    def fit_window(self, payload):
        """Resize the window so the page content fits without scrolling.

        The page reports its current viewport height (`inner`) and the height
        its content wants (`wanted`), both in CSS px; the same delta is applied
        to the outer window so the title bar / borders stay out of the maths.
        Growth is clamped to the screen and the window is nudged up when it
        would otherwise run under the taskbar.
        """
        if self._window is None:
            return {"ok": False}
        try:
            inner = int(payload.get("inner", 0))
            wanted = int(payload.get("wanted", 0))
        except (AttributeError, TypeError, ValueError):
            return {"ok": False}
        if inner <= 0 or wanted <= 0:
            return {"ok": False}
        try:
            width, height = self._window.width, self._window.height
            new_height = height + (wanted - inner)
            limit = None
            if self._screen_height:
                limit = int(self._screen_height) - self._SCREEN_MARGIN
                new_height = min(new_height, limit)
            new_height = max(self._MIN_HEIGHT, new_height)
            if abs(new_height - height) <= 1:
                return {"ok": True, "height": height}
            if limit is not None:
                x, y = self._window.x, self._window.y
                if y + new_height > limit:
                    self._window.move(x, max(0, limit - new_height))
            self._window.resize(width, new_height)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "height": new_height}

    def pick_app_path(self, app_id, persist=True):
        self._notify_activity()
        if self._window is None:
            return {"ok": False}
        file_types = self._backend.pick_path_filter()
        result = self._window.create_file_dialog(self._open_dialog, file_types=file_types)
        if not result:
            return {"ok": False}
        path = result[0]
        if persist:
            with cfg.CONFIG_LOCK:
                data = cfg.load_desktop_config()
                cfg.set_app_path(data, app_id, path)
                cfg.save_desktop_config(data)
            self._refresh_detection()
        return {"ok": True, "path": path}
