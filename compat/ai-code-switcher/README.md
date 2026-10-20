# ai-code-switcher has moved to Claude China

**已更名：`ai-code-switcher` 已弃用，请安装 [`claude-china`](https://pypi.org/project/claude-china/)，并使用 `claudec` 命令。**

**Deprecated:** this package is a compatibility bridge to
[`claude-china`](https://pypi.org/project/claude-china/). New features and fixes
are released under the new name.

## Recommended installation

```bash
python -m pip install --upgrade claude-china
claudec --help
```

For the Windows or macOS desktop launcher, quit the old launcher from its tray
menu first, then run:

```bash
python -m pip install --upgrade "claude-china[desktop]"
claudec desktop install
claudec desktop run
```

The desktop app is now named **Claude China**. Profiles, credentials and desktop
settings continue to use `~/.code-ai/`; no manual migration is needed.

## Compatibility for existing users

Starting with version **0.1.24**, installing `ai-code-switcher` automatically
installs `claude-china` as a dependency. The `desktop` extra forwards to
`claude-china[desktop]`.

```bash
python -m pip install --upgrade ai-code-switcher
# Desktop users:
python -m pip install --upgrade "ai-code-switcher[desktop]"
```

The old `code-ai` command and `python -m code_ai.cli` entry point continue to
work, forwarding to the new CLI. They print a deprecation warning to stderr;
arguments, stdout and exit codes are preserved. Existing desktop shortcuts
using the old module can still launch the app; reinstalling shortcuts with
`claudec desktop install` updates their name and icon.

The compatibility package does not preserve other internal `code_ai` Python
APIs. Update Python imports to `claude_china`.

After updating commands, scripts and shortcuts, the bridge can be removed:

```bash
python -m pip uninstall ai-code-switcher
```

This leaves `claude-china` and `claudec` installed. Versions pinned below
0.1.24 retain the old implementation and do not receive this migration.

Source and documentation:
[invoker-bot/Claude-China](https://github.com/invoker-bot/Claude-China).
