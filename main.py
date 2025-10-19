"""Top-level thin launcher for backwards compatibility.

This file delegates to the package `usagi.main.run`. Keeping a small launcher
allows `python main.py <url>` to continue working while the package is
discoverable by Poetry for installation.
"""

from usagi.main import run


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python main.py <target_url>')
        sys.exit(1)
    run(sys.argv[1])
