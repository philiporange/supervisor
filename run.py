"""Run the supervisor service."""

import uvicorn

from supervisor.config import config

if __name__ == "__main__":
    uvicorn.run(
        "supervisor.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )
