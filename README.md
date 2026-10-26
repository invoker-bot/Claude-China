# Claude China

Launch your AI coding apps, resume CLI sessions, and keep your project profiles
in one place.

`claude-china` gives each profile its own provider, endpoint, credentials,
proxy, and default arguments. The `claudec` command then starts Claude Code,
OpenAI Codex, or Grok using that profile.

Repository: [invoker-bot/Claude-China](https://github.com/invoker-bot/Claude-China)
· Desktop: [Download](https://github.com/invoker-bot/Claude-China/releases/latest)
· PyPI: [claude-china](https://pypi.org/project/claude-china/)
· CLI: `claudec`

![Claude China desktop: Claude, Codex and Grok Bot with launch controls and shared settings](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/desktop-apps.png)

**Your apps, one launcher.** Start Claude, Codex and Grok Bot with shared or
per-app environment settings, and check for launcher updates from the header.

## Features

- Manage multiple profiles from one command-line interface
- Support API-key and isolated login/credential profiles
- Configure a custom endpoint and proxy for each profile
- Forward arguments to the underlying AI CLI
- Set per-profile default arguments such as `--model`
- Upgrade the supported AI CLIs through npm
- Standalone Windows, macOS and Linux desktop launcher
- Desktop display languages: English, Simplified Chinese and Traditional Chinese
- Open project terminals and manage CLI profiles in the desktop app
- Search local CLI session history and resume a specific conversation
- Pin favorite project folders and start new sessions with the selected profile
- Inspect local token usage, tool calls, models, estimated API costs and daily trends
- Check the exit region and UDP route, and enable reversible Windows network protection while keeping WebRTC enabled

## Desktop tour

Screenshots use the English interface and sample data. Local statistics are
available in v0.4.3.

<details>
<summary><strong>Understand your usage — local statistics</strong></summary>

Compare token usage, active sessions and projects by day, application or model.
Explore Bash, Read, Write and MCP call counts, plus estimated API-equivalent
token costs with visible pricing sources and coverage.
Statistics are indexed locally in the background. Missing usage is clearly
marked, including Grok Bot's activity-only records. See the
[statistics guide](docs/desktop-statistics.md) for supported sources and limits.

![Local statistics: token usage, active sessions, projects and daily trends in English](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/usage-statistics.png)

</details>

<details>
<summary><strong>Pick up where you left off — searchable session history</strong></summary>

Find a previous Claude Code, Codex CLI or Grok CLI session by title, project path
or session ID, then continue it in the original project directory. History follows
the selected profile and includes sessions started outside the launcher.

![My terminals: search project history and resume a selected CLI session](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/terminal-history.png)

</details>

<details>
<summary><strong>Start something new — favorite project folders</strong></summary>

Keep frequently used folders within reach. Choose a CLI profile, start a fresh
session in a favorite project, or open its folder and terminal directly.

![My terminals: favorite project folders and new-session actions using a Codex CLI profile](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/favorite-projects.png)

</details>

<details>
<summary><strong>Set it once — proxy and environment settings</strong></summary>

Manage shared environment variables and per-app overrides in the Settings tab.
Optionally derive proxy variables from the system HTTP proxy and require launch
checks before opening an app.

![Settings: system proxy checks, automatic proxy environment variables and shared configuration](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/desktop-settings.png)

</details>

<details>
<summary><strong>Make it yours — display language</strong></summary>

Choose **Settings → General → Display language**, with English,
Simplified Chinese, Traditional Chinese and a system default. Language changes
apply immediately, including the tray and macOS application menu, and are saved
automatically without discarding unfinished settings. Available since v0.4.2.

![English desktop settings with display language selection](https://raw.githubusercontent.com/invoker-bot/Claude-China/main/docs/screenshots/desktop-language-en.png)

</details>

## Installation

Install the CLI from PyPI:

```bash
python -m pip install claude-china
```

For local development, install the checkout in editable mode:

```bash
python -m pip install -e .
```

Download the desktop app from
[GitHub Releases](https://github.com/invoker-bot/Claude-China/releases/latest).
It includes Python and the desktop dependencies; installing the CLI is optional.

v0.4.3 publishes Windows and Linux installers plus the CLI. macOS Intel and
Apple Silicon packages are currently build-validation artifacts in GitHub
Actions, not downloads attached to the v0.4.3 Release.

| Platform | Download | Install | Uninstall |
| --- | --- | --- | --- |
| Windows x64 | `*-windows-x64-setup.exe` | Run the installer | Settings → Apps → Installed apps → Claude China |
| macOS Apple Silicon | `*-macos-arm64.dmg` (Actions artifact) | Drag Claude China to Applications | Quit the app, then move it to Trash |
| macOS Intel | `*-macos-x64.dmg` (Actions artifact) | Drag Claude China to Applications | Quit the app, then move it to Trash |
| Debian / Ubuntu x64 | `*-linux-x64.deb` | Open with the software installer, or `sudo apt install ./<file>.deb` | Software manager, or `sudo apt remove claude-china-desktop` |
| Fedora x64 | `*-linux-x64.rpm` | Open with the software installer, or `sudo dnf install ./<file>.rpm` | Software manager, or `sudo dnf remove claude-china-desktop` |

In the desktop app, choose **检查更新** (Check for updates) in the top-right
corner, or **Claude China → 检查更新…** on macOS. The system tray
menu also has **检查更新…**. In Settings → **版本更新**, choose **下载更新** (Download),
then **安装并重启** (Install and restart). Returning to that page keeps the current
download or prepared update; switching pages does not cancel a download.
Checks are manual and use the latest
stable GitHub Release for your OS and architecture. Downloads show progress,
can be cancelled and must pass SHA-256 verification before installation.
Save or cancel any unsaved settings changes before restarting.
Windows/Linux integrate the titlebar into the page navigation, with minimize,
maximize/restore and close buttons, header dragging and edge resizing. Closing
still follows the platform's tray policy. There is no extra native window menu bar.
The tray also provides **设置…** (Settings), **发布页面** (Release page) and
**退出** (Quit). On macOS the standard application menu retains Settings,
Check for updates, About, Hide and Quit (Cmd+Q).

The display-language preference is stored as `language` in
`~/.claudec/desktop.yaml` (`system`, `en`, `zh-CN`, or `zh-TW`). System default
uses the operating system's display language when the launcher opens; unsupported
languages fall back to English. Changing it does not alter the system language,
timezone, region, launch environment, profile names, project paths or session
titles. It does not change the underlying AI apps' or CLIs' own language.

Settings → **安全检查** shows local timezone/language/region and checks the
current public-IP region before each app launch or restart. Unsupported regions
and, by default, unknown/failed checks block launching without stopping an
already running app. The settings include automatic-check and strict-mode
switches. **检查环境** runs the region check and an auxiliary STUN probe
together. On Windows, **启用网络防护** restricts the selected app to the pinned
HTTP proxy endpoint; **还原网络防护** removes its protection in one click.
Region eligibility does not guarantee account safety. See the
[environment check guide](docs/desktop-safety.md) for supported rules, network
privacy, limitations and maintenance.

Windows upgrades the registered installation; macOS replaces the installed app
after Developer ID/Gatekeeper verification; Linux requests system authorization
and upgrades through apt/dnf. macOS needs an Applications folder you can write
to; Linux needs `pkexec` and a desktop authentication agent. Development/unpacked
copies can check releases and open the download page but do not self-install.
Updating restarts only the launcher, leaving launched Claude/Codex/Grok Bot apps running.
Failures are shown in the launcher when it reopens.

You can also install a newer package over the existing installation.
Uninstalling preserves profiles and settings in `~/.claudec/`, legacy files in
`~/.code-ai/`, and your login credential directories.
The v0.3.0 release predates the update controls; install v0.4.0 or later manually once
to enable subsequent in-app updates on Windows and Linux.

CLI requirements:

- Python 3.9 or later
- At least one supported AI CLI installed and available on `PATH`
- Node.js and npm for `claudec upgrade`

Desktop requirements: Windows 10/11, macOS 12 or later, or a Linux desktop with
GTK 3 and WebKitGTK 4.1 (Ubuntu 22.04 or later; Fedora 40 or later). Windows
setup installs Microsoft's WebView2 Runtime if it is missing, which requires
internet access. Linux package managers resolve system GUI dependencies.
The launcher does not install Claude, Codex or Grok Bot themselves. On Linux,
Grok Bot's `grok-bot` desktop command is detected automatically; select an
installed executable in settings for other or portable desktop apps. Terminal
commands such as `claude`, `codex` and `grok` are not treated as desktop apps.

Windows signing service enrollment is pending; the v0.4.3 Windows installer is
unsigned. The macOS Actions artifacts are ad-hoc signed and not notarized.
Developer ID signing and Apple notarization can be enabled once credentials
are configured; see the
[signing setup guide](packaging/desktop/SIGNING.md). A valid Windows signature
does not guarantee that a new download has sufficient SmartScreen reputation.

### Upgrading from code-ai / AI Launcher

The 0.2 series renames the distribution from `ai-code-switcher` to `claude-china`,
the command from `code-ai` to `claudec`, and the desktop app to **Claude China**.
The Python module is now `claude_china` (`python -m claude_china.cli`).

For desktop use, quit the old launcher from its tray menu, remove the old
Python-based **AI Launcher** / **Claude China** desktop shortcut, and install
the native package from GitHub Releases. On macOS the old shortcut is an
AppleScript `.app` on the Desktop; the new app belongs in Applications.

For CLI use, run:

```bash
python -m pip install --upgrade claude-china
```

Configuration now lives in `~/.claudec/`. On first use, missing `config.yaml`
and `desktop.yaml` files are automatically imported from `~/.code-ai/`.
Existing files in the new directory take priority; files are never merged or
overwritten by this import. Old files remain as a backup and are not kept in
sync with subsequent changes. Login credential paths stay unchanged, so no
credentials need to be copied.

New icon and update caches also use `~/.claudec/`. Existing caches and active
update jobs stay in their original locations. On an existing installation,
the launcher also coordinates with the old instance lock to avoid opening
two windows across versions.
You can then remove the old distribution with `python -m pip uninstall ai-code-switcher`.

For existing scripts that still use `code-ai`, upgrade the compatibility package:

```bash
python -m pip install --upgrade ai-code-switcher
```

Starting with `ai-code-switcher` 0.1.24, the old package automatically installs
`claude-china`. Both `code-ai` and `python -m code_ai.cli` forward to the new
CLI and print a deprecation warning to stderr. Arguments, stdout and exit codes
are preserved. Switch scripts to `claudec` when convenient; removing the old
package afterwards leaves the new CLI installed. Internal Python imports should
use `claude_china`. Versions pinned below 0.1.24 retain the old implementation.
See the [compatibility package](https://github.com/invoker-bot/Claude-China/tree/main/compat/ai-code-switcher) for details.

## Quick start

Create a profile interactively, then launch it:

```bash
claudec add
claudec list
claudec show my-claude
claudec run my-claude
```

Arguments after the profile name are forwarded to the underlying CLI:

```bash
claudec run my-claude -p "Review this repository"
claudec run my-codex --model o3
claudec run my-grok --help
```

Useful commands:

```text
claudec list                         List configured profiles
claudec add                          Add a profile interactively
claudec show <profile>               Show profile details
claudec remove <profile>             Remove a profile
claudec upgrade                      Upgrade Claude, Codex, and Grok CLIs
claudec --version                    Show the installed version
claudec --help                       Show command help
```

The supported AI CLIs are:

- Claude Code: `@anthropic-ai/claude-code`
- OpenAI Codex: `@openai/codex`
- Grok: `@xai-official/grok`

`claudec upgrade` also refreshes the Grok binary in each login profile's
credentials directory. Grok stores a separate binary under `GROK_HOME/bin`, so
updating only the global npm package can leave a login profile running an old
version. The upgrade enables npm install scripts and verifies the actual binary
version in the default home and every login home; an unchanged or missing binary
causes the command to fail. Restart running Grok sessions after upgrading.

For Grok, `claudec run` prefers the official package in the active npm global
prefix, so an older native installation earlier on `PATH` cannot shadow the
package updated by `claudec upgrade`. Native installations remain supported
when the npm package is absent. Login credentials still use the profile's own
`GROK_HOME`.

## Profiles and configuration

Profiles are stored in `~/.claudec/config.yaml`. Use API mode when the profile
should provide a token or API key. Use login mode when the CLI should use an
isolated credentials directory.

Example configuration:

```yaml
profiles:
  claude-api:
    name: claude-api
    type: claude
    mode: api
    base_url: https://api.anthropic.com
    token: sk-ant-...
    default_args:
      - --model
      - claude-sonnet-4-5

  codex-login:
    name: codex-login
    type: codex
    mode: login
    credentials_path: ~/.codex-profiles/work
    proxy: http://127.0.0.1:7890

  grok-api:
    name: grok-api
    type: grok
    mode: api
    base_url: https://api.x.ai
    api_key: xai-...
```

Login profiles isolate credentials through the provider-specific environment
variables used by the CLIs. API profiles set the corresponding endpoint and
authentication variables for the selected provider.

Keep tokens and personal configuration out of source control.

### Default launch arguments

`default_args` can be a YAML list or a single string:

```yaml
profiles:
  claude-api:
    name: claude-api
    type: claude
    default_args: "--model claude-sonnet-4-5"
```

Profile defaults are appended after command-line arguments. This lets a
profile pin a value such as `--model` when the CLI uses the last occurrence of
a flag. Skip profile defaults for one launch with:

```bash
claudec run --no-default-args claude-api --model claude-opus-4-5
```

## Claude Buddy

Claude profiles can have a deterministic companion card generated from the
profile name:

```bash
claudec roll-claude-buddy claude-api
claudec roll-claude-buddy claude-api --name capybara
claudec roll-claude-buddy claude-api --type legendary
```

## Desktop launcher

The standalone desktop launcher provides a graphical interface for Claude,
Codex and [Grok Bot](https://cursor.com/download/bot) desktop apps.
Install it from GitHub Releases and open **Claude China**
from the Start Menu, Applications, or your Linux application menu.

```bash
claudec desktop download     # optional: print the Release download URL
```

`claudec desktop install` and `uninstall` are retired and display migration
instructions. The operating system owns installation, shortcuts and removal.

Only one launcher runs per user. Opening the app again restores and brings
the existing window forward. On Windows and macOS, closing the window hides it
in the system tray (the menu bar on macOS).
Click the tray icon or choose **打开 Claude China** to reopen the window;
choose **退出** from the tray menu to exit the launcher completely.
On Linux, closing the window exits the launcher, including on desktops without
a notification tray.

The launcher uses the terracotta **Claude China** mark for its window, shortcut,
tray and footer. The tray/menu-bar and footer marks briefly breathe and turn
when the launcher opens or an action runs, then return to rest. Shortcut and
window-title icons stay static. See the [icon preview](docs/branding/preview.html)
and [asset notes](docs/branding/README.md).

On Windows, the launcher and its shortcuts share a taskbar identity. Icon files
use a content-based filename so new artwork gets a fresh Shell cache entry.
The Windows installer updates the Start Menu shortcut and optional desktop
shortcut. Restart the launcher after upgrading to refresh the taskbar icon.

Desktop settings are stored separately in `~/.claudec/desktop.yaml`. The
launcher can check the system proxy and apply common or per-application
environment variables; per-application values take precedence.

In **设置 → 通用设置**, **自动添加代理环境变量** (off by default,
`auto_proxy_env` in the configuration) reads the current static HTTP proxy on
every launch and supplies both `HTTP_PROXY` and `HTTPS_PROXY`. Lowercase aliases
are kept in sync for clients that prefer them. Explicit common and then per-app
variables override these defaults. The derived address is not saved to disk or
written into the system environment.

Windows reads the enabled Internet Settings HTTP endpoint (including
`http=host:port;https=...` lists); macOS reads the global HTTP host/port from
`scutil --proxy`; Linux uses `http_proxy`/`HTTP_PROXY`, then GNOME's manual HTTP
proxy. HTTP URLs, host/port pairs and IPv6 are supported; a bare HTTP host uses
port 80. PAC-only, SOCKS-only, missing/invalid endpoints and unreadable settings
cancel the launch with an error **before stopping an already running app**.
This validation remains mandatory while auto-add is enabled, even if the
separate proxy-check switch is off or manual variables override the defaults.
GNOME proxies requiring authentication must instead be configured manually with
auto-add disabled.

Environment injection applies to directly launched processes. OS-brokered
activation (including Windows Codex MSIX activation, required for its package
context) may not forward custom variables to the application. The proxy
validation still runs before that activation.

### Environment check and WebRTC repair

**设置 → 安全检查 → 检查环境** runs both checks at once. It compares the HTTPS
exit (through the configured HTTP proxy) with the machine's UDP exit measured by
a STUN binding request, and checks the selected app's public-IP region against
the shared policy. It reports the proxy mode, Chrome/Edge policy state and the
IPv6 default route. The WebRTC result is a heuristic: it measures the local UDP
path, not a real browser session, and cannot replace an in-browser WebRTC test
such as browserleaks.com/webrtc. The STUN server necessarily sees the local UDP
exit IP. Browser-extension proxies, PAC/SOCKS proxies and split tunnels that
route only selected browser traffic may not be visible to this check.

On Windows, select an installed app and choose **启用网络防护**. After Windows
administrator authorization, WFP permits only TCP to the system HTTP proxy's
fixed IP and port (or localhost). All other outbound connections from the
covered EXEs are blocked, including UDP, IPv6 and direct TCP fallback. WebRTC
stays enabled; communication that cannot use the allowed proxy fails. The guard
does not change browser policies, system proxy settings or global firewall rules.

The guard covers EXEs in the selected installation, including bundled helpers,
for the current Windows user. Its persistent filters and restore metadata are
stored together in WFP; the launcher records enabled intent in
`~/.claudec/desktop.yaml`. Closing the launcher or disconnecting the proxy does
not remove protection. Each protected launch verifies the real filters, binary
paths and proxy endpoint even when region checks are disabled. Changes require
**重新应用网络防护**; an unverified protected launch is cancelled. Proxy environment
variables are pinned and bypass variables removed for protected launches.

**还原网络防护** works without the proxy or target app being available, removes
only this app's owned filters and preserves other apps' protection. Windows
uninstallation cleans up owned network protection before deleting the launcher;
failed cleanup stops uninstallation. Guard buttons act immediately, independently
of the settings Save/Cancel buttons. Previously recorded browser-policy repairs
remain restorable through **还原浏览器策略**; new protection never writes them.

This implementation supports Windows with static HTTP proxy IPs/localhost.
PAC, hostname-based proxy endpoints, SOCKS-only and TUN-only configurations are
not silently treated as protected. Shared runtimes and tools outside the app
installation, delegated system-service DNS queries, and disclosure of local
adapter addresses through browser APIs are outside its scope. Updates to a new
installation path require reapplying protection before using that path; launching
such a new path outside the launcher is not covered by old executable filters.
Only use a dedicated app installation directory, not a shared runtime directory.

The manual STUN request still tests the launcher itself, not a protected target
process. Its raw UDP exit can differ from the proxy even while the target's
direct traffic is correctly blocked. See [the native acceptance probe](tools/windows_network_guard_probe.py)
for isolated TCP/UDP, IPv4/IPv6, offline fallback, rollback and restore checks.

The home window presents application cards with status, launch/restart and stop
controls. **设置** is a main navigation tab alongside **我的应用** and **我的终端**,
with categories for common settings, safety, each application, updates and About.
Switching tabs or categories keeps unsaved drafts in memory, and returning to
Settings restores the last category. **保存设置** applies the current category;
**取消修改** restores its saved values while staying on the page. Application paths
also take effect only after saving, and can be reset to automatic detection. Use the refresh button
to detect newly installed applications. Smaller windows use a scrolling layout
without resizing as fields are added.

Grok Bot has its own launch/restart, stop and settings controls, stored under
`apps.grok-bot`. On Windows, detection checks its registered installation and
`%LOCALAPPDATA%\Programs\Grok Bot\Grok Bot.exe`. On macOS, it finds `Grok Bot.app`
through Spotlight or the Applications folders and launches the bundle executable
directly to pass environment variables. On Linux, it resolves the installed
`grok-bot` desktop command. All platforms also accept a manually selected path.
Grok Bot desktop controls do not manage the separate Grok CLI or its profiles.

### My Terminals

**我的终端**, next to **我的应用**, manages Claude Code, Codex CLI and Grok CLI
profiles in the same `~/.claudec/config.yaml` used by `claudec`. Search or filter
profiles, create API or login profiles, edit/rename, copy and delete them.
Editing leaves an existing key unchanged when the key field is blank; explicitly
clear it to remove it. Stored keys are not returned to the page. Deleting a
profile keeps its project files and login directory. Refresh to load external
CLI edits; an outdated edit/delete is rejected instead of overwriting changes.

Choose a project directory, reopen a recent directory, open it in the system
file manager, or open an ordinary terminal. **启动终端** on a profile starts that
CLI in the selected directory with the saved arguments and environment. The
CLI must already be installed and visible on `PATH`. API/login settings and a
profile's explicit proxy take precedence; automatic system proxy validation and
the desktop safety rules also apply. An invalid proxy or failed strict safety
check prevents the CLI from starting. Ordinary terminals do not apply a profile.

**历史会话** reads the selected profile's local Claude Code, Codex CLI or Grok
CLI history, including sessions started outside the launcher. Search by title
or project and choose **继续会话** to resume the exact conversation. **常用项目**
keeps starred and recent directories ready for **新建会话** with the selected
profile. Missing directories are shown but cannot be launched. Resume repeats
the same environment checks and injection as a new session.

Windows uses PowerShell, macOS uses Terminal (automation permission may be
required), and Linux uses an installed terminal such as GNOME Terminal, Konsole
or xterm. The shell remains open after the CLI exits. The selected profile is
read and checked again inside the new terminal, so credentials never need to be
written into shell history or temporary launch scripts. Profile variables apply
to that CLI process, not to later commands typed into the remaining shell.
See [terminal behavior and validation](docs/desktop-terminals.md).

## Development

Run the test suite and build the distribution locally with:

```bash
python -m pytest tests/ -q
python -m build
```

To run the desktop UI from source:

```bash
python -m pip install -e ".[desktop]"
claudec desktop run
```

Linux source development also needs PyGObject, GTK 3 and WebKitGTK 4.1. Native
installer builds and release validation are documented in
[packaging/desktop/README.md](packaging/desktop/README.md). Pushing a `v*` tag
builds the desktop packages for GitHub Releases and independently publishes
the CLI distribution to PyPI.

Ordinary branch pushes and pull request updates do not run GitHub Actions.
Release tags trigger automatic validation and publishing; manual validation and
optional dependency-cache warming remain available. See [CI and dependency
caches](docs/ci.md).

## License

[MIT](LICENSE)
