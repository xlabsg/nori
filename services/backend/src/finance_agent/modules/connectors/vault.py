"""Local encrypted credential storage; key is outside the repository."""

import fcntl
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


class CredentialVault:
    def __init__(self, key_path=None):
        self.key_path = Path(
            key_path
            or os.environ.get(
                "FINANCE_CREDENTIAL_KEY_FILE",
                Path.home() / ".local/share/finance-agent/credential.key",
            )
        )

    def cipher(self):
        self.key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.key_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(Fernet.generate_key())
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            key = handle.read()
            fcntl.flock(handle, fcntl.LOCK_UN)
        return Fernet(key)

    def seal(self, data):
        return self.cipher().encrypt(json.dumps(data).encode()).decode()

    def open(self, data):
        return json.loads(self.cipher().decrypt(data.encode()))
