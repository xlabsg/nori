"""Check Git publication candidates without printing matched secret values."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Google OAuth secret": re.compile(rb"GOCSPX-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "AWS access key": re.compile(rb"AKIA[A-Z0-9]{16}"),
}


def scan(data):
    return [
        (label, data[: match.start()].count(b"\n") + 1)
        for label, pattern in PATTERNS.items()
        for match in pattern.finditer(data)
    ]


def main():
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    failures = []
    for name in set(result.stdout.split(b"\0")) - {b""}:
        path = ROOT / name.decode()
        if path.is_symlink() or not path.is_file():
            continue
        for label, line in scan(path.read_bytes()):
            failures.append(f"{path.relative_to(ROOT)}:{line}: {label}")
    if failures:
        print("Potential secrets in publication candidates:")
        print("\n".join(sorted(failures)))
        raise SystemExit(1)
    print("No known secret patterns in Git publication candidates.")


if __name__ == "__main__":
    main()
