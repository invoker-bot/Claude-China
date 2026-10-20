import struct
from pathlib import Path


UI_DIR = Path(__file__).resolve().parents[1] / "src" / "claude_china" / "desktop" / "ui"


def test_desktop_shortcut_icons_are_packaged_assets():
    assert (UI_DIR / "icon.ico").is_file()
    assert (UI_DIR / "icon.icns").is_file()


def test_windows_shortcut_icon_is_multi_image_ico():
    data = (UI_DIR / "icon.ico").read_bytes()

    reserved, icon_type, image_count = struct.unpack("<HHH", data[:6])

    assert reserved == 0
    assert icon_type == 1
    assert image_count >= 5


def test_macos_shortcut_icon_is_icns_with_retina_sizes():
    data = (UI_DIR / "icon.icns").read_bytes()

    magic, declared_size = struct.unpack(">4sI", data[:8])

    assert magic == b"icns"
    assert declared_size == len(data)
    assert b"ic09" in data  # 512x512 PNG entry
    assert b"ic10" in data  # 1024x1024 PNG entry
