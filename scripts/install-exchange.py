"""Install pinned official CLIs locally. Run explicitly; unavailable to the model."""

import argparse
import hashlib
import io
import platform
import subprocess
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BINANCE_VERSION = "2.1.1"
CHECKSUMS = {
    "aarch64-apple-darwin": "380f76a300d601314cf8df7751b9ec7bd3f8c57b9817c3df50432e2a36c3f400",
    "aarch64-unknown-linux-gnu": "0c3786a72fe63f581c389dace7a0f8139ed9c401d0cb9453980f4dc2fa4a87ff",
    "x86_64-apple-darwin": "45772f48dc00e8743b2f6f30ec3db3d3904e0862d6b8e4c10bab28f4ef91598c",
    "x86_64-unknown-linux-gnu": "6b836a24f281abf590988207b0d19d4933971ca66dcf45a9e255cdc237c4deee",
}


def install(exchange):
    if exchange == "okx":
        subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--prefix", str(ROOT / "services/exchange-tools")],
            check=True,
        )
        return
    machine = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64"}.get(platform.machine())
    system = {"Darwin": "apple-darwin", "Linux": "unknown-linux-gnu"}.get(platform.system())
    target = f"{machine}-{system}"
    if target not in CHECKSUMS:
        raise SystemExit("Supported platforms: macOS/Linux on ARM64 or x86_64")
    asset = f"binance-cli-{target}.tar.xz"
    url = f"https://github.com/binance/binance-cli/releases/download/v{BINANCE_VERSION}/{asset}"
    with urlopen(url, timeout=30) as response:
        data = response.read(50_000_001)
    if len(data) > 50_000_000 or hashlib.sha256(data).hexdigest() != CHECKSUMS[target]:
        raise SystemExit("Official release checksum mismatch")
    destination = ROOT / ".runtime/exchange-bin"
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        archive.extractall(destination, filter="data")
    print(f"Installed Binance CLI {BINANCE_VERSION} for {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exchange", choices=["binance", "okx"])
    install(parser.parse_args().exchange)
