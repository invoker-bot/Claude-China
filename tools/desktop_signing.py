"""Signing and notarization checks used by native desktop release builds."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess


def run(args, *, private=False, check=True, timeout=120):
    args = [str(arg) for arg in args]
    if not private:
        print("+", " ".join(args), flush=True)
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        # Do not expose a password in an exception's command-line representation.
        raise RuntimeError(f"{Path(args[0]).name} could not complete") from None
    if check and result.returncode:
        detail = "" if private else "\n" + result.stdout + result.stderr
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}){detail}")
    return result


@dataclass(frozen=True)
class MacSigning:
    identity: str
    team: str
    profile: str
    keychain: str = ""


def macos_config(required=False):
    names = ("MACOS_SIGNING_IDENTITY", "MACOS_TEAM_ID", "MACOS_NOTARY_PROFILE")
    values = [os.environ.get(name, "").strip() for name in names]
    if not required and not any(values):
        return None
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise RuntimeError("Missing macOS signing configuration: " + ", ".join(missing))
    if values[0] == "-" or not re.fullmatch(r"[A-Z0-9]{10}", values[1]):
        raise RuntimeError("A Developer ID Application identity and valid MACOS_TEAM_ID are required")
    return MacSigning(*values, os.environ.get("MACOS_SIGNING_KEYCHAIN", ""))


def verify_macos_signature(target, team, *, app=False):
    run(["codesign", "--verify", "--deep", "--strict", "--all-architectures", target])
    result = run(["codesign", "--display", "--verbose=4", target])
    details = result.stdout + result.stderr
    if ("Authority=Developer ID Application:" not in details
            or f"TeamIdentifier={team}" not in details.splitlines()
            or "Timestamp=" not in details
            or (app and "(runtime)" not in details)):
        raise RuntimeError(f"Invalid Developer ID signature on {target}")


def notarize(target, profile, reports, *, keychain="", staple_target=None):
    reports = Path(reports)
    reports.mkdir(parents=True, exist_ok=True)
    credentials = ["--keychain-profile", profile]
    if keychain:
        credentials += ["--keychain", keychain]
    result = run([
        "xcrun", "notarytool", "submit", target, *credentials,
        "--wait", "--timeout", "20m", "--output-format", "json",
    ], check=False, timeout=1260)
    report = reports / (Path(target).name + "-notary.json")
    report.write_text(result.stdout, encoding="utf-8")
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError(f"Invalid notarization response; see {report}") from None
    if response.get("id"):
        log = run([
            "xcrun", "notarytool", "log", response["id"], *credentials,
        ], check=False)
        (reports / (Path(target).name + "-notary-log.json")).write_text(
            log.stdout, encoding="utf-8",
        )
    if result.returncode or response.get("status") != "Accepted":
        raise RuntimeError(f"Notarization {response.get('status', 'failed')}; see {report}")
    staple_target = str(staple_target or target)
    run(["xcrun", "stapler", "staple", staple_target])
    run(["xcrun", "stapler", "validate", staple_target])


def notarize_macos_app(app, config, work):
    archive = work / "notarization-app.zip"
    archive.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--keepParent", app, archive])
    notarize(archive, config.profile, work, keychain=config.keychain, staple_target=app)
    run(["spctl", "--assess", "--type", "execute", "--verbose=4", app])


def sign_macos_dmg(dmg, config, work):
    run(["codesign", "--force", "--sign", config.identity, "--timestamp", dmg])
    verify_macos_signature(dmg, config.team)
    notarize(dmg, config.profile, work, keychain=config.keychain)
    run(["spctl", "--assess", "--type", "open", "--context",
         "context:primary-signature", "--verbose=4", dmg])
