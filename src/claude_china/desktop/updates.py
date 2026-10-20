"""Manual, asynchronous updates from this project's stable GitHub Releases."""

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from .. import __version__
from . import config
from .update_install import Installation, cleanup_jobs, start_helper

REPOSITORY = "https://github.com/invoker-bot/Claude-China"
LATEST_API = "https://api.github.com/repos/invoker-bot/Claude-China/releases/latest"
MAX_INSTALLER = 512 * 1024 * 1024


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise UpdateError("发布版本号无效，请在发布页面确认。")
    return tuple(int(part) for part in value.split("."))


@dataclass(frozen=True)
class ReleaseAsset:
    version: str
    name: str
    url: str
    checksum_url: str
    size: int
    digest: str


def parse_release(data, current, suffix):
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("尚无可用的正式发布版本。")
    tag = data.get("tag_name", "")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise UpdateError("发布版本号无效。")
    version = tag[1:]
    if version_tuple(version) <= version_tuple(current):
        return None
    name = f"Claude-China-{version}-{suffix}"
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("发布信息中缺少安装包。")

    def asset_named(filename):
        matches = [item for item in assets if isinstance(item, dict)
                   and item.get("name") == filename]
        if len(matches) != 1:
            raise UpdateError("此版本尚未提供当前系统的安装包或校验文件，请稍后重试。")
        item = matches[0]
        expected = f"{REPOSITORY}/releases/download/{tag}/{filename}"
        if item.get("browser_download_url") != expected:
            raise UpdateError("安装包下载地址不属于本项目，已拒绝更新。")
        return item

    artifact = asset_named(name)
    checksum = asset_named(name + ".sha256")
    size = artifact.get("size")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise UpdateError("安装包大小无效。")
    digest = artifact.get("digest") or ""
    if digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError("安装包摘要格式无效。")
    return ReleaseAsset(version, name, artifact["browser_download_url"],
                        checksum["browser_download_url"], size, digest[7:].lower())


class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or parsed.hostname not in {
                    "github.com", "api.github.com", "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
                }):
            raise UpdateError("更新下载被重定向到不受信任的地址。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"Claude-China/{__version__}",
        "Accept": "application/vnd.github+json" if url == LATEST_API else "application/octet-stream",
    })
    return urllib.request.build_opener(GitHubRedirect()).open(request, timeout=20)


def latest_release():
    try:
        with _open(LATEST_API) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise UpdateError("发布信息过大，无法检查更新。")
        return json.loads(data)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError("GitHub 请求次数受限，请稍后重试。") from exc
        if exc.code == 404:
            raise UpdateError("尚无可用的正式发布版本。") from exc
        raise UpdateError(f"无法获取发布信息（HTTP {exc.code}）。") from exc


def download(asset, directory, cancelled, progress):
    def check_cancelled():
        if cancelled.is_set():
            raise UpdateCancelled("已取消下载。")

    check_cancelled()
    with _open(asset.checksum_url) as response:
        checksum = response.read(4097).decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})  " + re.escape(asset.name), checksum)
    if not match or (asset.digest and asset.digest != match[1].lower()):
        raise UpdateError("发布摘要与校验文件不一致，已拒绝更新。")
    expected = match[1].lower()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / asset.name
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    received = 0
    deadline = time.monotonic() + 1800
    try:
        with _open(asset.url) as response, partial.open("xb") as stream:
            while True:
                check_cancelled()
                if time.monotonic() > deadline:
                    raise UpdateError("下载超时，请重试。")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > asset.size:
                    raise UpdateError("安装包大小与发布信息不一致。")
                digest.update(chunk)
                stream.write(chunk)
                progress(received, asset.size)
        check_cancelled()
        if received != asset.size or digest.hexdigest() != expected:
            raise UpdateError("安装包校验失败，请重新下载。")
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


class UpdateManager:
    """The JS bridge supplies actions, never paths, URLs or shell commands."""

    def __init__(self, quit_callback, root=None, current=__version__):
        self._root = Path(root) if root else config.DESKTOP_CONFIG_FILE.parent / "updates"
        self._current = current
        self._quit = quit_callback
        self._installation = Installation.detect()
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        self._closed = False
        self._asset = None
        self._plan = None
        self._state = {
            "phase": "idle", "current": current, "latest": "", "progress": 0,
            "message": "手动检查新版本", "can_install": not bool(self._installation.reason),
            "reason": self._installation.reason,
        }
        try:
            result = self._root / "result.json"
            if result.is_file():
                data = json.loads(result.read_text(encoding="utf-8"))
                self._state.update(phase="idle" if data.get("ok") else "error",
                                   message=str(data["message"])[:1000])
                result.unlink()
        except (OSError, ValueError, KeyError):
            logging.getLogger(__name__).warning("Could not read the previous update result")
        cleanup_jobs(self._root)

    def status(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)

    def _start(self, allowed, phase, message, action):
        with self._lock:
            if self._closed or self._state["phase"] not in allowed:
                return self.status()
            self._cancelled.clear()
            self._set(phase=phase, message=message, progress=0)

        def work():
            try:
                action()
            except UpdateCancelled:
                self._set(phase="available", message="已取消下载，可稍后重试。")
            except Exception as exc:
                logging.getLogger(__name__).exception("Desktop update failed")
                message = str(exc) if isinstance(exc, (UpdateError, RuntimeError)) else "无法完成更新，请检查网络、磁盘空间或安装权限后重试。"
                self._set(phase="error", message=message[:1000])

        threading.Thread(target=work, daemon=True, name="desktop-update").start()
        return self.status()

    def check(self):
        def work():
            self._asset = parse_release(latest_release(), self._current, self._installation.suffix)
            self._plan = None
            if self._asset:
                self._set(phase="available", latest=self._asset.version,
                          message=f"发现新版本 {self._asset.version}")
            else:
                self._set(phase="latest", latest="", message="当前已是最新版本。")
        return self._start({"idle", "latest", "available", "error", "ready"},
                           "checking", "正在检查 GitHub Releases…", work)

    def fetch(self):
        if not self._asset or self._installation.reason:
            return self.status()

        def work():
            cleanup_jobs(self._root)
            directory = self._root / uuid.uuid4().hex
            directory.mkdir(parents=True, mode=0o700)
            (directory / ".claude-china-update").touch()
            path = download(self._asset, directory, self._cancelled,
                            lambda done, total: self._set(progress=int(done * 100 / total)))
            self._set(message="下载完成，正在验证并准备安装…")
            self._plan = self._installation.prepare(path, self._asset.version, self._cancelled)
            if self._cancelled.is_set():
                raise UpdateCancelled()
            self._set(phase="ready", progress=100, message="更新已就绪，安装后将重新打开 Claude China。")
        return self._start({"available", "error"}, "downloading", "正在下载安装包…", work)

    def cancel(self):
        with self._lock:
            if self._state["phase"] == "downloading":
                self._cancelled.set()
                self._set(message="正在取消…")
        return self.status()

    def install(self):
        def work():
            if self._closed:
                return
            helper = start_helper(self._plan)
            try:
                if self._closed:
                    helper.terminate()
                    return
                self._quit()
            except Exception:
                helper.terminate()
                raise
        return self._start({"ready"}, "installing", "正在退出并安装更新…", work)

    def open_release(self):
        webbrowser.open(REPOSITORY + "/releases/latest")
        return {"ok": True}

    def shutdown(self):
        with self._lock:
            self._closed = True
            self._cancelled.set()
