## Claude China 0.4.6

This release adds router-mode checks and Windows runtime network protection for
managed Claude sessions, while keeping WebRTC enabled. It also extends TUN
protection to managed CLI traffic and makes manual Claude Code login the default.

### What's new

- **Router mode:** start with a router-managed network and no local HTTP proxy.
  Launch checks compare service HTTPS and auxiliary STUN UDP exits, apply the
  configured region rule and report a single advisory DNS sample.
- **Claude runtime protection on Windows:** managed Claude desktop and Claude
  Code launches request administrator authorization and monitor the route.
  When a check fails, registered Claude and local Playwright executables are
  blocked while windows and sessions stay open. The guard can be restored in
  Settings → Safety. Codex and Grok receive startup checks only.
- **CLI and Playwright through TUN:** opt in to protecting managed CLI network
  traffic as well as discovered local Playwright browsers. Protected TUN
  launches bypass HTTP proxy environment variables and reject an unavailable
  or changed selected tunnel.
- **Claude Code login:** login profiles default to showing the URL for the user
  to open manually; automatic browser opening remains an explicit option.

Before switching to router mode, stop affected sessions and restore existing
network guards for the target, then disable the system HTTP/PAC proxy. Windows
runtime protection requires administrator authorization for the same Windows
account as the launcher. See the [路由器模式配置与测试教程](https://github.com/invoker-bot/Claude-China/blob/v0.4.6/docs/router-mode.md)
for setup, a controlled failure test, and recovery.

Checks are periodic: a failure can leak traffic before it is detected, and
unknown results only block when strict mode is enabled. Launcher-side STUN is
not proof of a browser's actual WebRTC exit or IP reputation. Rules cover
registered EXE paths for the current user, not arbitrary subprocesses, system
DNS, remote browsers or external launchers; other instances of a registered EXE
are affected too. Local TCP control remains available. Restore removes the
guard, so fix the route before allowing an existing session to reconnect.

### Install and upgrade

- **Windows x64:** use `Claude-China-0.4.6-windows-x64-setup.exe`, or choose
  **检查更新 → 下载更新 → 安装并重启** in v0.4.0 or newer.
- **Linux x64:** install the `.deb` with apt or the `.rpm` with dnf / your
  software manager. Claude router runtime protection is Windows-only.
- **CLI:** `python -m pip install --upgrade claude-china` upgrades a separately
  installed CLI. Desktop installers include Python and do not require it.

macOS Intel and Apple Silicon builds are validated in GitHub Actions and remain
development artifacts; this release does not include DMGs. Windows setup installs
Microsoft WebView2 Runtime if missing (internet required). Windows signing
service enrollment is pending, so the installer is unsigned and may show trust
warnings. Verify downloads against `SHA256SUMS`. Uninstalling preserves profiles,
settings and credentials after restoring owned network protection.
