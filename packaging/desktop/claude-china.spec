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
data += [(str(root / "LICENSE"), "licenses/claude-china")]
hidden = []
excluded = ["tkinter", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6",
            "webview.platforms.qt", "webview.platforms.cef", "webview.platforms.android"]
if sys.platform == "linux":
    hidden += ["gi.repository.Gtk", "gi.repository.AyatanaAppIndicator3",
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
if sys.platform == "linux":
    # Native packages use the distribution's GTK/WebKit stack. Bundling Ubuntu's
    # GI library hardcodes its typelib search path, which cannot find Fedora's
    # /usr/lib64/girepository-1.0. Mixing bundled GLib with a newer system WebKit
    # also breaks ABI compatibility. Keep Python, its extension modules and the
    # two Python libraries whose SONAME differs between distributions.
    a.exclude_system_libraries(list_of_exceptions=["libbz2.so.*", "libcrypt.so.*"])
    a.datas = [
        entry for entry in a.datas
        if not entry[0].startswith(("gi_typelibs/", "lib/gdk-pixbuf/", "share/"))
    ]
    # These hooks redirect GTK to the bundled libraries/data removed above.
    system_gui_hooks = {"pyi_rth_gi", "pyi_rth_gtk", "pyi_rth_glib", "pyi_rth_gdkpixbuf"}
    a.scripts = [entry for entry in a.scripts if entry[0] not in system_gui_hooks]
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
    entitlements_file=str(root / "packaging/desktop/macos/entitlements.plist")
    if sys.platform == "darwin" else None,
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
