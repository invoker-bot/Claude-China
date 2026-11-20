## Claude China 0.6.1

This release adds Google Antigravity, official missing-app installation, stronger
profile and upgrade management, and automatic router-mode recovery.

- **Antigravity:** Launch the Antigravity desktop app on Windows, macOS and Linux.
  Manage native `agy` CLI profiles with Gemini API keys, custom compatible endpoints,
  proxies and argument forwarding. The provider ID is `antigravity`; existing
  `antigravity-cli` records migrate automatically. Google account-token extraction,
  account rotation, Antigravity history and usage statistics are not supported.
- **Official app installation:** Missing desktop apps can be installed from their
  cards. Claude China selects current official packages for the OS and architecture,
  shows progress and supports cancellation. Store, direct installer, Linux package
  and archive flows remain distinct. Download hosts are allowlisted, and Windows
  installers require valid Authenticode signatures with expected publishers.
- **Profiles and CLI:** Provider metadata is centralized. Configuration is validated
  and updated in cross-process transactions. `show` masks credentials, interactive
  secret input is hidden, and scripted `add`/`edit` supports `--secret-stdin`.
  New `doctor` and `configure` commands help diagnose local installations.
  `roll-claude-buddy` has been removed.
- **Upgrade integrity:** `claudec upgrade` updates every supported CLI by default,
  with positional selection and repeatable `--exclude`. npm-backed tools check for
  running processes before installation, then compare package metadata, actual
  executable versions and PATH resolution. Missing native platform packages and
  stale binaries are reported by `doctor --versions`. Antigravity uses Google's
  native installer rather than npm. On npm 11 and newer, install scripts are
  explicitly permitted only for the selected npm packages.
- **Router recovery:** Network failures use non-modal Windows system notifications.
  When both the network and unchanged blocking rules recover, the guardian removes
  only its own rules automatically. A later managed launch also recovers an inactive
  blocked guard after an allowed region check. Unknown checks continue to follow
  strict mode and never authorize automatic recovery.
- **CI and distribution:** Main-branch pushes and pull requests run cross-platform
  source tests. Python 3.9 jobs remain on Ubuntu 22.04. Release tags attach Windows,
  macOS and Linux installers directly to GitHub Releases with SHA-256 checksums.

Country checks still do not verify provider account eligibility, every split route,
DNS/WebRTC exits or IP reputation. See the
[router-mode guide](https://github.com/invoker-bot/Claude-China/blob/v0.6.1/docs/router-mode.md)
for automatic recovery conditions and remaining limits.

### Install and upgrade

- **Windows x64:** install `Claude-China-0.6.1-windows-x64-setup.exe`, or use
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
