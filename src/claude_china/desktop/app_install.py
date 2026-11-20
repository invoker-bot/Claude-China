import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import platform as platform_module
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from dataclasses import dataclass

from .. import __version__
from . import config
from .apps import get_app


MAX_PAGE = 8 * 1024 * 1024
MAX_DOWNLOAD = 2 * 1024 * 1024 * 1024


class InstallError(Exception):
    pass


class InstallCancelled(InstallError):
    pass


@dataclass(frozen=True)
class InstallSpec:
    page: str
    hosts: tuple
    publishers: tuple
    required_path: str = ""
    excluded_path: str = ""
    store_id: str = ""


@dataclass(frozen=True)
class InstallPlan:
    app_id: str
    url: str
    filename: str
    method: str


INSTALL_SPECS = {
    "claude": InstallSpec(
        "https://claude.com/download",
        ("claude.com", "claude.ai", "downloads.claude.ai"),
        ("Anthropic",), excluded_path="claude-science", store_id="9P6K58THS811",
    ),
    "codex": InstallSpec(
        "https://chatgpt.com/codex/",
        ("chatgpt.com", "persistent.oaistatic.com", "get.microsoft.com", "download.microsoft.com"),
        ("Microsoft", "OpenAI"), required_path="codex-app-prod",
    ),
    "grok-bot": InstallSpec(
        "https://cursor.com/download/bot",
        ("cursor.com", "downloads.cursor.com"),
        ("Cursor", "Anysphere"), required_path="grokbot",
    ),
    "antigravity": InstallSpec(
        "https://antigravity.google/download/",
        ("antigravity.google", "storage.googleapis.com"),
        ("Google",), required_path="antigravity-hub",
    ),
}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "href" and value:
                self.values.append(value)


def extract_links(html, base_url):
    parser = _Links()
    parser.feed(html)
    values = parser.values + re.findall(r'https?://[^\s"<>]+', html)
    result = []
    for value in values:
        value = value.replace(chr(92) + "u0026", "&").replace(chr(92) + "/", "/").rstrip(chr(92))
        value = urllib.parse.urljoin(base_url, value.strip())
        if value not in result:
            result.append(value)
    return result


def _valid_url(value, spec):
    try:
        parsed = urllib.parse.urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in spec.hosts
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


def _arch_score(value, arch):
    value = value.lower()
    arm = any(marker in value for marker in ("arm64", "aarch64", "darwin-arm/", "windows-arm/", "linux-arm/"))
    x64 = any(marker in value for marker in ("x64", "amd64", "x86_64", "darwin-x64/", "win32-x64/"))
    universal = "universal" in value
    if arch == "arm64":
        if x64 and not universal:
            return -1
        return 2 if arm else 1 if universal else 0
    if arm:
        return -1
    return 2 if x64 else 1 if universal else 0


def _platform_candidate(value, platform, package_format):
    lower = value.lower()
    if platform == "win32":
        if any(marker in lower for marker in ("darwin", "linux", ".dmg", ".deb", ".rpm", ".appimage", ".tar.gz")):
            return 0
        if lower.endswith(".exe"):
            return 4
        if "/api/desktop/" in lower and "/setup/" in lower:
            return 4
        if urllib.parse.urlsplit(value).hostname == "get.microsoft.com":
            return 3
        return 0
    if platform == "darwin":
        if any(marker in lower for marker in ("win32", "windows", "linux", ".exe", ".deb", ".rpm", ".appimage", ".tar.gz")):
            return 0
        if "/api/desktop/" in lower and "/dmg/" in lower:
            return 4
        return 4 if lower.endswith(".dmg") else 0
    if platform == "linux":
        if any(marker in lower for marker in ("darwin", "win32", "windows", ".dmg", ".exe")):
            return 0
        if lower.endswith(".deb"):
            return 5 if package_format == "deb" else 3
        if lower.endswith(".rpm"):
            return 5 if package_format == "rpm" else 3
        if lower.endswith(".appimage"):
            return 2
        if lower.endswith(".tar.gz"):
            return 1
    return 0


