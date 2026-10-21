## Claude China 0.4.3

This release adds local usage, activity, tool-call and API-equivalent cost
statistics to the desktop app.
The desktop installers include Python; installing the CLI package separately
is optional.

### What's new

- **Statistics tab:** inspect token usage, active sessions, projects and active
  days over today, 7, 30 or 90 days. Filter by application, exact model and
  project, and explore daily token, session, call and cost trends.
- **Tool-call breakdown:** count Bash, Read, Write, custom and MCP tools by
  their recorded names. Search tools or select MCP only. Streaming fragments,
  transcript copies and status updates are deduplicated by call ID.
- **Model and cost breakdown:** view input, output and cached tokens alongside
  estimated API-equivalent USD costs using an offline official-price snapshot
  checked on 2026-10-22. Cache categories and supported context tiers are priced
  separately. Unknown model aliases remain unpriced, and partial coverage and
  assumptions are visible. Estimates are not subscription charges or invoices.
- **Local log sources:** read Claude Code, Codex and Grok CLI logs, including
  profile-specific homes and archived Codex sessions. Grok Bot's recognized
  local transcript caches provide activity only; missing token and call data
  stay unavailable instead of becoming zero.
- **Private, incremental indexing:** scans run in the background and reuse a
  local SQLite index. Prompts, responses, tool arguments and credentials are
  not retained in that index; no usage data is uploaded. Large histories may
  take several minutes on the first scan. Provider apps are not restarted.
- **Localized interface and English tour:** statistics support English,
  Simplified Chinese and Traditional Chinese, with an English sample screenshot
  in the README.

See the [statistics guide](https://github.com/invoker-bot/Claude-China/blob/v0.4.3/docs/desktop-statistics.md)
for supported sources, calculation rules, privacy and coverage limits.

### Install and upgrade

- **Windows x64:** run `*-setup.exe`. Remove it through Settings → Apps → Installed apps.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. Remove the `claude-china-desktop` package to uninstall.

v0.4.3 publishes Windows, Linux and the CLI. macOS Intel and Apple Silicon builds
are validated in GitHub Actions and remain available there as development
artifacts; this Release does not include DMG downloads.

Windows setup installs Microsoft's WebView2 Runtime if missing (internet required).
Linux requires GTK 3 and WebKitGTK 4.1; select an installed desktop executable in
the launcher settings. The packages do not include Claude, Codex or Grok Bot themselves.

From v0.4.0, choose **检查更新 → 下载更新 → 安装并重启** in the desktop app.
Only Claude China restarts; running Claude, Codex and Grok Bot apps stay open.
Save or cancel unsaved settings before updating. Install v0.4.3 manually when
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
