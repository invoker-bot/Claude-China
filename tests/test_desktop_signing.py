import base64
import json
import subprocess

import pytest

from tools import desktop_signing


def test_macos_signed_build_requires_complete_credentials(monkeypatch):
    for name in ("MACOS_SIGNING_IDENTITY", "MACOS_TEAM_ID", "MACOS_NOTARY_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    assert desktop_signing.macos_config(required=False) is None
    with pytest.raises(RuntimeError, match="MACOS_SIGNING_IDENTITY"):
        desktop_signing.macos_config(required=True)
    monkeypatch.setenv("MACOS_SIGNING_IDENTITY", "Developer ID Application: Example (ABCDEFGHIJ)")
    with pytest.raises(RuntimeError, match="MACOS_NOTARY_PROFILE"):
        desktop_signing.macos_config(required=False)


@pytest.mark.parametrize("details", [
    "Signature=adhoc\nTeamIdentifier=not set\n",
    "Authority=Developer ID Application: Example (OTHERTEAM1)\n"
    "TeamIdentifier=OTHERTEAM1\nTimestamp=Oct 20, 2026\nflags=0x10000(runtime)\n",
    "Authority=Apple Development: Example\nTeamIdentifier=ABCDEFGHIJ\n"
    "Timestamp=Oct 20, 2026\nflags=0x10000(runtime)\n",
    "Authority=Developer ID Application: Example (ABCDEFGHIJ)\n"
    "TeamIdentifier=ABCDEFGHIJ\nflags=0x10000(runtime)\n",
    "Authority=Developer ID Application: Example (ABCDEFGHIJ)\n"
    "TeamIdentifier=ABCDEFGHIJ\nTimestamp=Oct 20, 2026\nflags=0x0(none)\n",
])
def test_macos_app_rejects_untrusted_or_incomplete_signature(monkeypatch, tmp_path, details):
    monkeypatch.setattr(
        desktop_signing, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", details),
    )
    with pytest.raises(RuntimeError, match="signature"):
        desktop_signing.verify_macos_signature(tmp_path / "App.app", "ABCDEFGHIJ", app=True)


def test_notarization_invalid_response_cannot_produce_stapled_artifact(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        result = {"id": "submission-id", "status": "Invalid"} if "submit" in args else {}
        return subprocess.CompletedProcess(args, 0, json.dumps(result), "")

    monkeypatch.setattr(desktop_signing, "run", run)
    with pytest.raises(RuntimeError, match="Invalid"):
        desktop_signing.notarize(tmp_path / "App.dmg", "profile", tmp_path)
    assert not any("stapler" in args for args in calls)
    assert any("log" in args for args in calls)
    assert json.loads((tmp_path / "App.dmg-notary.json").read_text())["status"] == "Invalid"


def test_notarization_staples_only_after_accepted_and_validates_ticket(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        result = {"id": "submission-id", "status": "Accepted"} if "submit" in args else {}
        return subprocess.CompletedProcess(args, 0, json.dumps(result), "")

    monkeypatch.setattr(desktop_signing, "run", run)
    desktop_signing.notarize(tmp_path / "App.dmg", "profile", tmp_path, keychain="/private/build.keychain-db")
    assert [args[2] for args in calls] == ["submit", "log", "staple", "validate"]
    assert calls[0][calls[0].index("--keychain") + 1] == "/private/build.keychain-db"
    assert calls[2][-1] == str(tmp_path / "App.dmg")


def test_secret_command_failure_does_not_expose_arguments(monkeypatch):
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "password=super-secret")

    monkeypatch.setattr(desktop_signing.subprocess, "run", failed)
    with pytest.raises(RuntimeError) as error:
        desktop_signing.run(["security", "import", "-P", "super-secret"], private=True)
    assert "super-secret" not in str(error.value)


def test_keychain_cleanup_cannot_delete_outside_runner_temporary_directory(monkeypatch, tmp_path):
    from tools import setup_macos_signing
    preserved = tmp_path / "claude-china-signing-preserve"
    preserved.mkdir()
    sentinel = preserved / "certificate.p12"
    sentinel.write_bytes(b"preserve")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))
    monkeypatch.setenv("MACOS_SIGNING_TEMP_DIRECTORY", str(preserved))
    with pytest.raises(RuntimeError, match="outside"):
        setup_macos_signing.cleanup()
    assert sentinel.read_bytes() == b"preserve"


def test_setup_exports_complete_configuration_and_cleanup_restores_keychains(monkeypatch, tmp_path):
    from tools import setup_macos_signing
    environment_file = tmp_path / "environment"
    credentials = {
        "MACOS_CERTIFICATE_P12": base64.b64encode(b"certificate").decode(),
        "MACOS_CERTIFICATE_PASSWORD": "certificate-password",
        "MACOS_TEAM_ID": "ABCDEFGHIJ",
        "APPLE_ID": "developer@example.com",
        "APPLE_APP_SPECIFIC_PASSWORD": "notary-password",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_ENV": str(environment_file),
    }
    for name, value in credentials.items():
        monkeypatch.setenv(name, value)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        output = ""
        if args[:4] == ["security", "list-keychains", "-d", "user"] and "-s" not in args:
            output = '"/Users/runner/Library/Keychains/login.keychain-db"\n'
        elif args[:2] == ["security", "create-keychain"]:
            args[-1].touch()
        elif args[:2] == ["security", "find-identity"]:
            output = '1) ' + "A" * 40 + ' "Developer ID Application: Example (ABCDEFGHIJ)"'
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(setup_macos_signing, "run", run)
    setup_macos_signing.setup()
    exported = dict(line.split("=", 1) for line in environment_file.read_text().splitlines())
    assert exported["MACOS_TEAM_ID"] == "ABCDEFGHIJ"
    for name, value in exported.items():
        monkeypatch.setenv(name, value)
    assert desktop_signing.macos_config(required=True).identity == "A" * 40
    assert "certificate-password" not in environment_file.read_text()
    assert "notary-password" not in environment_file.read_text()
    assert not list(tmp_path.rglob("*.p12"))
    for args, kwargs in calls:
        if any(password in args for password in ("certificate-password", "notary-password")):
            assert kwargs.get("private")
    setup_macos_signing.cleanup()
    assert calls[-2][0] == [
        "security", "list-keychains", "-d", "user", "-s",
        "/Users/runner/Library/Keychains/login.keychain-db",
    ]
    assert not list(tmp_path.glob("claude-china-signing-*"))


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_signed_build_cannot_silently_ignore_unsupported_platform(monkeypatch, platform):
    from tools import build_desktop
    monkeypatch.setattr(build_desktop.sys, "platform", platform)
    monkeypatch.setattr(build_desktop.sys, "argv", ["build_desktop.py", "--signed"])

    def unexpected_build():
        pytest.fail("Unsupported signing must fail before building")

    monkeypatch.setattr(build_desktop, "freeze", unexpected_build)
    with pytest.raises(SystemExit) as error:
        build_desktop.main()
    assert error.value.code == 2
