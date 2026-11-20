import os
import sys
import subprocess
from typing import Optional, List

import typer

from .config import load_config, transaction
from .profiles import (
    list_profiles, add_profile, remove_profile, show_profile,
    create_profile_data, update_profile_data,
)
from .launcher import launch
from .grok import find_npm_installation, home_binary, check_version as check_grok_version
from .providers import PROVIDERS, get_provider
from . import __version__

app = typer.Typer(
    help="Claude China: switch AI coding profiles and launch CLI or desktop apps",
    add_completion=False,
)


@app.command(name="list")
def list_command():
    """List all profiles"""
    config = load_config()
    list_profiles(config)


@app.command(name="show")
def show_command(
    name: str = typer.Argument(..., help="Profile name to show"),
    reveal: bool = typer.Option(False, "--reveal", help="Reveal credentials in terminal output"),
):
    """Show profile details with credentials masked by default"""
    config = load_config()
    show_profile(config, name, reveal=reveal)


def _secret_from_stdin():
    secret = sys.stdin.read().strip()
    if "\n" in secret or "\r" in secret:
        raise ValueError("Secret input must contain exactly one line")
    if not secret:
        raise ValueError("No secret was provided on standard input")
    return secret


def _configure_provider(provider):
    if provider.settings_provider == "gemini":
        from .antigravity import configure_gemini_api
        return configure_gemini_api()
    return None


@app.command(name="doctor")
def doctor_command(
    profile: Optional[str] = typer.Argument(None, help="Check only this profile"),
    versions: bool = typer.Option(False, "--versions", help="Execute each installed CLI with --version"),
):
    """Validate local profiles and CLI installations without network requests"""
    from .diagnostics import collect
    try:
        report = collect(profile, versions)
    except (OSError, ValueError) as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None
    for tool in report["tools"]:
        state = "installed" if tool["installed"] else "not installed"
        detail = tool["version"] or tool["path"] or "not required by a profile"
        if tool.get("package_version"):
            detail += " · npm " + tool["package_version"]
        typer.echo(f"{tool['display']}: {state} · {detail}")
        if tool.get("warning"):
            typer.echo(f"  WARNING: {tool['warning']}")
        if tool["error"]:
            typer.echo(f"  ERROR: {tool['error']}", err=True)
    for item in report["profiles"]:
        state = "OK" if item["ok"] else "ERROR"
        typer.echo(f"Profile '{item['name']}' ({item['type']}): {state}")
        for warning in item["warnings"]:
            typer.echo(f"  WARNING: {warning}")
        for error in item["errors"]:
            typer.echo(f"  ERROR: {error}", err=True)
    if not report["profiles"]:
        typer.echo("No CLI profiles configured.")
    raise typer.Exit(0 if report["ok"] else 1)


@app.command(name="add")
def add_command(
    name: Optional[str] = typer.Option(None, "--name", help="Profile name for non-interactive creation"),
    kind: Optional[str] = typer.Option(None, "--type", help="CLI provider id"),
    mode: Optional[str] = typer.Option(None, "--mode", help="api or login, when supported"),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    credentials_path: Optional[str] = typer.Option(None, "--credentials-path"),
    proxy: Optional[str] = typer.Option(None, "--proxy"),
    default_args: Optional[str] = typer.Option(None, "--default-args"),
    secret_stdin: bool = typer.Option(False, "--secret-stdin", help="Read the API secret from standard input"),
):
    """Add a profile interactively or with explicit options"""
    values = (name, kind, mode, base_url, credentials_path, proxy, default_args)
    try:
        if not any(value is not None for value in values) and not secret_stdin:
            with transaction() as config:
                add_profile(config)
        else:
            if not name or not kind:
                raise ValueError("Non-interactive add requires --name and --type")
            secret = _secret_from_stdin() if secret_stdin else ""
            record = create_profile_data(name, kind, mode or "api", base_url, secret,
                                         credentials_path, proxy, default_args)
            with transaction() as config:
                if record["name"] in config.get("profiles", {}):
                    raise ValueError(f"Profile '{record['name']}' already exists")
                _configure_provider(get_provider(record["type"]))
                config.setdefault("profiles", {})[record["name"]] = record
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo("Profile added.")


