"""Per-user launcher ownership and local window activation."""

import errno
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

from . import config as cfg


def _try_lock(stream) -> bool:
    stream.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise
    return True


def _allow_foreground(pid: int) -> None:
    if sys.platform == "win32":
        import ctypes

        # Pass the new launch's foreground permission to the existing process.
        # A denied request is harmless; the window can still be restored/shown.
        ctypes.windll.user32.AllowSetForegroundWindow(pid)


class DesktopInstance:
    def __init__(self, path=None):
        self._path = Path(path) if path is not None else cfg.DESKTOP_CONFIG_FILE.with_name(
            "desktop.lock"
        )
        self._file = None
        self._listener = None
        self._token = secrets.token_hex(32).encode("ascii")
        self._closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def acquire_or_activate(self, timeout: float = 15.0) -> bool:
        """Own the launcher, or wake its owner and return False.

        Retry while the first launch is still initializing. If that process
        exits during startup, the OS releases its lock and this launch takes
        over. A live but unresponsive owner must never create a second GUI.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o600)
        self._file = os.fdopen(fd, "r+b", buffering=0)
        deadline = time.monotonic() + timeout
        while True:
            if _try_lock(self._file):
                self._start_listener()
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "AI Launcher is already running, but its window did not respond."
                )
            if self._activate_existing(min(remaining, 1.0)):
                return False
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    def _start_listener(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(0.2)
        state = json.dumps({
            "pid": os.getpid(),
            "port": self._listener.getsockname()[1],
            "token": self._token.decode("ascii"),
        }).encode("ascii")
        # Byte zero is locked on Windows; other processes can read the metadata
        # after it. Keep this file in place so contenders always lock the same file.
        self._file.seek(1)
        self._file.write(state)
        self._file.truncate()

    def _activate_existing(self, timeout: float) -> bool:
        try:
            self._file.seek(1)
            state = json.loads(self._file.read(4096))
            pid, port, token = state["pid"], state["port"], state["token"]
            if not (
                isinstance(pid, int) and 0 < pid < 0xFFFFFFFF
                and isinstance(port, int) and 0 < port < 65536
                and isinstance(token, str) and len(token) == 64
            ):
                return False
            with socket.create_connection(("127.0.0.1", port), timeout=timeout) as client:
                _allow_foreground(pid)
                client.sendall(token.encode("ascii") + b"\n")
                with client.makefile("rb") as response:
                    return response.read(3) == b"ok\n"
        except (OSError, ValueError, KeyError, TypeError):
            # The owner may not have published its endpoint yet, or may be
            # shutting down. Recheck ownership before attempting activation again.
            return False

    def listen(self, window) -> None:
        """Serve activation requests in pywebview.start's worker thread."""
        listener = self._listener
        while not self._closed.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with client:
                client.settimeout(1.0)
                try:
                    with client.makefile("rb") as request:
                        token = request.readline(128)
                    if not secrets.compare_digest(token, self._token + b"\n"):
                        continue
                    # These public APIs marshal work onto the native GUI thread.
                    # Do not mutate window.native or toggle WinForms TopMost here.
                    window.restore()
                    window.show()
                    client.sendall(b"ok\n")
                except OSError:
                    continue
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Could not activate the launcher window", exc_info=True
                    )

    def close(self) -> None:
        self._closed.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._file is not None:
            # Closing the handle releases the OS lock, even after startup errors.
            self._file.close()
            self._file = None
