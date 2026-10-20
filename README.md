# Claude China

Switch between profiles for AI coding tools and launch the right CLI with the
right environment.

`claude-china` gives each profile its own provider, endpoint, credentials,
proxy, and default arguments. The `claudec` command then starts Claude Code,
OpenAI Codex, or Grok using that profile.

Repository: [invoker-bot/Claude-China](https://github.com/invoker-bot/Claude-China)
· PyPI: [claude-china](https://pypi.org/project/claude-china/)
· CLI: `claudec`

## Features

- Manage multiple profiles from one command-line interface
- Support API-key and isolated login/credential profiles
- Configure a custom endpoint and proxy for each profile
- Forward arguments to the underlying AI CLI
- Set per-profile default arguments such as `--model`
- Upgrade the supported AI CLIs through npm
- Standalone Windows, macOS and Linux desktop launcher

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

| Platform | Download | Install | Uninstall |
| --- | --- | --- | --- |
| Windows x64 | `*-windows-x64-setup.exe` | Run the installer | Settings → Apps → Installed apps → Claude China |
| macOS Apple Silicon | `*-macos-arm64.dmg` | Drag Claude China to Applications | Quit the app, then move it to Trash |
| macOS Intel | `*-macos-x64.dmg` | Drag Claude China to Applications | Quit the app, then move it to Trash |
| Debian / Ubuntu x64 | `*-linux-x64.deb` | Open with the software installer, or `sudo apt install ./<file>.deb` | Software manager, or `sudo apt remove claude-china-desktop` |
| Fedora x64 | `*-linux-x64.rpm` | Open with the software installer, or `sudo dnf install ./<file>.rpm` | Software manager, or `sudo dnf remove claude-china-desktop` |

In the desktop app, choose **帮助 → 检查更新…** (Help → Check for updates)
on Windows/Linux, or **Claude China → 检查更新…** on macOS. The system tray
menu also has **检查更新…**. In the update dialog, choose **下载更新** (Download),
then **安装并重启** (Install and restart). Reopening the dialog keeps the current
download or prepared update; closing it does not cancel a download.
Checks are manual and use the latest
stable GitHub Release for your OS and architecture. Downloads show progress,
can be cancelled and must pass SHA-256 verification before installation.
Save or cancel any open settings editor before restarting.
The native application menu and tray also provide **设置…** (Settings),
**发布页面** (Release page) and **退出** (Quit). On macOS the standard
application menu retains About, Hide and Quit (Cmd+Q).

Windows upgrades the registered installation; macOS replaces the installed app
after Developer ID/Gatekeeper verification; Linux requests system authorization
and upgrades through apt/dnf. macOS needs an Applications folder you can write
to; Linux needs `pkexec` and a desktop authentication agent. Development/unpacked
copies can check releases and open the download page but do not self-install.
Updating restarts only the launcher, leaving launched Claude/Codex apps running.
Failures are shown in the launcher when it reopens.

You can also install a newer package over the existing installation.
Uninstalling preserves profiles, credentials and settings in `~/.code-ai/`.
The existing v0.3.0 release predates the update controls; install the first
release containing this feature manually once.

CLI requirements:

- Python 3.9 or later
- At least one supported AI CLI installed and available on `PATH`
- Node.js and npm for `claudec upgrade`

Desktop requirements: Windows 10/11, macOS 12 or later, or a Linux desktop with
GTK 3 and WebKitGTK 4.1 (Ubuntu 22.04 or later; Fedora 40 or later). Windows
setup installs Microsoft's WebView2 Runtime if it is missing, which requires
internet access. Linux package managers resolve system GUI dependencies.
The launcher does not install Claude or Codex themselves. On Linux, select an
installed desktop application's executable in its settings; terminal commands
on `PATH` are not treated as desktop apps.

The v0.3.0 installers have no verified publisher signature. Windows signing
service enrollment is pending. Future macOS release builds require Developer ID
signing and Apple notarization; see the
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

Existing profiles, login directories, desktop settings and the single-instance
lock continue to use `~/.code-ai/`; no credentials need to be copied.
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

Profiles are stored in `~/.code-ai/config.yaml`. Use API mode when the profile
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

The standalone desktop launcher provides a graphical interface for Claude and
Codex desktop apps. Install it from GitHub Releases and open **Claude China**
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

Desktop settings are stored separately in `~/.code-ai/desktop.yaml`. The
launcher can check the system proxy and apply common or per-application
environment variables; per-application values take precedence.

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

## License

[MIT](LICENSE)
