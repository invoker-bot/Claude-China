"""Verify a real PyPI 0.1.23 -> bridge upgrade in an isolated environment.

Run after building the bridge:
    python tests/legacy_install_smoke.py compat/ai-code-switcher/dist/<wheel>

After publishing, pass ai-code-switcher==0.1.24 to verify the public release.
Network access to PyPI is required. No user configuration is read or written.
"""

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", help="Bridge wheel path or pinned PyPI requirement")
    args = parser.parse_args()
    candidate = args.candidate
    if Path(candidate).is_file():
        candidate = str(Path(candidate).resolve())

    artifact_root = Path(__file__).resolve().parents[1] / ".test-artifacts"
    artifact_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="legacy-upgrade-", dir=artifact_root) as folder:
        root = Path(folder)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        scripts = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        suffix = ".exe" if os.name == "nt" else ""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.update(NO_COLOR="1", TERM="dumb", PYTHONIOENCODING="utf-8")

        def run(*command, expected=0):
            result = subprocess.run(
                [str(part) for part in command], cwd=root, env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180,
            )
            assert result.returncode == expected, (
                f"{command} exited {result.returncode}, expected {expected}\n"
                f"{result.stdout}\n{result.stderr}"
            )
            return result

        def install(*requirements):
            return run(
                python, "-m", "pip", "--isolated", "--disable-pip-version-check",
                "install", "--index-url", "https://pypi.org/simple",
                "--no-cache-dir", "--no-input", *requirements,
            )

        print("Installing the previous ai-code-switcher 0.1.23 release...", flush=True)
        install("ai-code-switcher==0.1.23")
        old = run(scripts / f"code-ai{suffix}", "--version")
        assert "0.1.23" in old.stdout
        run(python, "-c", "import importlib.util; assert importlib.util.find_spec('claude_china') is None")

        print("Upgrading to the bridge and checking automatic dependency installation...", flush=True)
        install("--upgrade", candidate)
        metadata = json.loads(run(
            python, "-c",
            "import importlib.metadata as m, json; "
            "print(json.dumps({'legacy': m.version('ai-code-switcher'), "
            "'current': m.version('claude-china'), "
            "'requires': m.requires('ai-code-switcher')}))",
        ).stdout)
        assert metadata["legacy"] == "0.1.24"
        assert "claude-china>=0.2.1" in metadata["requires"]
        assert any(
            "claude-china[desktop]>=0.2.1" in requirement
            and "desktop" in requirement.partition(";")[2]
            for requirement in metadata["requires"]
        )
        current = run(scripts / f"claudec{suffix}", "--version")
        assert current.stdout.strip() == f"claudec {metadata['current']}"
        assert "deprecated" not in current.stderr
        for command in (
            [scripts / f"code-ai{suffix}"],
            [python, "-m", "code_ai.cli"],
        ):
            old = run(*command, "--version")
            assert old.stdout == current.stdout
            assert "deprecated" in old.stderr
            assert "claudec" in old.stderr
            help_result = run(*command, "--help")
            assert "claudec" in help_result.stdout
            assert "Claude China" in help_result.stdout
            run(*command, "not-a-command", expected=2)

        print("Checking that uninstalling the bridge leaves claudec usable...", flush=True)
        run(
            python, "-m", "pip", "--isolated", "--disable-pip-version-check",
            "uninstall", "-y", "ai-code-switcher",
        )
        remaining = run(scripts / f"claudec{suffix}", "--version")
        assert remaining.stdout == current.stdout
        run(python, "-c", "import importlib.util; assert importlib.util.find_spec('code_ai') is None")
        print(f"PASS: ai-code-switcher 0.1.23 -> 0.1.24 -> claude-china {metadata['current']}")


if __name__ == "__main__":
    main()