@app.command(name="edit")
def edit_command(
    profile: str = typer.Argument(..., help="Existing profile name"),
    name: Optional[str] = typer.Option(None, "--name", help="New profile name"),
    mode: Optional[str] = typer.Option(None, "--mode"),
    base_url: Optional[str] = typer.Option(None, "--base-url"),
    credentials_path: Optional[str] = typer.Option(None, "--credentials-path"),
    proxy: Optional[str] = typer.Option(None, "--proxy"),
    clear_proxy: bool = typer.Option(False, "--clear-proxy"),
    default_args: Optional[str] = typer.Option(None, "--default-args"),
    clear_default_args: bool = typer.Option(False, "--clear-default-args"),
    secret_stdin: bool = typer.Option(False, "--secret-stdin"),
    clear_secret: bool = typer.Option(False, "--clear-secret"),
):
    """Edit a profile without exposing secrets in command arguments"""
    supplied = any(value is not None for value in
                   (name, mode, base_url, credentials_path, proxy, default_args))
    supplied = supplied or any((clear_proxy, clear_default_args, secret_stdin, clear_secret))
    if not supplied:
        raise typer.BadParameter("Provide at least one edit option")
    if secret_stdin and clear_secret:
        raise typer.BadParameter("--secret-stdin and --clear-secret cannot be combined")
    if clear_proxy and proxy is not None:
        raise typer.BadParameter("--clear-proxy and --proxy cannot be combined")
    if clear_default_args and default_args is not None:
        raise typer.BadParameter("--clear-default-args and --default-args cannot be combined")
    changes = dict(name=name, mode=mode, base_url=base_url, credentials_path=credentials_path,
                   proxy=proxy, clear_proxy=clear_proxy, default_args=default_args,
                   clear_default_args=clear_default_args, clear_secret=clear_secret)
    try:
        if secret_stdin:
            changes["secret"] = _secret_from_stdin()
        with transaction() as config:
            record = config.get("profiles", {}).get(profile)
            if not isinstance(record, dict):
                raise ValueError(f"Profile '{profile}' not found")
            updated = update_profile_data(record, changes)
            new_name = updated["name"]
            if new_name != profile and new_name in config["profiles"]:
                raise ValueError(f"Profile '{new_name}' already exists")
            _configure_provider(get_provider(updated["type"]))
            del config["profiles"][profile]
            config["profiles"][new_name] = updated
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo("Profile updated.")


@app.command(name="configure")
def configure_command(kind: str = typer.Argument(..., help="CLI provider requiring additional setup")):
    """Apply a provider's explicit local authentication setup"""
    try:
        provider = get_provider(kind)
        if provider.settings_provider == "gemini":
            from .antigravity import configure_gemini_api
            path = configure_gemini_api()
            typer.echo(f"Enabled Gemini API authentication in {path}")
        else:
            typer.echo(f"{provider.display} does not require additional local setup.")
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="kind") from None


@app.command(name="remove")
def remove_command(name: str = typer.Argument(..., help="Profile name to remove")):
    """Remove a profile"""
    with transaction() as config:
        remove_profile(config, name)


@app.command(name="login-browser")
def login_browser_command(
    profile: str = typer.Argument(..., help="Claude Code login profile"),
    mode: str = typer.Argument(..., help="manual or auto"),
):
    """Choose whether Claude Code opens its login browser automatically."""
    if mode not in ("manual", "auto"):
        raise typer.BadParameter("Choose 'manual' or 'auto'.", param_hint="mode")
    with transaction() as config:
        record = config.get("profiles", {}).get(profile)
        if not isinstance(record, dict) or record.get("type") != "claude" or record.get("mode") != "login":
            typer.echo("Choose an existing Claude Code login profile.", err=True)
            raise typer.Exit(1)
        record["manual_browser_login"] = mode == "manual"
    typer.echo("Manual browser login enabled." if mode == "manual" else "Automatic browser login enabled.")


@app.command(name="network-mode")
def network_mode_command(mode: str = typer.Argument(..., help="router or default")):
    """Select router mode or the existing proxy/TUN settings."""
    if mode not in ("router", "default"):
        raise typer.BadParameter("Choose 'router' or 'default'.", param_hint="mode")
    from .desktop import config as desktop_config
    with desktop_config.CONFIG_LOCK:
        data = desktop_config.load_desktop_config()
        desktop_config.set_safety_settings(data, {"router_mode": mode == "router"})
        desktop_config.save_desktop_config(data)
    if mode == "router":
        typer.echo("Router mode enabled. Restore existing system network guards and disable the local system proxy before launch.")
        typer.echo("On Windows, managed Claude launches also monitor the network and can block registered programs after a failure. Checks are periodic; other apps receive preflight only.")
    else:
        typer.echo("Router preflight disabled; existing proxy/TUN settings apply.")


