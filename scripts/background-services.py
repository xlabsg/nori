#!/usr/bin/env python3
"""Manage this workspace's macOS login services; plists contain paths, never secrets."""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = {
    "api": [
        "-m",
        "uvicorn",
        "finance_agent.entrypoints.api:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8767",
        "--no-access-log",
    ],
    "worker": ["-m", "finance_agent.entrypoints.worker"],
    "scheduler": ["-m", "finance_agent.entrypoints.scheduler"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["install", "status", "restart", "uninstall"])
    parser.add_argument("--model-env", type=Path)
    args = parser.parse_args()
    folder = Path.home() / "Library/LaunchAgents"
    logs = ROOT / ".runtime/services"
    domain = f"gui/{os.getuid()}"
    if args.command == "install":
        if not (ROOT / ".venv/bin/python").exists():
            raise SystemExit("Run uv sync first")
        if not args.model_env or not args.model_env.resolve().is_file():
            raise SystemExit("--model-env must identify your private model env file")
        folder.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, command in JOBS.items():
        label = f"com.xlabsg.finance-agent.{name}"
        path = folder / (label + ".plist")
        target = domain + "/" + label
        if args.command == "install":
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(Path.home()),
                "FINANCE_ROOT": str(ROOT),
                "FINANCE_MODEL_ENV_FILE": str(args.model_env.resolve()),
            }
            config = {
                "Label": label,
                "ProgramArguments": [str(ROOT / ".venv/bin/python"), *command],
                "WorkingDirectory": str(ROOT),
                "EnvironmentVariables": environment,
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 10,
                "StandardOutPath": str(logs / (name + ".out.log")),
                "StandardErrorPath": str(logs / (name + ".err.log")),
            }
            path.write_bytes(plistlib.dumps(config))
            path.chmod(0o600)
            subprocess.run(
                ["launchctl", "bootout", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
            print(name + ": installed")
        elif args.command == "restart":
            subprocess.run(["launchctl", "kickstart", "-k", target], check=True)
        elif args.command == "uninstall":
            subprocess.run(["launchctl", "bootout", target], check=False)
            path.unlink(missing_ok=True)
            print(name + ": removed")
        else:
            response = subprocess.run(
                ["launchctl", "print", target], capture_output=True, text=True
            )
            if response.returncode:
                print(name + ": not installed")
            else:
                for line in response.stdout.splitlines():
                    if any(
                        line.startswith("\t" + field)
                        for field in ("state =", "pid =", "last exit code =")
                    ):
                        print(name + ": " + line.strip())


if __name__ == "__main__":
    main()
