"""``python -m slappyengine.exporter`` — thin shim over ``slap export``.

Any argv passed here is forwarded verbatim to :func:`slappyengine.cli.main`
with an ``export`` subcommand prepended, so
``python -m slappyengine.exporter <args...>`` is equivalent to
``slap export <args...>``.
"""
from __future__ import annotations

import sys

from slappyengine import cli


def main() -> None:
    sys.argv = [sys.argv[0], "export", *sys.argv[1:]]
    cli.main()


if __name__ == "__main__":
    main()
