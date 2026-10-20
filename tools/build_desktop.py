"""Freeze the desktop app and build a native installer on the current OS."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import subprocess
import sys
import urllib.request

if __package__:
    from . import desktop_signing
else:
    import desktop_signing

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging/desktop"
WORK = ROOT / "build/desktop"
DIST = ROOT / "dist/desktop"
OUTPUT = ROOT / "dist/installers"
VERSION = runpy.run_path(str(ROOT / "src/claude_china/__init__.py"))["__version__"]


def command(args, **kwargs):
    print("+", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def reset_directory(path):
    # Only generated, project-local build trees may be recursively replaced.
    resolved = path.resolve()
    if not any(parent in resolved.parents for parent in (WORK.resolve(), DIST.resolve())):
        raise ValueError(f"Refusing to remove a non-build directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def architecture():
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "x64"
    if machine in ("arm64", "aarch64") and sys.platform == "darwin":
        return "arm64"
    raise RuntimeError(f"No installer is configured for {sys.platform}/{machine}")


def windows_version_file():
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )
    version_tuple = tuple(int(part) for part in VERSION.split(".")) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
                          mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("FileDescription", "Claude China desktop launcher"),
                StringStruct("ProductName", "Claude China"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("FileVersion", VERSION),
                StringStruct("OriginalFilename", "claude-china-desktop.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    path = WORK / "windows-version.txt"
    path.write_text(str(info), encoding="utf-8")
    return path


def freeze():
    env = os.environ.copy()
    if sys.platform == "win32":
        env["CLAUDE_CHINA_VERSION_FILE"] = str(windows_version_file())
    if sys.platform == "darwin":
        env["PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR"] = "1"
    # Fixed paths under the project; --noconfirm replaces only this app bundle.
    command([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", DIST, "--workpath", WORK / "pyinstaller",
             PACKAGING / "claude-china.spec"], cwd=ROOT, env=env)


def executable():
    if sys.platform == "darwin":
        return DIST / "Claude China.app/Contents/MacOS/claude-china-desktop"
    return DIST / "claude-china-desktop" / (
        "claude-china-desktop.exe" if sys.platform == "win32" else "claude-china-desktop"
    )


def smoke_test(binary, report=None):
    report = report or WORK / "smoke.json"
    report.unlink(missing_ok=True)
    command([binary, "--smoke-test", report], timeout=120)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("ok") or not result.get("frozen") or result.get("version") != VERSION:
        raise RuntimeError(f"Packaged GUI failed: {result}")
    print(json.dumps(result, indent=2), flush=True)


def windows_installer():
    compiler = os.environ.get("ISCC_EXE") or shutil.which("ISCC")
    if not compiler:
        candidate = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6/ISCC.exe"
        if candidate.is_file():
            compiler = str(candidate)
    if not compiler:
        raise RuntimeError("Install Inno Setup 6 or set ISCC_EXE to its compiler.")
    bootstrapper = WORK / "MicrosoftEdgeWebview2Setup.exe"
    if not bootstrapper.is_file():
        urllib.request.urlretrieve(
            "https://go.microsoft.com/fwlink/p/?LinkId=2124703", bootstrapper,
        )
    # Check the vendor signature before embedding a downloaded executable.
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:CLAUDE_WEBVIEW_BOOTSTRAPPER; "
        "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') "
        "{ throw 'Invalid Microsoft WebView2 signature' }"
    )
    verification_env = dict(os.environ, CLAUDE_WEBVIEW_BOOTSTRAPPER=str(bootstrapper))
    # PowerShell 7's module paths cannot be loaded by Windows PowerShell 5.1.
    for key in list(verification_env):
        if key.upper() == "PSMODULEPATH":
            verification_env.pop(key)
    command(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            env=verification_env)
    command([compiler, f"/DAppVersion={VERSION}",
             f"/DBundleDirectory={DIST / 'claude-china-desktop'}",
             f"/DOutputDirectory={OUTPUT}",
             f"/DIconFile={ROOT / 'src/claude_china/desktop/ui/icon.ico'}",
             f"/DWebViewBootstrapper={bootstrapper}",
             PACKAGING / "windows/installer.iss"])
    return [OUTPUT / f"Claude-China-{VERSION}-windows-x64-setup.exe"]


def macos_installer(arch, signing=None):
    if signing:
        desktop_signing.verify_macos_signature(DIST / "Claude China.app", signing.team, app=True)
        desktop_signing.notarize_macos_app(DIST / "Claude China.app", signing, WORK)
    staging = WORK / "dmg"
    reset_directory(staging)
    command(["ditto", DIST / "Claude China.app", staging / "Claude China.app"])
    (staging / "Applications").symlink_to("/Applications")
    target = OUTPUT / f"Claude-China-{VERSION}-macos-{arch}.dmg"
    target.unlink(missing_ok=True)
    command(["hdiutil", "create", "-volname", "Claude China", "-srcfolder", staging,
             "-format", "UDZO", target])
    if signing:
        desktop_signing.sign_macos_dmg(target, signing, WORK)
        (WORK / "signing.json").write_text(json.dumps({
            "version": VERSION, "platform": "darwin", "architecture": arch,
            "team": signing.team, "signed": True, "notarized": True,
            "gatekeeper": True,
        }, indent=2), encoding="utf-8")
    return [target]


def linux_installers():
    staging = WORK / "linux"
    reset_directory(staging)
    root = staging / "root"
    app = root / "opt/claude-china"
    shutil.copytree(DIST / "claude-china-desktop", app, symlinks=True)
    files = {
        "usr/share/applications/claude-china.desktop": PACKAGING / "linux/claude-china.desktop",
    }
    for target, source in files.items():
        destination = root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    from PIL import Image
    icon = root / "usr/share/icons/hicolor/256x256/apps/claude-china.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(ROOT / "src/claude_china/desktop/ui/icon.png") as source:
        source.resize((256, 256), Image.Resampling.LANCZOS).save(icon)
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/claude-china-desktop").symlink_to("/opt/claude-china/claude-china-desktop")
    deb_root = staging / "deb"
    shutil.copytree(root, deb_root, symlinks=True)
    (deb_root / "DEBIAN").mkdir()
    (deb_root / "DEBIAN/control").write_text(
        (PACKAGING / "linux/control").read_text().replace("@VERSION@", VERSION),
        encoding="utf-8",
    )
    deb = OUTPUT / f"Claude-China-{VERSION}-linux-x64.deb"
    command(["dpkg-deb", "--root-owner-group", "--build", deb_root, deb])
    rpm_root = staging / "rpm"
    for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (rpm_root / name).mkdir(parents=True)
    shutil.copytree(root, rpm_root / "SOURCES/root", symlinks=True)
    spec = rpm_root / "SPECS/claude-china.spec"
    spec.write_text((PACKAGING / "linux/claude-china.spec").read_text().replace(
        "@VERSION@", VERSION), encoding="utf-8")
    command(["rpmbuild", "--define", f"_topdir {rpm_root}",
             "--define", "__os_install_post %{nil}",
             "--define", "_build_id_links none", "-bb", spec])
    rpm = OUTPUT / f"Claude-China-{VERSION}-linux-x64.rpm"
    built = list((rpm_root / "RPMS").rglob("*.rpm"))
    if len(built) != 1:
        raise RuntimeError(f"Expected one RPM, found {len(built)}")
    shutil.copyfile(built[0], rpm)
    return [deb, rpm]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-freeze", action="store_true")
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Test the bundled GUI before packaging")
    parser.add_argument("--signed", action="store_true",
                        help="Require Developer ID signing and notarization (macOS)")
    args = parser.parse_args()
    if args.signed and sys.platform != "darwin":
        parser.error("--signed currently supports macOS only; Windows needs a signing provider")
    if not re.fullmatch(r"\d+\.\d+\.\d+", VERSION):
        parser.error("Native installer versions must have the form X.Y.Z")
    arch = architecture()
    (WORK / "signing.json").unlink(missing_ok=True)
    mac_signing = desktop_signing.macos_config(required=args.signed) if sys.platform == "darwin" else None
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not args.skip_freeze:
        freeze()
    if mac_signing:
        desktop_signing.verify_macos_signature(DIST / "Claude China.app", mac_signing.team, app=True)
    if args.smoke:
        smoke_test(executable())
    if args.freeze_only:
        return
    if sys.platform == "win32":
        artifacts = windows_installer()
    elif sys.platform == "darwin":
        artifacts = macos_installer(arch, mac_signing)
    elif sys.platform == "linux":
        artifacts = linux_installers()
    else:
        parser.error(f"Unsupported OS: {sys.platform}")
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{digest}  {artifact.name}\n", encoding="utf-8")
        print(f"Built {artifact} ({artifact.stat().st_size:,} bytes)", flush=True)


if __name__ == "__main__":
    main()
