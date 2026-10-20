# ai-code-switcher

Switch between profiles for AI coding tools and launch the right CLI with the
right environment.

`ai-code-switcher` gives each profile its own provider, endpoint, credentials,
proxy, and default arguments. The `code-ai` command then starts Claude Code,
OpenAI Codex, or Grok using that profile.

## Features

- Manage multiple profiles from one command-line interface
- Support API-key and isolated login/credential profiles
- Configure a custom endpoint and proxy for each profile
- Forward arguments to the underlying AI CLI
- Set per-profile default arguments such as `--model`
- Upgrade the supported AI CLIs through npm
- Optional Windows and macOS desktop launcher

## Installation

Install the CLI from PyPI:

```bash
python -m pip install ai-code-switcher
```

For local development, install the checkout in editable mode:

```bash
python -m pip install -e .
```

The optional desktop launcher is installed with:

```bash
python -m pip install "ai-code-switcher[desktop]"
```

Requirements:

- Python 3.9 or later
- At least one supported AI CLI installed and available on `PATH`
- Node.js and npm for `code-ai upgrade`
- Windows or macOS for the optional desktop launcher

## Quick start

Create a profile interactively, then launch it:

```bash
code-ai add
code-ai list
code-ai show my-claude
code-ai run my-claude
```

Arguments after the profile name are forwarded to the underlying CLI:

```bash
code-ai run my-claude -p "Review this repository"
code-ai run my-codex --model o3
code-ai run my-grok --help
```

Useful commands:

```text
code-ai list                         List configured profiles
code-ai add                          Add a profile interactively
code-ai show <profile>               Show profile details
code-ai remove <profile>             Remove a profile
code-ai upgrade                      Upgrade Claude, Codex, and Grok CLIs
code-ai --version                    Show the installed version
code-ai --help                       Show command help
```

The supported AI CLIs are:

- Claude Code: `@anthropic-ai/claude-code`
- OpenAI Codex: `@openai/codex`
- Grok: `@xai-official/grok`

`code-ai upgrade` also refreshes the Grok binary in each login profile's
credentials directory. Grok stores a separate binary under `GROK_HOME/bin`, so
updating only the global npm package can leave a login profile running an old
version. The upgrade enables npm install scripts and verifies the actual binary
version in the default home and every login home; an unchanged or missing binary
causes the command to fail. Restart running Grok sessions after upgrading.

For Grok, `code-ai run` prefers the official package in the active npm global
prefix, so an older native installation earlier on `PATH` cannot shadow the
package updated by `code-ai upgrade`. Native installations remain supported
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
code-ai run --no-default-args claude-api --model claude-opus-4-5
```

## Claude Buddy

Claude profiles can have a deterministic companion card generated from the
profile name:

```bash
code-ai roll-claude-buddy claude-api
code-ai roll-claude-buddy claude-api --name capybara
code-ai roll-claude-buddy claude-api --type legendary
```

## Desktop launcher

The optional desktop launcher provides a graphical interface for detected
Claude and Codex desktop apps. It is supported on Windows and macOS.

```bash
python -m pip install "ai-code-switcher[desktop]"
code-ai desktop install       # create or recreate the shortcut
code-ai desktop run           # open the launcher
code-ai desktop uninstall     # remove the shortcut
```

Only one launcher runs per user. Opening the shortcut or running
`code-ai desktop run` again restores and brings the existing window forward.
Closing the window hides it in the system tray (the menu bar on macOS).
Click the tray icon or choose **打开 AI Launcher** to reopen the window;
choose **退出** from the tray menu to exit the launcher completely.

The launcher uses the terracotta **Anti-Claude** mark for its window, shortcut,
tray and footer. The tray/menu-bar and footer marks briefly breathe and turn
when the launcher opens or an action runs, then return to rest. Shortcut and
window-title icons stay static. See the [icon preview](docs/branding/preview.html)
and [asset notes](docs/branding/README.md).

Desktop settings are stored separately in `~/.code-ai/desktop.yaml`. The
launcher can check the system proxy and apply common or per-application
environment variables; per-application values take precedence.

## Development

Run the test suite and build the distribution locally with:

```bash
python -m pytest tests/ -q
python -m build
```

## License

MIT
