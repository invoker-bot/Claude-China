## Claude China 0.5.0

This release adds Google Antigravity, strengthens profile management, and improves
router-mode recovery and desktop distribution.

- **Antigravity:** Launch the Antigravity desktop app on Windows, macOS and Linux.
  Manage native `agy` CLI profiles with Gemini API keys, custom compatible endpoints,
  proxies and argument forwarding. The provider ID is `antigravity`; existing
  `antigravity-cli` records migrate automatically. Google account-token extraction,
  account rotation, Antigravity history and usage statistics are not supported.
- **Profiles and CLI:** Provider metadata is centralized. Configuration is validated
  and updated in cross-process transactions. `show` masks credentials, interactive
  secret input is hidden, and scripted `add`/`edit` supports `--secret-stdin`.
  New `doctor` and `configure` commands help diagnose local installations.
  `roll-claude-buddy` has been removed.
- **Upgrades:** `claudec upgrade` still updates every supported CLI by default,
  while positional tool selection and repeatable `--exclude` options control the
  selection. Antigravity uses Google's native installer; other CLIs use npm.
- **Router recovery:** Network failures use non-modal Windows system notifications.
  When both the network and unchanged blocking rules recover, the guardian removes
  only its own rules and dismisses the notification automatically. A crashed monitor
  or changed/unverifiable rules still require manual restoration.
- **CI and distribution:** Main-branch pushes and pull requests run cross-platform
  source tests. Release tags attach Windows, macOS and Linux installers directly to
  GitHub Releases with SHA-256 checksums.

Country checks still do not verify provider account eligibility, every split route,
DNS/WebRTC exits or IP reputation. See the
[router-mode guide](https://github.com/invoker-bot/Claude-China/blob/v0.5.0/docs/router-mode.md)
for automatic recovery conditions and remaining limits.

### Install and upgrade

- **Windows x64:** install `Claude-China-0.5.0-windows-x64-setup.exe`, or use
  **检查更新 → 下载更新 → 安装并重启** in v0.4.0 or newer.
- **macOS Apple Silicon / Intel:** download the matching DMG and replace the app in
  Applications manually. Ad-hoc signed packages are not eligible for in-app updates.
- **Linux x64:** install the matching `.deb` or `.rpm` package.
- **CLI:** `python -m pip install --upgrade claude-china` upgrades a separately
  installed CLI. Desktop installers bundle Python.

Windows setup installs Microsoft WebView2 Runtime if missing. Windows installers
remain unsigned and macOS packages remain ad-hoc signed and not notarized. Verify
downloads against `SHA256SUMS`. Uninstallation preserves profiles, settings and
credentials after restoring owned network protection.
