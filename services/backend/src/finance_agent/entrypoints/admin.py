import argparse
import json
import os
from pathlib import Path

from finance_agent.adapters.database import Database
from finance_agent.settings import ROOT, Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "migrate"])
    args = parser.parse_args()
    root = Path(os.environ.get("FINANCE_ROOT", ROOT))
    config = Path(os.environ.get("FINANCE_CONFIG_FILE", root / ".runtime/config.json"))
    if args.command == "init":
        config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            print("Existing workspace configuration retained.")
        else:
            with os.fdopen(descriptor, "w") as output:
                json.dump({"callbacks": {}}, output)
            print(f"Workspace configuration saved to {config}.")
    settings = Settings.load()
    Database(settings.database).migrate(root / "services/backend/migrations")
    print("Database migrations applied.")


if __name__ == "__main__":
    main()
