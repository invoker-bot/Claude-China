"""Native installer handoff. The helper runs outside the installed application."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time

from . import process

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudeChina.DesktopLauncher_is1"
PACKAGE = "claude-china-desktop"
BUNDLE_ID = "com.claudechina.launcher"


def _run(args, **kwargs):
    result = process.run([str(arg) for arg in args], capture_output=True, text=True,
                         timeout=kwargs.pop("timeout", 60), **kwargs)
    if result.returncode:
        raise RuntimeError(f"更新操作未完成（{Path(str(args[0])).name}，退出码 {result.returncode}）。")
    return result.stdout.strip()


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def cleanup_jobs(root):
    """Remove only our inactive UUID staging folders, never settings or symlinks."""
    if not root.is_dir():
        return
    import psutil
    try:
        jobs = list(root.iterdir())
    except OSError:
        return
    for job in jobs:
        if (not re.fullmatch(r"[0-9a-f]{32}", job.name) or not job.is_dir()
                or job.is_symlink() or job.resolve().parent != root.resolve()
                or not (job / ".claude-china-update").is_file()):
            continue
        try:
            ready = job / "ready.json"
            if ready.is_file():
                pid = json.loads(ready.read_text(encoding="utf-8"))["pid"]
                if type(pid) is not int or psutil.pid_exists(pid):
                    continue
            shutil.rmtree(job)
        except (OSError, ValueError, KeyError):
            # A still-exiting Windows helper can retain a DLL/file handle.
            continue


def windows_registration():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return (Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve(),
                    winreg.QueryValueEx(key, "DisplayVersion")[0])
    except OSError:
        return None, None


def _mac_info(app):
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise RuntimeError("应用标识不匹配，已拒绝更新。")
    return info


def _mac_team(app):
    result = process.run(["/usr/bin/codesign", "-d", "--verbose=4", str(app)],
                         capture_output=True, text=True, timeout=30)
    match = re.search(r"^TeamIdentifier=([A-Z0-9]{10})$", result.stderr, re.MULTILINE)
    return match[1] if match else None


def verify_windows_signature(package, executable):
    # Preserve publisher continuity once the project has a signing certificate.
    # Unsigned v0.3 installations can migrate to the first signed release.
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$items = @($env:CLAUDE_UPDATE_FILE, $env:CLAUDE_UPDATE_CURRENT); "
        "$items | ForEach-Object { $s = Get-AuthenticodeSignature -LiteralPath $_; "
        "[pscustomobject]@{Status=[string]$s.Status; Subject=$s.SignerCertificate.Subject} } "
        "| ConvertTo-Json -Compress"
    )
    env = dict(os.environ, CLAUDE_UPDATE_FILE=str(package), CLAUDE_UPDATE_CURRENT=str(executable))
    for key in list(env):
        if key.upper() == "PSMODULEPATH":
            env.pop(key)
    shell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    data = json.loads(_run([shell, "-NoProfile", "-NonInteractive", "-Command", script], env=env))
    new, old = data
    if new["Status"] not in ("Valid", "NotSigned"):
        raise RuntimeError("Windows 安装包签名无效，已拒绝更新。")
    if old["Status"] == "Valid" and (
        new["Status"] != "Valid" or not new["Subject"] or new["Subject"] != old["Subject"]
    ):
        raise RuntimeError("更新的签名发布者与当前应用不一致。")


@dataclass
class Installation:
    kind: str
    target: Path
    suffix: str
    reason: str = ""

    @classmethod
    def detect(cls):
        machine = platform.machine().lower()
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        executable = Path(sys.executable).resolve()
        if sys.platform == "win32":
            kind, suffix, target = "windows", "windows-x64-setup.exe", executable.parent
        elif sys.platform == "darwin":
            kind, suffix = "macos", f"macos-{arch}.dmg"
            target = next((p for p in executable.parents if p.suffix == ".app"), executable.parent)
        else:
            kind = "deb" if Path("/usr/bin/dpkg-query").exists() else "rpm"
            suffix, target = f"linux-x64.{kind}", executable.parent
        result = cls(kind, target, suffix)
        if not getattr(sys, "frozen", False):
            result.reason = "开发模式仅支持检查更新，请通过发布页面安装桌面版。"
            return result
        if machine not in ("amd64", "x86_64", "arm64", "aarch64") or (arch == "arm64" and kind != "macos"):
            result.reason = "当前架构尚无原生更新包，请查看发布页面。"
            return result
        try:
            if kind == "windows" and windows_registration()[0] != target:
                raise RuntimeError("请先运行 Windows 安装包，再使用应用内更新。")
            if kind == "macos":
                _mac_info(target)
                if str(target).startswith("/Volumes/") or not os.access(target.parent, os.W_OK):
                    raise RuntimeError("请将应用移至有写入权限的 Applications 文件夹后更新。")
            if kind in ("deb", "rpm"):
                if target != Path("/opt/claude-china"):
                    raise RuntimeError("请先使用系统安装包安装，再使用应用内更新。")
                if not Path("/usr/bin/pkexec").is_file() or not result.package_manager().is_file():
                    raise RuntimeError("系统缺少图形授权或包管理器，请从发布页面手动安装更新。")
                result.installed_version()
        except (RuntimeError, OSError, ValueError) as exc:
            result.reason = str(exc)
        return result

    def executable(self):
        if self.kind == "macos":
            return self.target / "Contents/MacOS/claude-china-desktop"
        return self.target / ("claude-china-desktop.exe" if self.kind == "windows" else PACKAGE)

    def package_manager(self):
        return Path("/usr/bin/apt-get" if self.kind == "deb" else "/usr/bin/dnf")

    def installed_version(self):
        if self.kind == "windows":
            location, version = windows_registration()
            if location != self.target:
                raise RuntimeError("安装位置已改变，请重新打开应用后检查更新。")
            return version
        if self.kind == "macos":
            return _mac_info(self.target)["CFBundleShortVersionString"]
        if self.kind == "deb":
            return _run(["/usr/bin/dpkg-query", "-W", "-f=${Version}", PACKAGE])
        return _run(["/usr/bin/rpm", "-q", "--qf", "%{VERSION}", PACKAGE])

    def verify_package(self, package, version):
        if self.kind == "windows":
            verify_windows_signature(package, self.executable())
        elif self.kind == "deb":
            identity = _run(["/usr/bin/dpkg-deb", "-f", package, "Package", "Version", "Architecture"])
            expected = {"Package": PACKAGE, "Version": version, "Architecture": "amd64"}
            fields = dict(line.split(": ", 1) for line in identity.splitlines() if ": " in line)
            if fields != expected:
                raise RuntimeError("DEB 安装包的名称、版本或架构不匹配。")
        elif self.kind == "rpm":
            identity = _run(["/usr/bin/rpm", "-qp", "--qf", "%{NAME}\n%{VERSION}\n%{ARCH}", package])
            if identity.splitlines() != [PACKAGE, version, "x86_64"]:
                raise RuntimeError("RPM 安装包的名称、版本或架构不匹配。")

    def prepare(self, package, version, cancelled):
        import psutil
        job = package.parent
        if self.target.resolve() == job.resolve() or self.target.resolve() in job.resolve().parents:
            raise RuntimeError("更新暂存目录不能位于应用安装目录内，请手动安装更新。")
        (job / ".claude-china-update").touch()
        self.verify_package(package, version)
        if self.kind == "macos":
            self._prepare_mac(package, version)
        if cancelled.is_set():
            from .updates import UpdateCancelled
            raise UpdateCancelled()
        helper = job / ("helper.app" if self.kind == "macos" else "helper")
        # The original executable and its DLLs must be unlocked before Inno runs.
        # Preserve the complete signed bundle on macOS, including its symlinks.
        if self.kind == "macos":
            _run(["/usr/bin/ditto", self.target, helper], timeout=300)
        else:
            shutil.copytree(self.target, helper, symlinks=True)
        parent = psutil.Process()
        plan = {
            "kind": self.kind, "target": str(self.target), "suffix": self.suffix,
            "package": package.name, "version": version, "sha256": file_digest(package),
            "previous": self.installed_version(),
            "parent_pid": parent.pid, "parent_created": parent.create_time(),
        }
        path = job / "plan.json"
        write_json(path, plan)
        return path

    def _prepare_mac(self, package, version):
        job = package.parent
        mount = job / "mounted"
        mount.mkdir()
        _run(["/usr/bin/hdiutil", "attach", package, "-readonly", "-nobrowse",
              "-mountpoint", mount], timeout=120)
        try:
            new = mount / "Claude China.app"
            if _mac_info(new).get("CFBundleShortVersionString") != version:
                raise RuntimeError("macOS 安装包版本不匹配。")
            _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", new])
            _run(["/usr/sbin/spctl", "--assess", "--type", "execute", new])
            old_team, new_team = _mac_team(self.target), _mac_team(new)
            if not new_team or (old_team and old_team != new_team):
                raise RuntimeError("macOS 更新的 Developer ID 与当前应用不一致。")
            _run(["/usr/bin/ditto", new, job / "new.app"], timeout=300)
        finally:
            _run(["/usr/bin/hdiutil", "detach", mount], timeout=60)

    def apply(self, package, version):
        self.verify_package(package, version)
        if self.kind == "windows":
            _run([package, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                  "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/RESTARTEXITCODE=3010",
                  f"/DIR={self.target}", f"/LOG={package.parent / 'installer.log'}"], timeout=1800)
        elif self.kind in ("deb", "rpm"):
            command = ["/usr/bin/pkexec", self.package_manager(), "install", "-y"]
            if self.kind == "deb":
                command.append("--no-remove")
            _run(command + [package], timeout=1800)
        else:
            self._apply_mac(package.parent, version)
        if self.installed_version() != version:
            raise RuntimeError("安装器未完成版本升级，请从发布页面重新安装。")

    def _apply_mac(self, job, version):
        new = job / "new.app"
        if _mac_info(new).get("CFBundleShortVersionString") != version:
            raise RuntimeError("待安装应用的版本不匹配。")
        _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", new])
        _run(["/usr/sbin/spctl", "--assess", "--type", "execute", new])
        team = _mac_team(self.target)
        if not _mac_team(new) or (team and team != _mac_team(new)):
            raise RuntimeError("待安装应用的签名发布者不匹配。")
        # Both renames stay on the installation volume. Restore the original on
        # any failure; never delete the user's app before a replacement exists.
        incoming = self.target.with_name(".Claude China-incoming-" + job.name + ".app")
        backup = self.target.with_name(".Claude China-backup-" + job.name + ".app")
        if incoming.exists() or backup.exists():
            raise RuntimeError("发现未完成的应用替换，请先恢复上一次更新。")
        try:
            _run(["/usr/bin/ditto", new, incoming], timeout=300)
            self.target.rename(backup)
            try:
                incoming.rename(self.target)
            except Exception:
                backup.rename(self.target)
                raise
        finally:
            if incoming.exists():
                shutil.rmtree(incoming)
        # Cleanup is best effort: a valid replacement is already installed.
        try:
            shutil.rmtree(backup)
        except OSError:
            pass


def _detached_options():
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _spawn(args, cwd, output=subprocess.DEVNULL):
    return process.Popen([str(arg) for arg in args], cwd=str(cwd),
                         env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
                         stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                         **_detached_options())


def start_helper(plan):
    plan = Path(plan)
    data = json.loads(plan.read_text(encoding="utf-8"))
    helper = Installation(data["kind"], plan.parent / (
        "helper.app" if data["kind"] == "macos" else "helper"), data["suffix"])
    ready = plan.parent / "ready.json"
    ready.unlink(missing_ok=True)
    with (plan.parent / "helper.log").open("ab") as log:
        child = _spawn([helper.executable(), "--apply-update", plan], plan.parent, log)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError("更新助手无法启动，应用保持打开，请重新下载更新。")
        if ready.is_file():
            handshake = json.loads(ready.read_text(encoding="utf-8"))
            if handshake.get("pid") == child.pid:
                return child
        time.sleep(0.1)
    child.terminate()
    raise RuntimeError("更新助手启动超时，应用保持打开。")


def _wait_for_parent(pid, created):
    import psutil
    try:
        parent = psutil.Process(pid)
        if parent.create_time() != created:
            raise RuntimeError("原应用进程已改变，已取消更新。")
        parent.wait(timeout=120)
    except psutil.NoSuchProcess:
        pass


def apply_update(plan):
    """Hidden CLI entry, called by a staged copy, never under the GUI mutex."""
    plan = Path(plan).resolve()
    job = plan.parent
    # Reject arbitrary manifests/paths before doing anything with the install.
    if plan.name != "plan.json" or not re.fullmatch(r"[0-9a-f]{32}", job.name):
        return 1
    exited = False
    installation = None
    try:
        data = json.loads(plan.read_text(encoding="utf-8"))
        version = data["version"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise RuntimeError("更新版本号无效。")
        kind = data["kind"]
        if kind not in {"windows", "macos", "deb", "rpm"}:
            raise RuntimeError("不支持的更新类型。")
        target = Path(data["target"])
        if not target.is_absolute() or target.resolve() != target or job in target.parents or target in job.parents:
            raise RuntimeError("更新目标路径无效。")
        installation = Installation(kind, target, data["suffix"])
        valid_suffixes = {
            "windows": {"windows-x64-setup.exe"},
            "macos": {"macos-arm64.dmg", "macos-x64.dmg"},
            "deb": {"linux-x64.deb"}, "rpm": {"linux-x64.rpm"},
        }
        if data["suffix"] not in valid_suffixes[kind]:
            raise RuntimeError("更新安装包类型无效。")
        if kind in ("deb", "rpm") and target != Path("/opt/claude-china"):
            raise RuntimeError("Linux 更新必须由系统包管理器安装。")
        if kind == "macos" and (target.suffix != ".app" or target.is_symlink()):
            raise RuntimeError("macOS 应用路径无效。")
        package = job / data["package"]
        if (package.parent != job or package.name != f"Claude-China-{version}-{data['suffix']}"
                or not package.is_file() or file_digest(package) != data["sha256"]):
            raise RuntimeError("安装包在下载后被修改，已拒绝更新。")
        write_json(job / "ready.json", {"pid": os.getpid()})
        _wait_for_parent(data["parent_pid"], data["parent_created"])
        exited = True
        if file_digest(package) != data["sha256"]:
            raise RuntimeError("安装包在等待退出期间被修改，已拒绝更新。")
        if installation.installed_version() != data["previous"]:
            raise RuntimeError("已安装版本在更新期间发生改变，请重新检查更新。")
        installation.apply(package, version)
        result = {"ok": True, "message": f"已更新至 {version}。"}
    except Exception as exc:
        result = {"ok": False, "message": f"更新未完成：{exc} 原有设置已保留。"}
    write_json(job.parent / "result.json", result)
    if installation and exited:
        try:
            if installation.kind == "macos":
                _spawn(["/usr/bin/open", "-n", installation.target], installation.target.parent)
            else:
                arguments = [installation.executable()]
                # Native installer CI uses the existing isolated GUI smoke mode;
                # no arbitrary restart arguments or paths are accepted.
                if data.get("restart_smoke") is True:
                    arguments += ["--smoke-test", job / "restarted-smoke.json"]
                _spawn(arguments, installation.target.parent)
        except OSError as exc:
            result = {"ok": False, "message": f"更新后无法打开应用，请手动启动：{exc}"}
            write_json(job.parent / "result.json", result)
    return 0 if result["ok"] else 1
