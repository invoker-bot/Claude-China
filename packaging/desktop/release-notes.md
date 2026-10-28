## Claude China 0.4.7

The environment check now uses a single independent Cloudflare country lookup
in router and TUN modes. It does not contact Claude or Anthropic for checks,
send chat messages, or perform separate STUN, UDP or DNS leak probes.

- **Router mode:** Managed launches check the country against the existing
  blocked-region list. On Windows, Claude runtime protection checks it about
  every 10 seconds and blocks registered executables if the country is blocked,
  or the result is unknown with strict mode enabled. The session remains open.
- **TUN mode:** The country check for a protected CLI or desktop app is bound
  to its selected tunnel. Existing WFP tunnel-only TCP/UDP protection remains
  active, and can be restored in Settings → Safety. TUN mode does not monitor
  the country continuously.
- **Safety screen:** The result is labeled as a region check and explicitly
  says browser WebRTC has not been tested. Local browser-policy settings remain
  available for inspection and previously recorded changes can be restored.

Country-only checks cannot detect every split route, an IP change within an
allowed country, a different IPv4/IPv6 or UDP exit, or the target browser's
actual WebRTC traffic. A router-mode failure is not detected instantly. With
strict mode disabled, an unknown country result alone does not trigger a block.
The protection covers registered executable paths, not all processes or system
DNS. Cloudflare sees the IP used for the request. See the
[router-mode guide](https://github.com/invoker-bot/Claude-China/blob/v0.4.7/docs/router-mode.md)
for setup, testing, and restoration.

### Install and upgrade

- **Windows x64:** install `Claude-China-0.4.7-windows-x64-setup.exe`, or use
  **检查更新 → 下载更新 → 安装并重启** in v0.4.0 or newer.
- **Linux x64:** install the `.deb` or `.rpm`. Claude router runtime protection
  remains Windows-only.
- **CLI:** `python -m pip install --upgrade claude-china` upgrades a separately
  installed CLI. Desktop installers bundle Python.

macOS builds remain development artifacts and are not included in this release.
Windows setup installs Microsoft WebView2 Runtime if missing. Windows signing
service enrollment is pending, so the installer is unsigned. Verify downloads
against `SHA256SUMS`. Uninstallation preserves profiles, settings and credentials
after restoring owned network protection.
