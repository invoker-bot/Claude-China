# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`claude-china` (CLI: `claudec`) is a Typer-based wrapper that selects an AI coding-tool profile and execs the matching upstream CLI (`claude`, `codex`, or `gemini`) with the right environment. Configuration lives in `~/.code-ai/config.yaml`. Distribution name is `claude-china`; the Python package is `claude_china`.

## Commands

```bash
# Install for development
pip install -e .

# Run all tests (configured via [tool.pytest.ini_options] in pyproject.toml)
python -m pytest tests/ -q

# Run a single test
python -m pytest tests/test_launcher.py::test_merge_launch_args_only_defaults -q

# Run the CLI from source (NOT from the globally-installed package)
PYTHONPATH=src python -m claude_china.cli <subcommand>
```

There is no linter or formatter configured; do not invent one.

## Source-vs-installed gotcha

The package is commonly installed globally (`pip install -e .` or via release). Running `python -m claude_china.cli` or `claudec` after editing source may execute the **installed** copy, not your edits. Tests use `from src.claude_china.X import Y` (note the `src.` prefix) so they always hit the working tree. For manual CLI smoke-tests of in-progress changes, prefix with `PYTHONPATH=src`.

## Architecture

The flow for `claudec run <profile> [extra_args...]`:

1. **`cli.py`** (`run_command`) — Typer entry point. Uses `ignore_unknown_options=True` + `allow_extra_args=True` so unknown flags fall through into `ctx.args` and get forwarded to the underlying CLI verbatim. Declared options like `--no-default-args` are still parsed normally and do **not** leak into `ctx.args`.
2. **`config.py`** loads `~/.code-ai/config.yaml`. `load_config` auto-migrates legacy profiles (back-fills missing `name`/`mode` fields and re-saves).
3. **`models.py`** — `profile_from_dict` dispatches the raw dict to either `ApiProfile` or `LoginProfile` based on `type` + `mode`. `BaseProfile` holds shared fields (`name`, `type`, `proxy`, `default_args`).
4. **`launcher.py`** — `prepare_environment` first **clears** every var in `MANAGED_ENV_VARS` from the inherited environment, then sets only what the active profile needs. This prevents stale `ANTHROPIC_*` / `OPENAI_*` / `CLAUDE_CONFIG_DIR` / proxy settings from a parent shell from leaking into the child CLI. `merge_launch_args(extra_args, profile.default_args, use_default_args)` produces the final argv: command-line args first, profile defaults appended last (so defaults win for last-occurrence-wins flags like `--model`).
5. Spawn: on Windows uses `subprocess.run` (so npm-installed `.cmd` shims resolve correctly via `shutil.which(f"{cmd}.cmd")`); on Unix uses `os.execvp`.

### `ENV_MAP` is the contract

`launcher.py:ENV_MAP` is the single source of truth for: which env vars each `type` maps to (claude→`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`, codex→`OPENAI_*`, gemini→`GOOGLE_GEMINI_BASE_URL`/`GEMINI_API_KEY`) and which underlying executable to spawn. `MANAGED_ENV_VARS` is derived from it plus `CONFIG_DIR_ENV_VARS` (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) and the four proxy vars. **When adding a new env var, add it to one of these tables** — otherwise `clear_managed_environment` won't clean it up between runs and you get cross-profile bleed.

### Login vs API mode

- **API mode** (`ApiProfile`): sets the type's env vars (`base_url` → `ANTHROPIC_BASE_URL`, etc.) directly.
- **Login mode** (`LoginProfile`, claude/codex only): sets `CLAUDE_CONFIG_DIR` or `CODEX_HOME` to a per-profile credentials directory, so the underlying CLI uses an isolated OAuth state. For codex specifically, `prepare_environment` writes a minimal `config.toml` (`model_provider = "openai"`) into the credentials dir if missing — this prevents codex from inheriting custom providers from the user's global `~/.codex/config.toml`.

### Adding a profile field

If you add a field to `BaseProfile`, you must:
1. Update `profile_from_dict` to read it from the dict (it does **not** auto-pick up new fields).
2. Add it to interactive `add_profile` in `profiles.py` if it should be promptable.
3. `profile_to_dict` uses `asdict()` and strips `None`s, so round-tripping works automatically as long as the default is `None`.

## `buddy.py` — special invariants

`buddy.py` is a **bit-exact port of the JS buddy generator** in upstream Claude Code (`mulberry32`, `hash_string` FNV-1a, `_imul`, `_i32`, `_u32`). The signed/unsigned 32-bit dance is intentional: it reproduces JS's `|0`, `>>>`, `Math.imul` semantics so a given seed produces the same buddy in both runtimes. Do not "simplify" the integer ops — that breaks compatibility with Claude Code's own buddy display.

`bruteforce_user_id` writes the resulting userID to `<config_dir>/.claude.json` and **strips `oauthAccount.accountUuid`** so Claude Code falls back to `userID` for buddy seeding (otherwise the rolled buddy never appears).

## Test layout

- `test_models.py` — dataclass round-tripping, `profile_from_dict` dispatch, `default_args` parsing
- `test_launcher.py` — `prepare_environment` (env var setting/clearing), `resolve_default_args`, `merge_launch_args`
- `test_integration.py` — end-to-end profile lifecycle (`add_profile` → save → load → `prepare_environment`); mocks `builtins.input` with `side_effect=[...]`. **When adding a prompt to `add_profile`, every existing inputs list in `test_integration.py` must grow by one entry** or those tests start raising `StopIteration`.
