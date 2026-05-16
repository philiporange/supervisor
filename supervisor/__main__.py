"""
Entry point for running supervisor via `python -m supervisor` or the
`supervisor` console script.

Delegates to the CLI parser which handles subcommands (status, start, stop,
etc.) and falls back to starting the server when no subcommand is given.
"""

from .cli import main

if __name__ == "__main__":
    main()
