"""Release smoke test with the real npm installer on a fresh macOS runner."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from claude_china import cli
from claude_china.grok import check_version, find_npm_installation, home_binary


def main():
    with tempfile.TemporaryDirectory(prefix="claudec-grok-smoke-") as temporary:
        root = Path(temporary)
        prefix = root / "npm-prefix"
        old_bin = root / "old-install"
        home = root / "login home"
        old_bin.mkdir()
        (home / "bin").mkdir(parents=True)
        old_script = "#!/bin/sh\necho 'grok 0.2.118 (old)'\n"
        for path in [old_bin / "grok", home / "bin/grok"]:
            path.write_text(old_script, encoding="utf-8")
            path.chmod(0o755)
        default_binary = Path(home_binary(os.path.expanduser("~/.grok")))
        if not default_binary.exists():
            default_binary.parent.mkdir(parents=True, exist_ok=True)
            default_binary.write_text(old_script, encoding="utf-8")
            default_binary.chmod(0o755)
        auth = home / "auth.json"
        auth.write_text("{}\n", encoding="utf-8")
        os.environ["npm_config_prefix"] = str(prefix)
        os.environ["npm_config_ignore_scripts"] = "true"
        os.environ["PATH"] = str(old_bin) + os.pathsep + os.environ["PATH"]
        profile = {"name": "smoke", "type": "grok", "mode": "login", "credentials_path": str(home)}
        cli.UPGRADE_PACKAGES = ["@xai-official/grok"]
        cli.load_config = lambda: {"profiles": {"smoke": profile}}
        try:
            cli.upgrade()
        except SystemExit as exc:
            assert exc.code == 0, "Grok upgrade failed"
        installation = find_npm_installation()
        assert installation is not None
        check_version(home_binary(str(home)), dict(os.environ, GROK_HOME=str(home)), installation.version)
        assert auth.read_text(encoding="utf-8") == "{}\n", "Login credentials changed"
        result = subprocess.run(
            [sys.executable, "-c", "from claude_china.launcher import launch; launch(" + repr(profile) + ", ['--version'])"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "grok " + installation.version in result.stdout, result.stdout
        print("Verified real npm upgrade and launch on macOS: " + result.stdout.strip())


if __name__ == "__main__":
    main()
