Download the desktop app below; Python and the CLI package are not required.

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **macOS:** choose `arm64` for Apple Silicon or `x64` for Intel, open the DMG and drag Claude China to Applications. Quit and move the app to Trash to uninstall.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude, Codex or Grok Bot themselves.

The launcher now supports Grok Bot alongside Claude and Codex, including
automatic detection, launch/restart, stop and per-application environment settings.

The redesigned desktop window uses application cards and a separate settings
panel with category navigation. Unsaved settings survive category changes and
closing the panel; save or cancel each changed category before restarting for
an update.

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