@app.command(name="upgrade")
def upgrade_command(
    tools: Optional[List[str]] = typer.Argument(None, help="Tools to upgrade; default is every supported CLI"),
    exclude: Optional[List[str]] = typer.Option(None, "--exclude", help="Exclude a CLI from this upgrade; repeatable"),
):
    """Upgrade all supported CLIs, or only the selected tools"""
    try:
        upgrade(tools=tools, exclude=exclude)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="tools") from None


@app.command(
    name="run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_command(
    ctx: typer.Context,
    no_default_args: bool = typer.Option(
        False,
        "--no-default-args",
        help="Skip the profile's default_args for this run only",
    ),
    profile: str = typer.Argument(..., help="Profile name to launch"),
):
    """Launch a profile with optional arguments

    Examples:
      claudec run fox-claude
      claudec run fox-claude -p "hello"
      claudec run 4399 --help
      claudec run --no-default-args fox-claude --model sonnet
    """
    config = load_config()
    profiles = config.get("profiles", {})
    if profile not in profiles:
        typer.echo(f"Unknown profile: '{profile}'", err=True)
        typer.echo("Run 'claudec list' to see available profiles.")
        raise typer.Exit(1)
    launch(profiles[profile], ctx.args, use_default_args=not no_default_args)


desktop_app = typer.Typer(
    help="Download the desktop app, or run it from a development environment",
    add_completion=False,
)
app.add_typer(desktop_app, name="desktop")

_DESKTOP_UNSUPPORTED = "Claude China desktop supports Windows, macOS and Linux."
_DESKTOP_RELEASES = "https://github.com/invoker-bot/Claude-China/releases/latest"


def _require_desktop_extra() -> None:
    try:
        import webview  # noqa: F401
        import psutil  # noqa: F401
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        typer.echo(f"Download the standalone desktop installer: {_DESKTOP_RELEASES}")
        typer.echo('For source development only: pip install "claude-china[desktop]"')
        raise typer.Exit(1)


@desktop_app.command("download")
def desktop_download():
    """Show the GitHub Releases download page for native desktop installers."""
    typer.echo(_DESKTOP_RELEASES)


@desktop_app.command("install", hidden=True)
def desktop_install():
    """Compatibility hint for the retired shortcut installer."""
    typer.echo("Desktop installation has moved to native installers on GitHub Releases.")
    typer.echo(_DESKTOP_RELEASES)
    raise typer.Exit(1)


@desktop_app.command("run")
def desktop_run():
    """Run the GUI from a source/Python development installation."""
    from .desktop.platforms import get_backend

    backend = get_backend()
    if backend is None:
        typer.echo(_DESKTOP_UNSUPPORTED)
        raise typer.Exit(1)
    _require_desktop_extra()
    from .desktop.app import run_gui

    run_gui()


@desktop_app.command("uninstall", hidden=True)
def desktop_uninstall(
    purge: bool = typer.Option(
        False, "--purge", hidden=True,
    ),
    keep_config: bool = typer.Option(
        False, "--keep-config", hidden=True,
    ),
):
    """Compatibility hint; the operating system owns desktop installations."""
    typer.echo("Uninstall Claude China using your operating system:")
    typer.echo("  Windows: Settings > Apps > Installed apps > Claude China > Uninstall")
    typer.echo("  macOS: quit Claude China, then move it from Applications to Trash")
    typer.echo("  Linux: remove claude-china-desktop with your package manager")
    typer.echo("Your profiles and settings in ~/.claudec/ (and legacy ~/.code-ai/) are preserved.")
    raise typer.Exit(1)


def version_callback(value: bool):
    if value:
        typer.echo(f"claudec {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show version"
    ),
):
    """
    Switch AI coding tool profiles and launch the correct CLI.

    Examples:
      claudec list                      List all profiles
      claudec show fox-claude           Show profile details
      claudec run fox-grok              Launch Grok CLI with fox profile
      claudec run 4399                  Launch Claude CLI with 4399 profile
      claudec run fox-claude -p "hi"    Pass extra args to Claude CLI
    """
    pass


