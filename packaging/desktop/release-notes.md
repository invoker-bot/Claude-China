Download the desktop app below; Python and the CLI package are not required.

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **macOS:** choose `arm64` for Apple Silicon or `x64` for Intel, open the DMG and drag Claude China to Applications. Quit and move the app to Trash to uninstall.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude or Codex themselves.

The Windows and macOS downloads are not publisher-signed/notarized and may
show operating-system trust warnings. Check downloads against `SHA256SUMS`.

The old `claudec desktop install` / `uninstall` commands now show migration
instructions. Quit the old Python launcher and remove its shortcut before
installing. Existing profiles, credentials and settings in `~/.code-ai/` are
reused and preserved during uninstall.

The CLI remains available with `python -m pip install --upgrade claude-china`.
