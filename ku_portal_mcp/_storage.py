"""Shared helpers for caching session state on disk securely.

Session files hold authentication tokens/cookies that are equivalent to login
credentials, so they must not be world-readable. We write atomically (temp file
+ os.replace) with 0600 permissions inside a 0700 directory.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_secure_json(path: Path, data: Any) -> None:
    """Atomically write JSON to ``path`` with owner-only (0600) permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Best-effort tighten an existing dir created before this code shipped.
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
