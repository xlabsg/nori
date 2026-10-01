"""Start the local API, worker and scheduler; stop children together on exit."""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "PI_PROVIDER",
    "PI_MODEL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".runtime")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            parser.error("port is already occupied; use --port with another port")
    env = os.environ.copy()
    values = dotenv_values(ROOT / ".env")
    for key in ENV_KEYS:
        if values.get(key):
            env.setdefault(key, values[key])
    data = args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update(
        FINANCE_DATABASE=str(data / "finance.db"), FINANCE_CONFIG_FILE=str(data / "config.json")
    )
    subprocess.run(
        [sys.executable, "-m", "finance_agent.entrypoints.admin", "init"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    runtime = ROOT / "services/agent-runtime"
    if not (runtime / "node_modules/@earendil-works/pi-agent-core").exists():
        subprocess.run(["npm", "ci", "--ignore-scripts"], cwd=runtime, check=True)
    commands = [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "finance_agent.entrypoints.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        [sys.executable, "-m", "finance_agent.entrypoints.worker"],
        [sys.executable, "-m", "finance_agent.entrypoints.scheduler"],
    ]
    children = []

    def stop(_signum=None, _frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Starting local workspace: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True))
        while True:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError("A workspace service stopped; see service output above")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    main()
