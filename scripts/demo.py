"""Create an isolated synthetic conversation for screenshots; never use live data."""

import argparse
import json
import time
from pathlib import Path

from finance_agent.adapters.database import Database
from finance_agent.settings import ROOT

MESSAGE = """这是用于开源预览的虚构数据，未连接真实邮件或日历账号。

### 今日工作简报

| 来源 | 示例内容 | 关注点 |
| --- | --- | --- |
| 邮件 | 项目例会材料已更新 | 会前阅读附件 |
| 邮件 | 研究报告发布通知 | 留待本周整理 |
| 日历 | 10:00 项目例会 | 提前准备讨论要点 |

**可以交给助手持续跟进**

- 每天早上汇总邮件和日程，在提醒收件箱查看结果。
- 按你指定的范围检查变化，重要更新通过 Telegram 提醒。
- 在日历事项开始前提醒，或按需使用右侧 Linux 桌面。

这是静态演示对话，没有读取账号或创建真实后台任务。"""


ENGLISH_MESSAGE = """
Synthetic data for this open-source preview. No real mail or calendar account is connected.

### Today’s work brief

| Source | Example update | Follow-up |
| --- | --- | --- |
| Mail | Team meeting materials updated | Read the attachment before the meeting |
| Mail | Research report published | Review later this week |
| Calendar | 10:00 team meeting | Prepare the discussion points |

**Work Nori can follow up on**

- Summarize mail and calendar each morning; review results in the reminder inbox.
- Check for changes within your requested scope and send important updates to Telegram.
- Remind you before calendar events, or use the Linux desktop when needed.

This is a static preview conversation. No accounts were read or background tasks created."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".runtime/demo")
    parser.add_argument("--language", choices=["en", "zh-CN"], default="zh-CN")
    args = parser.parse_args()
    english = args.language == "en"
    folder = args.data_dir.resolve()
    if folder == (ROOT / ".runtime").resolve():
        parser.error("demo must use an isolated directory")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / "finance.db"
    if path.exists():
        parser.error("destination database already exists; choose a fresh directory")
    database = Database(path)
    database.migrate(ROOT / "services/backend/migrations")
    now = time.time()
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, tenant_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "demo-preview",
                "local",
                "Daily work brief · Synthetic preview"
                if english
                else "日常工作简报 · 虚构数据演示",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO chat_runs "
            "(id, conversation_id, request_id, request_hash, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("demo-run", "demo-preview", "demo", "demo", "completed", now),
        )
        for kind, text in [
            (
                "user",
                "I want a daily mail and calendar brief. Show me the workspace with synthetic data."
                if english
                else "我想让你每天汇总邮件和日程，先用虚构数据展示一下工作区。",
            ),
            ("assistant", ENGLISH_MESSAGE if english else MESSAGE),
        ]:
            conn.execute(
                "INSERT INTO chat_events "
                "(conversation_id, run_id, type, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "demo-preview",
                    "demo-run",
                    kind,
                    json.dumps({"text": text}, ensure_ascii=False),
                    now,
                ),
            )
    print("Synthetic conversation created. No connectors, model calls or tasks were created.")
    print(f"Preview: uv run python scripts/dev.py --port 8768 --data-dir {folder}")


if __name__ == "__main__":
    main()
