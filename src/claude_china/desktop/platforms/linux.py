"""Find known desktop executables and launch explicitly configured ones."""

import os
from pathlib import Path
import shutil

from . import base
from .base import AppStatus
from .. import process as subprocess


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

    def pick_path_filter(self) -> tuple:
        return ("Executable files (*)",)
