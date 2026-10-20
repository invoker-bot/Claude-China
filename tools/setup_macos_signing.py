"""Provision a temporary signing keychain on a macOS GitHub Actions runner."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import tempfile

if __package__:
    from .desktop_signing import run
else:
    from desktop_signing import run


def export_environment(values):
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError("Signing configuration must not contain line breaks")
            output.write(f"{name}={value}\n")


def setup():
    names = (
        "MACOS_CERTIFICATE_P12", "MACOS_CERTIFICATE_PASSWORD", "MACOS_TEAM_ID",
        "APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "RUNNER_TEMP", "GITHUB_ENV",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing signing credentials: " + ", ".join(missing))
    team = os.environ["MACOS_TEAM_ID"]
    if not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise RuntimeError("MACOS_TEAM_ID must be the ten-character Apple team ID")
    certificate = base64.b64decode(os.environ["MACOS_CERTIFICATE_P12"], validate=True)
    directory = Path(tempfile.mkdtemp(prefix="claude-china-signing-", dir=os.environ["RUNNER_TEMP"]))
    export_environment({"MACOS_SIGNING_TEMP_DIRECTORY": str(directory)})
    previous = shlex.split(run(["security", "list-keychains", "-d", "user"]).stdout)
    (directory / "previous-keychains.json").write_text(json.dumps(previous), encoding="utf-8")
    keychain = directory / "release.keychain-db"
    certificate_file = directory / "certificate.p12"
    certificate_file.write_bytes(certificate)
    certificate_file.chmod(0o600)
    password = secrets.token_urlsafe(32)
    run(["security", "create-keychain", "-p", password, keychain], private=True)
    run(["security", "set-keychain-settings", "-lut", "21600", keychain])
    run(["security", "unlock-keychain", "-p", password, keychain], private=True)
    run(["security", "import", certificate_file, "-P", os.environ["MACOS_CERTIFICATE_PASSWORD"],
         "-k", keychain, "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"], private=True)
    certificate_file.unlink()
    run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
         "-s", "-k", password, keychain], private=True)
    run(["security", "list-keychains", "-d", "user", "-s", keychain, *previous])
    identities = run(["security", "find-identity", "-v", "-p", "codesigning", keychain]).stdout
    matches = [
        fingerprint for fingerprint, name in
        re.findall(r'([0-9A-Fa-f]{40})\s+"(Developer ID Application:[^"]+)"', identities)
        if name.endswith(f"({team})")
    ]
    if len(matches) != 1:
        raise RuntimeError("The P12 must contain one valid Developer ID Application identity for MACOS_TEAM_ID")
    profile = "claude-china-release"
    run(["xcrun", "notarytool", "store-credentials", profile, "--keychain", keychain,
         "--apple-id", os.environ["APPLE_ID"], "--team-id", team,
         "--password", os.environ["APPLE_APP_SPECIFIC_PASSWORD"]], private=True)
    export_environment({
        "MACOS_SIGNING_IDENTITY": matches[0],
        "MACOS_TEAM_ID": team,
        "MACOS_SIGNING_KEYCHAIN": str(keychain),
        "MACOS_NOTARY_PROFILE": profile,
    })


def cleanup():
    temporary = os.environ.get("MACOS_SIGNING_TEMP_DIRECTORY")
    if not temporary:
        return
    directory = Path(temporary).resolve()
    runner = Path(os.environ["RUNNER_TEMP"]).resolve()
    if directory.parent != runner or not directory.name.startswith("claude-china-signing-"):
        raise RuntimeError("Refusing to remove a directory outside this signing job")
    if not directory.exists():
        return
    previous = directory / "previous-keychains.json"
    try:
        if previous.is_file():
            run(["security", "list-keychains", "-d", "user", "-s",
                 *json.loads(previous.read_text(encoding="utf-8"))])
        keychain = directory / "release.keychain-db"
        if keychain.exists():
            run(["security", "delete-keychain", keychain])
    finally:
        shutil.rmtree(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "cleanup"))
    args = parser.parse_args()
    setup() if args.action == "setup" else cleanup()
