## Claude China 0.4.0

This release adds a terminal workspace, native updates, launch checks and a
redesigned desktop interface. The desktop installers include Python; installing
the CLI package separately is optional.

### What's new

- **My apps / My terminals / Settings:** Settings is a normal navigation tab.
  Switching tabs or settings categories preserves unsaved edits. Windows and
  Linux use an integrated titlebar with minimize, maximize and close controls.
- **My terminals:** create, edit, rename, copy, search and delete the same CLI
  profiles used by `claudec`. Open a project folder, an ordinary terminal, or
  Claude Code / Codex CLI / Grok CLI with the selected profile. Saved credentials
  are masked and are not placed in terminal command arguments.
- **Grok Bot desktop:** detection, start/restart, stop and per-app environment
  settings alongside Claude and Codex. The application icons have been corrected.
- **Native updates:** manually check from the header, Settings or tray, download
  with SHA-256 verification, then install and restart the launcher. Launched
  provider apps are left running. Save or cancel unsaved settings before updating.
- **Launch checks:** optionally derive `HTTP_PROXY` and `HTTPS_PROXY` from the
  system HTTP proxy. Invalid proxy settings block launch when this is enabled.
  Regional checks apply a shared blocked-region policy; strict mode also blocks
  unknown or failed IP checks. Timezone, language and region are displayed for
  inspection. These checks do not guarantee account safety.
- **Windows original-entry takeover:** opt-in, independent registrations for
  fixed-path Claude, Codex and Grok Bot EXEs. Original-entry launches and same-path
  updater restarts run fresh checks and inject the configured environment.

### Install and upgrade

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **macOS:** choose `arm64` for Apple Silicon or `x64` for Intel, open the DMG and drag Claude China to Applications. Quit and move the app to Trash to uninstall.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude, Codex or Grok Bot themselves.

Install v0.4.0 manually when upgrading from v0.3.0, which predates the in-app
update controls. Future compatible releases can use the new updater.

macOS release builds must pass Developer ID signing and Apple notarization.
Windows signing service enrollment is pending; Windows downloads currently
remain unsigned and may show trust warnings. Check downloads against
`SHA256SUMS`. See the [signing setup and status](https://github.com/invoker-bot/Claude-China/blob/main/packaging/desktop/SIGNING.md).

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
