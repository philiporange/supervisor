"""
Entry point for running supervisor via `python -m supervisor`.

Starts the FastAPI server with uvicorn.
"""

import uvicorn

from .config import HOST, PORT


def main():
    """Run the supervisor server."""
    uvicorn.run(
        "supervisor.main:app",
        host=HOST,
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
