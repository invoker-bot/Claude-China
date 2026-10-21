# Repository Guidelines

## Project Structure & Module Organization

This is a `src`-layout Python package. Core CLI and profile logic lives in `src/claude_china/`, with `cli.py` as the Typer entry point, `config.py` for `~/.claudec/config.yaml`, `config_paths.py` for shared paths and one-time imports from `~/.code-ai/`, `models.py` for profile dataclasses, and `launcher.py` for environment setup and process launch. Desktop launcher code is under `src/claude_china/desktop/`; static desktop UI assets are in `src/claude_china/desktop/ui/` and are packaged via `pyproject.toml`. Tests live in `tests/`, and design notes/plans live in `docs/superpowers/`.

The deprecated `ai-code-switcher` distribution is built separately from `compat/ai-code-switcher/`. It only provides the old CLI/module bridge and depends on `claude-china`; do not copy application code into it. Tags `legacy-v<version>` run its cross-platform upgrade checks and publish that package, while `v<version>` tags publish the main distribution.

## Build, Test, and Development Commands

- `pip install -e .` installs the package in editable mode for local CLI development.
- `pip install -e ".[test]"` installs the package and non-GUI test dependencies.
- `pip install -e ".[desktop]"` installs optional desktop launcher dependencies.
- `python -m pytest tests/ -q` runs the full pytest suite configured in `pyproject.toml`.
- `python -m pytest tests/test_launcher.py::test_merge_launch_args_only_defaults -q` runs one targeted test.
- `PYTHONPATH=src python -m claude_china.cli <subcommand>` smoke-tests the working tree version. Use this form when checking uncommitted source changes.
- `python -m build compat/ai-code-switcher` builds the legacy bridge; `python tests/legacy_install_smoke.py <wheel-path>` verifies upgrading the old PyPI release in an isolated environment (requires network access).

## Coding Style & Naming Conventions

Use Python 3.9-compatible code, 4-space indentation, and clear dataclass-style models where they match existing patterns. Keep modules focused: CLI parsing in `cli.py`, persistence in `config.py`, profile prompting in `profiles.py`, and launch behavior in `launcher.py`. Test files follow `test_*.py`; test names should describe behavior, for example `test_prepare_environment_clears_managed_vars`. There is no configured formatter or linter, so do not introduce formatting-only churn.

## Testing Guidelines

The project uses pytest. Add or update tests whenever behavior changes in profile serialization, CLI argument forwarding, environment variable handling, or desktop platform behavior. Existing integration tests mock `builtins.input`; if adding a prompt to `add_profile`, extend each affected input list to avoid `StopIteration`. Prefer targeted tests for small changes, then run `python -m pytest tests/ -q` before submitting.

## Commit & Pull Request Guidelines

Recent commits use concise conventional-style messages such as `fix(desktop): ...`, `chore: ...`, and `release: v...`. Follow that pattern with an imperative, scoped summary. Pull requests should include a short behavior summary, linked issue when applicable, test commands run, and platform notes for desktop changes. Include screenshots or screen recordings for visible UI changes in `src/claude_china/desktop/ui/`.

## Security & Configuration Tips

Do not commit real tokens, profile configs, or generated user settings from `~/.claudec/` or legacy `~/.code-ai/`. `launcher.py` deliberately clears managed environment variables before setting profile-specific values; when adding new provider env vars, update the central env-var tables so cross-profile leakage stays covered by tests.
