import argparse
import time

from finance_agent.adapters.database import Database
from finance_agent.modules.connectors.service import ConnectorService
from finance_agent.modules.monitors.service import MonitorService
from finance_agent.modules.tasks.agent_service import AgentTaskService
from finance_agent.modules.tasks.health import service_heartbeat
from finance_agent.modules.tasks.service import TaskService
from finance_agent.settings import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.load()
    monitors = MonitorService(TaskService(Database(settings.database), settings.callbacks))
    agent_tasks = AgentTaskService(
        monitors.tasks.database, ConnectorService(monitors.tasks.database)
    )
    with service_heartbeat(monitors.tasks.database, "scheduler"):
        while True:
            monitors.tick()
            agent_tasks.tick()
            if args.once:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
