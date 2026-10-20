"""Export Windows/macOS icons and a one-shot motion preview from the PNG master."""

import argparse
from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "code_ai" / "desktop" / "ui"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=UI / "icon.png")
    args = parser.parse_args()
    resampling = getattr(Image, "Resampling", Image)
    with Image.open(args.source) as source:
        master = source.convert("RGBA").resize((1024, 1024), resampling.LANCZOS)
    try:
        master.save(UI / "icon.png", optimize=True)
        sizes = [(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
        master.save(UI / "icon.ico", sizes=sizes)
        master.save(UI / "icon.icns")

        # Use the actual tray animation frames, rather than a separate mockup.
        sys.path.insert(0, str(ROOT / "src"))
        from code_ai.desktop.animation import build_activity_frames

        preview = ROOT / "docs" / "branding" / "anti-claude-motion.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        with master.resize((192, 192), resampling.LANCZOS) as rest:
            frames = build_activity_frames(rest)
            try:
                rest.save(
                    preview, save_all=True, append_images=frames + [rest],
                    duration=[500] + [80] * len(frames) + [1500],
                    loop=1, disposal=0, blend=0,
                )
            finally:
                for frame in frames:
                    frame.close()
    finally:
        master.close()
    print("Exported PNG, ICO, ICNS and the one-shot APNG preview.")


if __name__ == "__main__":
    main()
