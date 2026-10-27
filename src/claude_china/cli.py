import os
import sys
import subprocess
from typing import Optional, List

import typer

from .config import load_config, save_config
from .profiles import list_profiles, add_profile, remove_profile, show_profile
from .launcher import launch
from .grok import find_npm_installation, home_binary, check_version as check_grok_version
from .buddy import (
    RARITIES, SPECIES, RARITY_COLORS,
    roll_by_name, bruteforce_user_id,
    write_user_id_to_claude_config, get_claude_config_path,
    format_buddy_card,
)
from .models import profile_from_dict, LoginProfile
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
def show_command(name: str = typer.Argument(..., help="Profile name to show")):
    """Show profile details (platform, URL, and credentials)"""
    config = load_config()
    show_profile(config, name)


@app.command(name="add")
def add_command():
    """Add a new profile interactively"""
    config = load_config()
    config = add_profile(config)
    save_config(config)
    typer.echo("Profile added.")


@app.command(name="remove")
def remove_command(name: str = typer.Argument(..., help="Profile name to remove")):
    """Remove a profile"""
    config = load_config()
    config = remove_profile(config, name)
    save_config(config)


@app.command(name="login-browser")
def login_browser_command(
    profile: str = typer.Argument(..., help="Claude Code login profile"),
    mode: str = typer.Argument(..., help="manual or auto"),
):
    """Choose whether Claude Code opens its login browser automatically."""
    if mode not in ("manual", "auto"):
        raise typer.BadParameter("Choose 'manual' or 'auto'.", param_hint="mode")
    config = load_config()
    record = config.get("profiles", {}).get(profile)
    if not isinstance(record, dict) or record.get("type") != "claude" or record.get("mode") != "login":
        typer.echo("Choose an existing Claude Code login profile.", err=True)
        raise typer.Exit(1)
    if mode == "manual":
        record["manual_browser_login"] = True
    else:
        record["manual_browser_login"] = False
    save_config(config)
    typer.echo("Manual browser login enabled." if mode == "manual" else "Automatic browser login enabled.")


@app.command(name="network-mode")
def network_mode_command(mode: str = typer.Argument(..., help="router or default")):
    """Select router preflight or the existing proxy/TUN settings."""
    if mode not in ("router", "default"):
        raise typer.BadParameter("Choose 'router' or 'default'.", param_hint="mode")
    from .desktop import config as desktop_config
    with desktop_config.CONFIG_LOCK:
        data = desktop_config.load_desktop_config()
        desktop_config.set_safety_settings(data, {"router_mode": mode == "router"})
        desktop_config.save_desktop_config(data)
    if mode == "router":
        typer.echo("Router preflight enabled. Restore existing system network guards and disable the local system proxy before launch.")
        typer.echo("The check cannot block direct connections after the router fails.")
    else:
        typer.echo("Router preflight disabled; existing proxy/TUN settings apply.")


@app.command(name="roll-claude-buddy")
def roll_claude_buddy_command(
    profile: str = typer.Argument(..., help="Profile name to roll buddy for"),
    species: Optional[str] = typer.Option(None, "--name", "-n", help="Target species: duck/cat/dragon/capybara/..."),
    rarity: Optional[str] = typer.Option(None, "--type", "-t", help="Target rarity: common/uncommon/rare/epic/legendary"),
):
    """Roll a Claude Code buddy companion for a profile

    By default the buddy is deterministic per profile (same profile = same buddy).
    Use --name and/or --type to keep rolling until you get the target species/rarity.

    Examples:
      claudec roll-claude-buddy fox-claude                           Roll buddy for profile
      claudec roll-claude-buddy fox-claude --name capybara           Roll until capybara
      claudec roll-claude-buddy fox-claude --type legendary          Roll until legendary
      claudec roll-claude-buddy fox-claude --name dragon --type epic Roll until epic dragon
    """
    config = load_config()
    profiles = config.get("profiles", {})
    if profile not in profiles:
        typer.echo(f"Unknown profile: '{profile}'", err=True)
        typer.echo("Run 'claudec list' to see available profiles.")
        raise typer.Exit(1)

    if rarity and rarity not in RARITIES:
        typer.echo(f"Invalid rarity: '{rarity}'. Choose from: {', '.join(RARITIES)}", err=True)
        raise typer.Exit(1)

    if species and species not in SPECIES:
        typer.echo(f"Invalid species: '{species}'. Choose from: {', '.join(SPECIES)}", err=True)
        raise typer.Exit(1)

    # Resolve the .claude.json path for this profile:
    # login mode → credentials_path/.claude.json
    # api mode   → ~/.claude.json
    profile_obj = profile_from_dict(profiles[profile])
    config_dir = None
    if isinstance(profile_obj, LoginProfile) and profile_obj.credentials_path:
        import os
        config_dir = os.path.expanduser(profile_obj.credentials_path)

    import io
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if species or rarity:
        claude_json = get_claude_config_path(config_dir)
        out.write("\n")
        target_desc = " + ".join(filter(None, [
            rarity.capitalize() if rarity else None,
            species.capitalize() if species else None,
        ]))
        out.write(f"  Bruteforcing userID for {target_desc}...\n")
        out.flush()
        user_id, bones = bruteforce_user_id(target_rarity=rarity, target_species=species)
        write_user_id_to_claude_config(user_id, config_dir)
        out.write(f"  Written userID to {claude_json}\n")
    else:
        bones = roll_by_name(profile)
        user_id = None

    color = RARITY_COLORS[bones.rarity]
    card = format_buddy_card(bones)
    out.write("\n")
    out.write(typer.style(f"  [{profile}] You rolled a Claude Buddy!", bold=True) + "\n")
    out.write("\n")
    out.write(typer.style(card, fg=color) + "\n")
    if user_id:
        out.write("\n")
        out.write(f"  Restart Claude Code to see your new buddy!\n")
    out.write("\n")
    out.flush()


@app.command(name="upgrade")
def upgrade_command():
    """Upgrade claude, codex, and grok CLI via npm"""
    upgrade()


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


UPGRADE_PACKAGES = [
    "@anthropic-ai/claude-code",
    "@openai/codex",
    "@xai-official/grok",
]


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


def upgrade():
    typer.echo("Upgrading claude, codex, grok CLI...")

    env = os.environ.copy()
    env.pop("GROK_HOME", None)
    result = _run_npm(["install", "-g", "--ignore-scripts=false"] + UPGRADE_PACKAGES, env)
    if result.returncode:
        sys.exit(result.returncode)

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
    sys.exit(0)


if __name__ == "__main__":
    app()


