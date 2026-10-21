## Claude China 0.4.2

This release adds desktop language settings and an English screenshot tour.
The desktop installers include Python; installing the CLI package separately
is optional.

### What's new

- **Display language:** choose English, Simplified Chinese, Traditional Chinese
  or the system default in Settings → General. Unsupported system languages
  fall back to English.
- **Immediate switching:** language changes apply across apps, terminals,
  settings, launch diagnostics, the tray and the macOS application menu.
  The selection saves automatically and persists after restart.
- **Preserved drafts and user data:** switching language keeps unfinished
  settings, profile names, session titles, paths and credentials intact.
  CLI commands and launched provider apps keep their own language settings.
- **Offline translations:** the message catalogs ship inside the desktop
  installers and Python package, with no translation service required.
- **English README tour:** five screenshots demonstrate app launching,
  session history, favorite projects, proxy settings and language selection.
  A reproducible capture script uses isolated English example data.

See the [language settings guide](https://github.com/invoker-bot/Claude-China/blob/main/docs/desktop-localization.md)
for supported languages and localization behavior.

### Install and upgrade

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

v0.4.2 publishes Windows, Linux and the CLI. macOS Intel and Apple Silicon builds
are validated in GitHub Actions and remain available there as development
artifacts; this Release does not include DMG downloads.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude, Codex or Grok Bot themselves.

From v0.4.0, choose **检查更新 → 下载更新 → 安装并重启** in the desktop app.
Only Claude China restarts; running Claude, Codex and Grok Bot apps stay open.
Save or cancel unsaved settings before updating. Install v0.4.2 manually when
upgrading from v0.3.0, which predates the in-app update controls.

Windows signing service enrollment is pending; Windows downloads currently
remain unsigned and may show trust warnings. Check downloads against
`SHA256SUMS`. See the [signing setup and status](https://github.com/invoker-bot/Claude-China/blob/main/packaging/desktop/SIGNING.md).
The macOS Actions artifacts use ad-hoc signing and are not notarized.

The old `claudec desktop install` / `uninstall` commands now show migration
instructions. Quit the old Python launcher and remove its shortcut before
installing. Configuration now lives in `~/.claudec/`. Missing profile and
desktop settings files are automatically imported from `~/.code-ai/` on first
use; existing new files take priority and the old files remain as a backup.
Login credential paths stay unchanged. Uninstalling preserves both directories
and your credentials.

The CLI remains available with `python -m pip install --upgrade claude-china`.

### Platform limits

Windows takeover supports fixed EXE paths, including replacement at that same
path. MSIX packages and versioned installation paths are not supported, and the
UI refuses to enable takeover for those installations. Actual provider-app
takeover verification used Grok Bot only; running Claude and Codex were not
restarted or modified. macOS and Linux global takeover are not implemented.
Normal launches through this launcher still use their configured checks and
environment. See the [platform coverage](https://github.com/invoker-bot/Claude-China/blob/main/docs/launch-takeover-platforms.md).
