"""Collect only the selected version's installers after verifying all checksums."""

import argparse
import hashlib
from pathlib import Path
import re
import runpy
import shutil


def prepare_release(artifacts, output, version, include_macos=False):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must have the form X.Y.Z")
    artifacts, output = Path(artifacts), Path(output)
    if output.exists():
        raise FileExistsError(f"Release output must be a new directory: {output}")
    packages = [
        ("windows-x64", "windows-x64-setup.exe"),
        ("linux-x64", "linux-x64.deb"),
        ("linux-x64", "linux-x64.rpm"),
    ]
    if include_macos:
        packages += [("macos-x64", "macos-x64.dmg"), ("macos-arm64", "macos-arm64.dmg")]
    verified = []
    for target, suffix in packages:
        package = artifacts / ("desktop-" + target) / f"Claude-China-{version}-{suffix}"
        checksum = package.with_name(package.name + ".sha256")
        digest = hashlib.sha256()
        with package.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        line = f"{digest.hexdigest()}  {package.name}"
        if checksum.read_text(encoding="utf-8").strip() != line:
            raise ValueError(f"Installer checksum or filename mismatch: {package.name}")
        verified.append((package, checksum, line))
    # Validate the complete selection before exposing any files for uploading.
    output.mkdir(parents=True)
    for package, checksum, _ in verified:
        shutil.copyfile(package, output / package.name)
        shutil.copyfile(checksum, output / checksum.name)
    (output / "SHA256SUMS").write_text(
        "".join(line + "\n" for _, _, line in verified), encoding="utf-8",
    )
    return [package.name for package, _, _ in verified]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("release"))
    parser.add_argument("--include-macos", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = runpy.run_path(str(root / "src/claude_china/__init__.py"))["__version__"]
    packages = prepare_release(args.artifacts, args.output, version, args.include_macos)
    print("Verified release installers: " + ", ".join(packages))


if __name__ == "__main__":
    main()
