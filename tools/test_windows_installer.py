"""Install, repair, launch and uninstall the actual EXE in an isolated directory.

Run on a clean Windows user (as in CI). Refuse to overwrite an existing native
installation. Start Menu entries are isolated; no desktop shortcut is created.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import winreg

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudeChina.DesktopLauncher_is1"


def registration():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            return {name: winreg.QueryValueEx(key, name)[0] for name in
                    ("DisplayName", "DisplayVersion", "InstallLocation", "UninstallString")}
    except FileNotFoundError:
        return None


def run(args):
    subprocess.run([str(arg) for arg in args], check=True, timeout=180,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    if registration() is not None:
        raise RuntimeError("Use a clean Windows user; Claude China is already installed.")
    installer = args.installer.resolve(strict=True)
    artifacts = Path(__file__).resolve().parents[1] / "build/desktop"
    artifacts.mkdir(parents=True, exist_ok=True)
    # Keep diagnostic logs even after a failure; only the installed app is removed.
    root = Path(tempfile.mkdtemp(prefix="installer-test-", dir=artifacts)).resolve()
    destination = root / "application"
    group = root.name
    menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / group
    settings = {path: hashlib.sha256(path.read_bytes()).digest()
                for path in (Path.home() / ".code-ai").glob("*.yaml")}
    try:
        for phase in ("install", "repair"):
            run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                 f"/DIR={destination}", f"/GROUP={group}", "/TASKS=",
                 f"/LOG={root / (phase + '.log')}"])
            entry = registration()
            assert entry and entry["DisplayName"] == "Claude China", entry
            assert Path(entry["InstallLocation"]).resolve() == destination
            assert (menu / "Claude China.lnk").is_file()
            report = root / f"{phase}-smoke.json"
            run([destination / "claude-china-desktop.exe", "--smoke-test", report])
            result = json.loads(report.read_text(encoding="utf-8"))
            assert result["ok"] and result["frozen"], result
            assert result["version"] == entry["DisplayVersion"], result
            print(f"{phase}: registered app, Start Menu shortcut and packaged GUI verified",
                  flush=True)
    finally:
        entry = registration()
        if entry:
            # Never run an uninstaller unless its registered location is
            # the exact directory created by this test.
            assert Path(entry["InstallLocation"]).resolve() == destination
            assert root in destination.resolve().parents
            uninstaller = Path(entry["UninstallString"].strip('"')).resolve()
            assert uninstaller == destination / "unins000.exe"
            run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                 f"/LOG={root / 'uninstall.log'}"])
            # Inno's uninstaller hands off to a temporary second process.
            deadline = time.monotonic() + 30
            while destination.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
    assert registration() is None
    assert not destination.exists()
    assert not (menu / "Claude China.lnk").exists()
    assert all(path.is_file() and hashlib.sha256(path.read_bytes()).digest() == digest
               for path, digest in settings.items())
    print("uninstall: registration, runtime and shortcut removed; user settings preserved",
          flush=True)


if __name__ == "__main__":
    main()
