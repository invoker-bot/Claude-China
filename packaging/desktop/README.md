# Native desktop distribution

End users download installers from GitHub Releases. PyPI continues to deliver
the CLI, and the `[desktop]` extra is retained for development. Each installer
contains the desktop application, Python and its Python dependencies.

## Outputs and operating-system ownership

| Target | Output | Ownership and removal |
| --- | --- | --- |
| Windows x64 | `Claude-China-<version>-windows-x64-setup.exe` | Inno Setup installs per user in `%LOCALAPPDATA%\Programs\Claude China`, creates a Start Menu entry and registers an uninstaller in Installed apps. The desktop shortcut is optional. |
| macOS arm64 / x64 | `Claude-China-<version>-macos-<arch>.dmg` | A self-contained `Claude China.app` and an Applications link. Drag to Applications to install; quit and move the app to Trash to uninstall. |
| Linux x64 | `Claude-China-<version>-linux-x64.deb` and `.rpm` | The package manager owns `/opt/claude-china`, the command symlink, application menu entry and icon. Remove `claude-china-desktop` with apt/dnf or the software manager. |

The Windows AppId and macOS bundle ID remain constant across versions.
Installing a newer package upgrades the same app. The application never
installs its own shortcuts. No installer or uninstaller deletes `~/.code-ai/`,
which contains shared CLI profiles, credentials and desktop settings.

Quit the old Python launcher and remove its old Desktop/Start Menu shortcut
before migrating. A macOS AppleScript shortcut on the Desktop is not the new
native `.app`. Native installation does not uninstall Python packages;
`ai-code-switcher` and, if no longer needed for the CLI, `claude-china` can be
removed separately using pip.

Windows 10/11 needs WebView2. Setup checks Microsoft's documented registry
locations and runs a bundled, Microsoft-signed Evergreen bootstrapper only
when necessary. This requires internet access on machines without WebView2.
The shared Microsoft runtime is not removed by our uninstaller.

Linux packages target glibc 2.35 or newer and GTK 3 / WebKitGTK 4.1. Build Linux
releases on Ubuntu 22.04 so newer build-host glibc symbols do not silently raise
the minimum OS requirement. Configure actual desktop executables on Linux;
the launcher does not substitute `claude`/`codex` terminal CLIs. Select the
installed or extracted executable, not a shell wrapper or an AppImage runtime.
Closing the Linux window exits, even without an AppIndicator host.

## Local builds

Build on the target OS and CPU architecture. PyInstaller cannot cross-compile.
Start with an isolated environment so other installed GUI toolkits do not
enter the bundle.

Windows (Python 3.12 and Inno Setup 6):

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install ".[desktop]" -r packaging/desktop/requirements.txt
$env:ISCC_EXE = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
.venv/Scripts/python tools/build_desktop.py --smoke
python tools/test_windows_installer.py dist/installers/Claude-China-<version>-windows-x64-setup.exe
```

The last command requires a clean Windows user: it refuses to overwrite an
existing native installation. It installs into a unique temporary directory,
checks the uninstall registry entry and isolated Start Menu shortcut, runs the
installed GUI, repairs the installation, then runs the registered uninstaller
and verifies removal. It never creates a desktop shortcut.

macOS (Python 3.12):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[desktop]" -r packaging/desktop/requirements.txt
.venv/bin/python tools/build_desktop.py --smoke
```

Linux (Ubuntu 22.04, system Python 3.10 to match the system PyGObject ABI):

```bash
sudo apt-get install python3-venv python3-dev libpython3.10 python3-gi \
  python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  gir1.2-ayatanaappindicator3-0.1 binutils rpm xvfb xauth dbus-x11 \
  desktop-file-utils fonts-noto-cjk
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip "setuptools>=64" wheel
.venv/bin/python -m pip install ".[desktop]" -r packaging/desktop/requirements.txt
xvfb-run -a dbus-run-session -- .venv/bin/python tools/build_desktop.py --smoke
```

`linux/Dockerfile` supplies the same Linux build dependencies for local
container builds. Run GUI tests as a non-root user so WebKit's sandbox can
operate normally. For root-only disposable CI containers, WebKit may require
`WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1`; never embed that setting in a
distributed app or run a user-facing desktop app as root.

Outputs go to `dist/installers/`, with a SHA-256 sidecar for each package.
`--freeze-only` builds just the runnable bundle; `--skip-freeze` reuses it.
`--smoke` opens an actual hidden native webview, loads the bundled HTML/CSS/JS
and icon, waits for the UI to initialize through the real Python bridge, and
writes `build/desktop/smoke.json`. It uses temporary configuration and does not
read or overwrite the user's settings.

## Release workflow

`.github/workflows/desktop-release.yml` builds Windows x64, macOS Intel, macOS
Apple Silicon and Linux x64 on native GitHub runners. PRs and manual dispatch
only upload Actions artifacts. A `v*` tag must match
`src/claude_china/__init__.py`; all build and validation jobs must succeed
before the workflow publishes five installer files and `SHA256SUMS` to the
matching GitHub Release. The existing PyPI workflow remains independent.
Update `pyproject.toml` and `__version__` together before tagging a new version.

Validation covers the full pytest suite, each frozen GUI, the Windows
install/repair/uninstall cycle, the mounted macOS disk image, Debian
installation/removal, and RPM installation, native GUI startup and removal in
a disposable Fedora 44 container.

## Signing

Default builds are unsigned on Windows and ad-hoc signed on macOS. Publisher
reputation and Gatekeeper approval are separate from a successful build.
Users may see OS warnings; public releases should be signed by their maintainer.
Do not claim a release is signed or notarized unless its artifacts are verified.

For macOS, import a Developer ID Application certificate into the build user's
keychain and export `MACOS_SIGNING_IDENTITY` before building. Optionally set
`MACOS_NOTARY_PROFILE` to an existing `xcrun notarytool store-credentials`
keychain profile; the builder submits the DMG, waits for notarization and staples
the result. Hosted CI does not provision credentials automatically. Keep
certificates and passwords in CI secrets, never in this repository.

Windows maintainers can sign the frozen executable before running
`tools/build_desktop.py --skip-freeze`, then sign the resulting setup EXE and
regenerate its SHA-256 sidecar before uploading. The bundled WebView2 bootstrapper
is independently checked against Microsoft's Authenticode signature.

## Packaging references

- [PyInstaller external-process library isolation](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application)
- [Microsoft WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [Inno Setup per-user installation](https://jrsoftware.org/ishelp/topic_admininstallmode.htm)
