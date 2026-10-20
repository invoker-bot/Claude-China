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
installed GUI, repairs the installation, performs an update through a staged
helper (including old-process exit and a restarted frozen GUI), then runs the registered uninstaller
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
install/repair/update/restart/uninstall cycle, the mounted macOS disk image, Debian
installation/removal, and RPM installation, native GUI startup and removal in
a disposable Fedora 44 container.

The Linux packages bundle Python and its extension modules, and use the host
distribution's GTK/WebKit libraries and GI typelibs through declared package
dependencies. Do not bundle Ubuntu's GLib or GI runtime into the RPM: its
compiled search paths and library versions are incompatible with Fedora.

## Signing

See [SIGNING.md](SIGNING.md) for certificate creation, GitHub credentials,
notarization checks and the Windows open-source signing application process.
The existing v0.3.0 downloads are unsigned on Windows and ad-hoc signed on macOS.

PR builds and default manual builds remain unsigned/ad-hoc. Manual runs can
enable `macos_signing` to exercise Developer ID signing and notarization.
Every future `v*` tag requires those macOS credentials: missing credentials or
failed signature/notarization/Gatekeeper checks stop the desktop release.
The workflow never falls back to an ad-hoc macOS release.

Windows signing still requires an approved signing provider and its workflow
integration. Its default build currently remains unsigned. `--signed` is
implemented only for macOS and fails explicitly on other platforms. Do not
describe a Windows release as signed until the application, installer and
uninstaller have all been signed and verified. The bundled WebView2 bootstrapper
is independently checked against Microsoft's Authenticode signature.

## In-app updates

The updater checks the fixed repository's `releases/latest` REST endpoint only
when requested. It compares numeric `X.Y.Z` versions, rejects drafts,
prereleases, missing architecture assets and downgrades, and requires the exact
installer filename and its `.sha256` sidecar. Downloads use HTTPS with a GitHub
redirect allowlist, bounded size/time, SHA-256 and the GitHub asset digest when
provided. No profiles, credentials or settings are sent to GitHub.

Each download has an isolated UUID staging directory in `~/.code-ai/updates`.
Only a completely verified download enables **安装并重启**. A copy of the current
runtime starts outside the installation directory, acknowledges readiness and
waits for the original PID (including creation time) to exit. It then rechecks
the package hash, invokes the native installer and reopens the launcher. The
helper never acquires the GUI/installer mutex and resets PyInstaller's process
environment for the new executable. Failed installations are reported on the
next launch; user settings are not part of the update transaction.
Inactive staging folders are cleaned at startup or before another download.

- Windows: requires the matching per-user Inno registration. Runs Inno with
  `/NORESTART`, `/NOCLOSEAPPLICATIONS` and `/NORESTARTAPPLICATIONS`; only the
  launcher is restarted. A valid existing Authenticode publisher must match the
  update. Unsigned installations can migrate to the first signed release;
  while signing enrollment is pending, unsigned updates still use HTTPS/hash
  verification. A required OS reboot is reported as an incomplete update.
- macOS: requires a writable installed `.app` outside `/Volumes`. Verifies the
  bundle identifier, version, code signature, Gatekeeper acceptance and Team ID
  continuity. Stages the new `.app` on the destination volume, renames the old
  bundle aside, swaps and restores the original if the swap fails. Ad-hoc
  development packages cannot be installed through this updater.
- Linux: requires the package-managed `/opt/claude-china` installation, `pkexec`
  and apt/dnf. Checks package identity/version/architecture, then uses the
  system authentication agent to authorize the package manager. Does not
  extract files over a package-managed installation or store an admin password.

The Windows native validation intentionally reinstalls the current build to
exercise the installer and restart lifecycle without publishing a fake newer
release. Unit tests separately cover newer/equal/older version selection,
cancelled/corrupt downloads, publisher continuity, parent-exit ordering, Linux
package commands, failed macOS swaps and restart failures. Real signed macOS
updates still need maintainer credentials; interactive Linux authorization
needs a desktop session and cannot be established by headless unit tests.

Reference behavior: [GitHub Releases REST API](https://docs.github.com/en/rest/releases/releases),
[Inno Setup parameters](https://jrsoftware.org/ishelp/topic_setupcmdline.htm),
[PyInstaller restart environment](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart).

## Packaging references

- [PyInstaller external-process library isolation](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application)
- [PyInstaller system library exclusion](https://pyinstaller.org/en/stable/spec-files.html#posix-specific-options)
- [Microsoft WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [Inno Setup per-user installation](https://jrsoftware.org/ishelp/topic_admininstallmode.htm)
