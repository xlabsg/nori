import argparse
import logging
import time

from pydantic import ValidationError

from finance_agent.adapters.database import Database
from finance_agent.modules.agent.service import ChatService
from finance_agent.modules.analytics.calculations import analyze
from finance_agent.modules.analytics.schemas import AnalysisInput
from finance_agent.modules.callbacks.delivery import CallbackDispatcher
from finance_agent.modules.notifications.telegram import TelegramService
from finance_agent.modules.tasks.agent_worker import AgentTaskWorker
from finance_agent.modules.tasks.health import service_heartbeat
from finance_agent.modules.tasks.service import TaskService
from finance_agent.settings import Settings

logger = logging.getLogger(__name__)


def work_once(tasks):
    job = tasks.claim()
    if job is None:
        return False
    try:
        result = analyze(AnalysisInput.model_validate(job["input"]))
    except (ValidationError, ArithmeticError):
        tasks.finish(job["tenant_id"], job["id"], job["lease_token"], error_code="invalid_analysis")
    else:
        tasks.finish(job["tenant_id"], job["id"], job["lease_token"], result=result)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once", action="store_true", help="Process one task and callback then exit"
    )
    args = parser.parse_args()
    settings = Settings.load()
    database = Database(settings.database)
    tasks = TaskService(database, settings.callbacks)
    dispatcher = CallbackDispatcher(database, settings.callbacks)
    agent_dispatcher = CallbackDispatcher(database, settings.callbacks, agent_tasks=True)
    chat = ChatService(settings, tasks)
    agent_worker = AgentTaskWorker(chat.agent_tasks, chat)
    telegram = TelegramService(database)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with service_heartbeat(database, "worker"):
        while True:
            processed = work_once(tasks)
            processed = agent_worker.work_once() or processed
            dispatched = dispatcher.tick()
            dispatched = agent_dispatcher.tick() or dispatched
            dispatched = telegram.tick() or dispatched
            if args.once:
                return
            if not processed and not dispatched:
                time.sleep(1)


if __name__ == "__main__":
    main()
