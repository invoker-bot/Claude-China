## Claude China 0.4.4

This release adds opt-in Windows network protection for desktop apps and local
Playwright browsers while keeping WebRTC available.

### What's new

- **TUN protection:** select a connected tunnel in Settings → Safety. Covered
  applications can use TCP and UDP through that interface; direct fallback is
  blocked if the tunnel disconnects or the route changes. Your proxy client
  manages routing and DNS. Configure it to send the target traffic, including
  UDP, through the intended proxy; TUN mode alone does not change its rules.
- **Playwright protection:** select CLI / Playwright as the target. Standard
  browser caches are discovered, and custom browser EXE paths can be added.
  `claudec` and terminals opened by the desktop launcher check browsers before
  starting them. Reapply protection after installing a new browser version.
- **Fixed HTTP proxy protection:** alternatively restrict a desktop app to a
  configured HTTP proxy, including blocking outbound UDP and direct fallback.
  This mode preserves WebRTC but connections requiring UDP will fail.
- **One-click restore:** remove the selected target's protection even if its
  proxy, tunnel or application is unavailable. Rules persist until restored.

Windows requests administrator authorization when applying or restoring
protection. The tunnel source-address guard also affects other processes using
those addresses, and browser APIs may still expose local interface addresses.
External launchers need to integrate the Playwright launch check; remote and
WSL/container browsers are outside these Windows rules. Restart existing
CLI/browser processes after changing or restoring modes. See the
[network protection guide](https://github.com/invoker-bot/Claude-China/blob/v0.4.4/docs/desktop-safety.md)
for setup and scope.

### Install and upgrade

- **Windows x64:** use `*-windows-x64-setup.exe`, or choose **检查更新 → 下载更新 → 安装并重启** in an existing v0.4.0 or newer desktop app.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your software manager. The new network protection is Windows-only.
- **CLI:** `python -m pip install --upgrade claude-china` updates a separately installed CLI. The desktop installers include Python and do not require the CLI package.

macOS Intel and Apple Silicon builds are validated in GitHub Actions and remain
available there as development artifacts; this release does not include DMGs.
Windows setup installs Microsoft WebView2 Runtime if missing (internet required).
Windows signing service enrollment is pending; the installer is unsigned and
may show trust warnings. Verify downloads against `SHA256SUMS`. See the
[signing status](https://github.com/invoker-bot/Claude-China/blob/main/packaging/desktop/SIGNING.md).

Save or cancel unsaved settings before updating. From v0.3.0, install the new
version manually once because that version predates in-app updates. Uninstalling
preserves configuration and credentials.
