import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Requires Unix executable scripts")
def test_grok_launch_executes_updated_npm_binary_with_isolated_home(tmp_path):
    old_bin = tmp_path / "old-install"
    prefix = tmp_path / "npm-prefix"
    old_bin.mkdir()
    (prefix / "bin").mkdir(parents=True)
    package = prefix / "lib/node_modules/@xai-official/grok"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@xai-official/grok", "version": "1.0.46"}))
    scripts = {
        old_bin / "npm": "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(str(prefix)) + "\n",
        old_bin / "grok": "#!/bin/sh\necho 'grok 0.2.118 (old)'\n",
        prefix / "bin/grok": "#!/bin/sh\necho 'grok 1.0.46 (current)'\nprintf 'profile=%s\\n' \"$GROK_HOME\"\n",
    }
    for path, script in scripts.items():
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    home = str(tmp_path / "profile with spaces")
    profile = {"name": "account-a", "type": "grok", "mode": "login", "credentials_path": home}
    env = os.environ.copy()
    env["PATH"] = str(old_bin) + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", "from claude_china.launcher import launch; launch(" + repr(profile) + ", ['--version'])"],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "grok 1.0.46" in result.stdout
    assert "0.2.118" not in result.stdout
    assert "profile=" + home in result.stdout
