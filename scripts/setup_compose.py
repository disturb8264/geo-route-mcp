"""Create local Docker Compose directories and a private gateway token."""

import os
import secrets
from pathlib import Path


root = Path(__file__).resolve().parents[1]
secret_dir = root / "secrets"
secret_dir.mkdir(mode=0o700, exist_ok=True)
(root / "data" / "tile-cache").mkdir(parents=True, exist_ok=True)
token_path = secret_dir / "geo_route_token"
try:
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(f"Keeping existing token: {token_path}")
else:
    with os.fdopen(fd, "w", encoding="ascii") as token_file:
        token_file.write(secrets.token_hex(32) + "\n")
    print(f"Created token: {token_path}")
