import hashlib

import pytest

from tools import prepare_desktop_release as release


VERSION = "0.4.0"
PACKAGES = {
    "windows-x64": ["windows-x64-setup.exe"],
    "linux-x64": ["linux-x64.deb", "linux-x64.rpm"],
    "macos-x64": ["macos-x64.dmg"],
    "macos-arm64": ["macos-arm64.dmg"],
}


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "artifacts"
    for target, suffixes in PACKAGES.items():
        folder = root / ("desktop-" + target)
        folder.mkdir(parents=True)
        for suffix in suffixes:
            package = folder / f"Claude-China-{VERSION}-{suffix}"
            package.write_bytes(suffix.encode())
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            package.with_name(package.name + ".sha256").write_text(f"{digest}  {package.name}\n")
    return root


def test_windows_linux_release_excludes_macos_and_unrelated_artifacts(artifacts, tmp_path):
    (artifacts / "desktop-windows-x64/unrelated.exe").write_bytes(b"ignore")
    output = tmp_path / "release"
    release.prepare_release(artifacts, output, VERSION)
    expected = {f"Claude-China-{VERSION}-{suffix}" for target in ("windows-x64", "linux-x64")
                for suffix in PACKAGES[target]}
    assert {p.name for p in output.iterdir()} == expected | {n + ".sha256" for n in expected} | {"SHA256SUMS"}
    lines = (output / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        digest, filename = line.split("  ")
        assert filename in expected
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest


def test_explicit_macos_release_requires_both_architectures(artifacts, tmp_path):
    output = tmp_path / "release"
    release.prepare_release(artifacts, output, VERSION, include_macos=True)
    assert len(list(output.glob("*.dmg"))) == 2
    assert len((output / "SHA256SUMS").read_text().splitlines()) == 5


@pytest.mark.parametrize("damage", ["payload", "checksum", "filename", "missing"])
def test_invalid_release_artifacts_fail_before_creating_output(artifacts, tmp_path, damage):
    package = artifacts / "desktop-linux-x64" / f"Claude-China-{VERSION}-linux-x64.rpm"
    checksum = package.with_name(package.name + ".sha256")
    if damage == "payload":
        package.write_bytes(b"corrupt")
    elif damage == "checksum":
        checksum.unlink()
    elif damage == "filename":
        checksum.write_text(checksum.read_text().replace(package.name, "wrong-version.rpm"))
    else:
        package.unlink()
    output = tmp_path / "release"
    with pytest.raises((ValueError, FileNotFoundError)):
        release.prepare_release(artifacts, output, VERSION)
    assert not output.exists()


def test_existing_output_cannot_mix_stale_packages_into_release(artifacts, tmp_path):
    output = tmp_path / "release"
    output.mkdir()
    stale = output / "stale.dmg"
    stale.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        release.prepare_release(artifacts, output, VERSION)
    assert stale.read_bytes() == b"preserve"


def test_missing_macos_does_not_block_windows_linux_but_blocks_macos_release(artifacts, tmp_path):
    image = artifacts / "desktop-macos-arm64" / f"Claude-China-{VERSION}-macos-arm64.dmg"
    image.unlink()
    release.prepare_release(artifacts, tmp_path / "windows-linux", VERSION)
    with pytest.raises(FileNotFoundError):
        release.prepare_release(artifacts, tmp_path / "all", VERSION, include_macos=True)


def test_wrong_version_cannot_publish_other_version_artifacts(artifacts, tmp_path):
    with pytest.raises(FileNotFoundError):
        release.prepare_release(artifacts, tmp_path / "release", "0.5.0")
