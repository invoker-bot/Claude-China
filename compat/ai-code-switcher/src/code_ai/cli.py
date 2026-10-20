"""Keep old commands and desktop shortcuts working during the rename."""

import sys


def main():
    from claude_china.cli import app

    # Windows desktop shortcuts use pythonw.exe, which has no console streams.
    if sys.stderr is not None:
        print(
            "WARNING: ai-code-switcher and code-ai are deprecated. "
            "Install with: python -m pip install --upgrade claude-china "
            "and use claudec instead of code-ai.",
            file=sys.stderr,
        )
    return app(prog_name="claudec")


if __name__ == "__main__":
    main()
