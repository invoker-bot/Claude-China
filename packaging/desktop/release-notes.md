## Claude China 0.4.1

This release adds searchable CLI session history and favorite project folders
to My terminals. The desktop installers include Python; installing the CLI
package separately is optional.

### What's new

- **Session history:** browse and search local Claude Code, Codex CLI and Grok
  CLI sessions for the selected profile, including sessions started outside the
  launcher. Resume the selected session in its original project directory.
- **Favorite projects:** pin folders, revisit recent projects and start a fresh
  conversation with the selected CLI profile. Missing directories are identified
  before launch. Favorites and recent projects persist across launcher restarts.
- **Launch validation:** resume and new-session actions use the configured
  environment, proxy and safety checks. Conflicting default session or directory
  arguments are rejected instead of opening a different conversation or project.
- **Profile isolation:** history follows the selected profile's CLI home. Reading
  history does not launch a provider, change its files or contact a remote service.
- **UI reliability:** profile changes discard stale history responses, and repeated
  clicks cannot create duplicate terminal launches while a launch is pending.

See the [terminal workspace guide](https://github.com/invoker-bot/Claude-China/blob/main/docs/desktop-terminals.md)
for supported history formats and limits.

### Install and upgrade

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

v0.4.1 publishes Windows, Linux and the CLI. macOS Intel and Apple Silicon builds
are validated in GitHub Actions and remain available there as development
artifacts; this Release does not include DMG downloads.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude, Codex or Grok Bot themselves.

From v0.4.0, choose **检查更新 → 下载更新 → 安装并重启** in the desktop app.
Only Claude China restarts; running Claude, Codex and Grok Bot apps stay open.
Save or cancel unsaved settings before updating. Install v0.4.1 manually when
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
