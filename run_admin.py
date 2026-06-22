from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "admin_backend.main:app",
        host=os.getenv("MEDIWRITER_HOST", "127.0.0.1"),
        port=int(os.getenv("MEDIWRITER_PORT", "8000")),
        reload=os.getenv("MEDIWRITER_RELOAD", "0") == "1",
    )