def select_plan(app_id, html, base_url, platform, machine, package_format="deb"):
    spec = INSTALL_SPECS[app_id]
    if platform == "win32" and spec.store_id:
        return InstallPlan(app_id, "ms-windows-store://pdp/?productid=" + spec.store_id, "", "store-link")
    arch = "arm64" if machine.lower() in ("arm64", "aarch64") else "x64"
    candidates = []
    for value in extract_links(html, base_url):
        if not _valid_url(value, spec):
            continue
        decoded = urllib.parse.unquote(value)
        if spec.excluded_path and spec.excluded_path in decoded:
            continue
        if urllib.parse.urlsplit(value).hostname != "get.microsoft.com":
            if spec.required_path and spec.required_path not in decoded:
                continue
        arch_score = _arch_score(decoded, arch)
        platform_score = _platform_candidate(decoded, platform, package_format)
        if arch_score < 0 or not platform_score:
            continue
        candidates.append((arch_score, platform_score, value))
    if not candidates:
        app = get_app(app_id)
        return InstallPlan(app_id, spec.page, "", "page")
    _, _, url = max(candidates)
    app = get_app(app_id)
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname == "get.microsoft.com":
        filename = app.display + "-Store-Setup.exe"
        method = "store"
    else:
        filename = urllib.parse.unquote(Path(parsed.path).name)
        if platform == "win32" and not filename.lower().endswith(".exe"):
            filename = app.display + "-Setup.exe"
        elif platform == "darwin" and not filename.lower().endswith(".dmg"):
            filename = app.display + ".dmg"
        method = "archive" if filename.lower().endswith(".tar.gz") else "package"
    if not re.fullmatch(r"[\w .()+-]{1,120}", filename):
        raise InstallError("官方安装文件名无效。")
    return InstallPlan(app_id, url, filename, method)


def linux_package_format():
    try:
        values = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value.strip().strip('"').lower()
        family = values.get("ID", "") + " " + values.get("ID_LIKE", "")
        if any(value in family for value in ("fedora", "rhel", "centos", "suse")):
            return "rpm"
    except OSError:
        pass
    return "deb"


def _open(url, spec):
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not _valid_url(urllib.parse.urljoin(req.full_url, newurl), spec):
                raise InstallError("官方下载被重定向到不受信任的地址。")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 Claude-China/" + __version__,
        "Accept": "text/html,application/octet-stream;q=0.9,*/*;q=0.8",
    })
    return urllib.request.build_opener(Redirect()).open(request, timeout=30)


def resolve_plan(app_id, platform=None, machine=None, package_format=None):
    if app_id not in INSTALL_SPECS:
        raise InstallError("此应用没有可用的官方安装渠道。")
    spec = INSTALL_SPECS[app_id]
    platform = sys.platform if platform is None else platform
    machine = platform_module.machine() if machine is None else machine
    package_format = linux_package_format() if package_format is None else package_format
    try:
        with _open(spec.page, spec) as response:
            raw = response.read(MAX_PAGE + 1)
            base_url = response.geturl()
    except InstallError:
        raise
    except Exception:
        raise InstallError("无法读取官方安装页面，请检查网络后重试。") from None
    if len(raw) > MAX_PAGE:
        raise InstallError("官方安装页面内容过大。")
    return select_plan(app_id, raw.decode("utf-8", "replace"), base_url,
                       platform, machine, package_format)


def download(plan, directory, cancelled, progress):
    spec = INSTALL_SPECS[plan.app_id]
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination = directory / plan.filename
    partial = destination.with_name(destination.name + ".part")
    received, digest = 0, hashlib.sha256()
    deadline = time.monotonic() + 3600
    try:
        with _open(plan.url, spec) as response, partial.open("xb") as stream:
            length = response.headers.get("Content-Length")
            try:
                total = int(length) if length else 0
            except ValueError:
                total = 0
            if total < 0 or total > MAX_DOWNLOAD:
                raise InstallError("官方安装包大小无效。")
            while True:
                if cancelled.is_set():
                    raise InstallCancelled()
                if time.monotonic() > deadline:
                    raise InstallError("下载超时，请重试。")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_DOWNLOAD or total and received > total:
                    raise InstallError("官方安装包大小异常。")
                digest.update(chunk)
                stream.write(chunk)
                progress(received, total)
        if cancelled.is_set():
            raise InstallCancelled()
        if not received:
            raise InstallError("官方安装包为空。")
        partial.replace(destination)
        return destination, digest.hexdigest()
    finally:
        partial.unlink(missing_ok=True)


def verify_windows_signature(path, publishers):
    script = ("$s=Get-AuthenticodeSignature -LiteralPath $env:CLAUDE_CHINA_INSTALLER; "
              "[pscustomobject]@{Status=[string]$s.Status;Subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''}} "
              "| ConvertTo-Json -Compress")
    env = dict(os.environ, CLAUDE_CHINA_INSTALLER=str(path))
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env=env, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
    except Exception:
        raise InstallError("无法验证官方安装器签名，已取消启动。") from None
    subject = data.get("Subject", "").lower()
    if result.returncode or data.get("Status") != "Valid" or not any(
            publisher.lower() in subject for publisher in publishers):
        raise InstallError("官方安装器签名或发布者无效，已取消启动。")


