from __future__ import annotations

import os
import re
from pathlib import Path


DEFAULT_ENV_FILE = Path(__file__).resolve().with_name(".env.admin")
_ENV_LOADED = False
_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_mediwriter_env() -> None:
    """Load local runtime env without overriding already exported values."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    env_path = Path(os.getenv("MEDIWRITER_ENV_FILE", str(DEFAULT_ENV_FILE))).expanduser()
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_PATTERN.match(key):
            continue
        os.environ.setdefault(key, _strip_quotes(value.strip()))


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