UPGRADE_PACKAGES = [provider.npm_package for provider in PROVIDERS if provider.npm_package]


def _run_npm(args, env):
    # On Windows, npm is a .cmd file, need to use shell=True or npm.cmd
    if sys.platform == "win32":
        return subprocess.run("npm " + " ".join(args), shell=True, env=env)
    return subprocess.run(["npm"] + args, env=env)


def _verify_grok(command, env, version):
    try:
        check_grok_version(command, env, version)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        sys.exit(1)


def _selected_providers(tools=None, exclude=None):
    selected = []
    for kind in tools or [provider.id for provider in PROVIDERS]:
        provider = get_provider(kind)
        if provider not in selected:
            selected.append(provider)
    excluded = {get_provider(kind).id for kind in exclude or []}
    selected = [provider for provider in selected if provider.id not in excluded]
    if not selected:
        raise ValueError("No CLI tools selected")
    return selected


def _verify_cli(kind, env):
    from .upgrades import verify_installation
    return verify_installation(kind, env)


def _upgrade_native(provider, env):
    url = provider.native_upgrade
    if sys.platform == "win32":
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                   f"irm {url}.ps1 | iex"]
        return subprocess.run(command, env=env)
    return subprocess.run(["bash", "-c", f"curl -fsSL {url}.sh | bash"], env=env)


def _upgrade_selected(selected, env):
    npm = [provider for provider in selected if provider.npm_package]
    if npm:
        from .upgrades import ensure_not_running
        for provider in npm:
            ensure_not_running(provider.id)
        result = _run_npm(["install", "-g", "--ignore-scripts=false"]
                          + [provider.npm_package for provider in npm], env)
        if result.returncode:
            sys.exit(result.returncode)
    if any(provider.id == "grok" for provider in npm):
        _upgrade_grok(env)
    for provider in npm:
        if provider.id != "grok":
            typer.echo(f"{provider.display}: {_verify_cli(provider.id, env)}")
    for provider in selected:
        if not provider.native_upgrade:
            continue
        typer.echo(f"Updating {provider.display} with its official installer...")
        result = _upgrade_native(provider, env)
        if result.returncode:
            sys.exit(result.returncode)
        typer.echo(f"{provider.display}: {_verify_cli(provider.id, env)}")


def _upgrade_grok(env):
    installation = find_npm_installation()
    if not installation:
        typer.echo("Cannot find the updated @xai-official/grok installation in the active npm prefix.", err=True)
        sys.exit(1)
    _verify_grok(installation.command, env, installation.version)
    default_home = os.path.expanduser("~/.grok")
    _verify_grok(home_binary(default_home), env, installation.version)
    typer.echo(f"Grok CLI {installation.version} verified at {installation.command}")

    # Grok's npm launcher prefers GROK_HOME/bin even when that binary is old.
    # Re-run its installer in each login home after updating the global package.
    refreshed = {os.path.normcase(os.path.realpath(default_home))}
    for name, profile in load_config().get("profiles", {}).items():
        if (profile.get("type") != "grok" or profile.get("mode") != "login"
                or not profile.get("credentials_path")):
            continue
        home = os.path.expanduser(profile["credentials_path"])
        normalized_home = os.path.normcase(os.path.realpath(home))
        if normalized_home in refreshed:
            continue
        typer.echo(f"Refreshing Grok CLI for login profile '{name}'...")
        profile_env = dict(env, GROK_HOME=home)
        result = _run_npm([
            "rebuild", "-g", "--ignore-scripts=false", "--foreground-scripts", "@xai-official/grok",
        ], profile_env)
        if result.returncode:
            typer.echo(f"Failed to refresh Grok CLI for profile '{name}'.", err=True)
            sys.exit(result.returncode)
        _verify_grok(home_binary(home), profile_env, installation.version)
        typer.echo(f"Grok CLI {installation.version} verified for profile '{name}'.")
        refreshed.add(normalized_home)


def upgrade(tools=None, exclude=None):
    selected = _selected_providers(tools, exclude)
    typer.echo("Upgrading " + ", ".join(provider.id for provider in selected) + "...")
    env = os.environ.copy()
    env.pop("GROK_HOME", None)
    env.pop("AGY_CLI_DISABLE_AUTO_UPDATE", None)
    try:
        _upgrade_selected(selected, env)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    app()