def launch_installer(plan, path):
    spec = INSTALL_SPECS[plan.app_id]
    try:
        if sys.platform == "win32":
            verify_windows_signature(path, spec.publishers)
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif plan.method == "package" and path.suffix.lower() == ".appimage":
            path.chmod(0o700)
            subprocess.Popen([str(path)], cwd=str(path.parent), start_new_session=True)
        else:
            subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
    except InstallError:
        raise
    except Exception:
        raise InstallError("无法启动官方安装器，请打开下载目录手动安装。") from None


class AppInstallManager:
    def __init__(self, root=None):
        self._root = Path(root) if root else config.DESKTOP_CONFIG_FILE.parent / "app-installers"
        self._lock = threading.RLock()
        self._states = {}
        self._cancelled = {}
        self._closed = False

    def status(self, app_id):
        get_app(app_id)
        with self._lock:
            return dict(self._states.get(app_id, {
                "app_id": app_id, "phase": "idle", "progress": 0,
                "message": "", "method": "",
            }))

    def _set(self, app_id, **changes):
        with self._lock:
            state = self.status(app_id)
            state.update(changes)
            self._states[app_id] = state
            return dict(state)

    def start(self, app_id, installed):
        spec = INSTALL_SPECS.get(app_id)
        if spec is None:
            raise InstallError("此应用没有可用的官方安装渠道。")
        with self._lock:
            if self._closed:
                return self.status(app_id)
            if self.status(app_id)["phase"] in ("resolving", "downloading", "launching"):
                return self.status(app_id)
            cancelled = self._cancelled[app_id] = threading.Event()
            self._set(app_id, phase="resolving", progress=0,
                      message="正在选择官方安装方式…", method="")

        def work():
            try:
                if installed():
                    self._set(app_id, phase="launched", progress=100, message="应用已经安装。", method="")
                    return
                plan = resolve_plan(app_id)
                if cancelled.is_set():
                    raise InstallCancelled()
                if plan.method in ("page", "store-link"):
                    if plan.method == "store-link" and sys.platform == "win32":
                        os.startfile(plan.url)
                        message = "已打开 Microsoft Store，请点击安装。"
                    else:
                        import webbrowser
                        webbrowser.open(plan.url)
                        message = "已打开官方安装页面，请按页面说明安装。"
                    self._set(app_id, phase="launched", progress=0, message=message, method=plan.method)
                    return
                self._set(app_id, phase="downloading", message="正在下载官方安装包…", method=plan.method)
                directory = self._root / uuid.uuid4().hex
                path, _ = download(plan, directory, cancelled,
                                   lambda done, total: self._set(
                                       app_id, progress=int(done * 100 / total) if total else 0))
                if installed():
                    self._set(app_id, phase="launched", progress=100, message="应用已经安装。", method=plan.method)
                    return
                self._set(app_id, phase="launching", progress=100, message="正在启动官方安装器…")
                launch_installer(plan, path)
                message = ("已下载官方压缩包，请解压后运行 Antigravity。" if plan.method == "archive"
                           else "已启动官方安装器；安装完成后点击刷新。")
                self._set(app_id, phase="launched", message=message)
            except InstallCancelled:
                self._set(app_id, phase="idle", progress=0, message="已取消下载。")
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 404):
                    import webbrowser
                    webbrowser.open(spec.page)
                    self._set(app_id, phase="launched", method="page",
                              message="官方直链不可用，已打开官方安装页面。")
                else:
                    self._set(app_id, phase="error", message="官方安装包下载失败，请稍后重试。")
            except Exception as exc:
                message = str(exc) if isinstance(exc, InstallError) else "无法完成下载安装，请稍后重试。"
                self._set(app_id, phase="error", message=message[:500])

        threading.Thread(target=work, daemon=True, name="app-install-" + app_id).start()
        return self.status(app_id)

    def cancel(self, app_id):
        with self._lock:
            if self.status(app_id)["phase"] in ("resolving", "downloading", "launching"):
                self._cancelled[app_id].set()
                self._set(app_id, message="正在取消…")
        return self.status(app_id)

    def shutdown(self):
        with self._lock:
            self._closed = True
            for cancelled in self._cancelled.values():
                cancelled.set()
