# Build on the target OS; PyInstaller does not cross-compile.
import os
from pathlib import Path
import runpy
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
version = runpy.run_path(str(root / "src/claude_china/__init__.py"))["__version__"]
data = collect_data_files("claude_china") + collect_data_files("webview")
data += copy_metadata("pywebview") + copy_metadata("proxy_tools")
hidden = []
excluded = ["tkinter", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6",
            "webview.platforms.qt", "webview.platforms.cef", "webview.platforms.android"]
if sys.platform == "linux":
    hidden += ["gi.repository.Gtk", "gi.repository.WebKit2",
               "gi.repository.Soup", "gi.repository.AyatanaAppIndicator3",
               "pystray._appindicator", "pystray._gtk", "pystray._xorg"]
elif sys.platform == "win32":
    hidden += ["pystray._win32", "webview.platforms.winforms"]
else:
    hidden += ["pystray._darwin", "webview.platforms.cocoa"]

a = Analysis(
    [str(root / "packaging/desktop/entry.py")],
    pathex=[str(root / "src")],
    binaries=[], datas=data, hiddenimports=hidden,
    hookspath=[], runtime_hooks=[], excludes=excluded,
    hooksconfig={"gi": {"module-versions": {"Gtk": "3.0", "WebKit2": "4.1", "Soup": "3.0"}}},
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = root / "src/claude_china/desktop/ui" / (
    "icon.icns" if sys.platform == "darwin" else "icon.ico"
)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="claude-china-desktop",
    debug=False, strip=False, upx=False, console=False,
    icon=str(icon) if sys.platform != "linux" else None,
    version=os.environ.get("CLAUDE_CHINA_VERSION_FILE") if sys.platform == "win32" else None,
    codesign_identity=os.environ.get("MACOS_SIGNING_IDENTITY") or None,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                     name="claude-china-desktop")
if sys.platform == "darwin":
    app = BUNDLE(
        collection, name="Claude China.app", icon=str(icon),
        bundle_identifier="com.claudechina.launcher",
        codesign_identity=os.environ.get("MACOS_SIGNING_IDENTITY") or None,
        info_plist={
            "CFBundleName": "Claude China",
            "CFBundleDisplayName": "Claude China",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
