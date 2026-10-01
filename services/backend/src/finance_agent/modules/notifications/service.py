import time

from finance_agent.modules.tasks.service import NotFound


class NotificationService:
    def __init__(self, database):
        self.database = database

    def list(self, tenant):
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,event_id,task_id,title,created_at,read_at FROM "
                    "notifications WHERE tenant_id=? "
                    "UNION ALL SELECT id,run_id AS event_id,task_id,title,created_at,read"
                    "_at FROM agent_notifications "
                    "WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100",
                    (tenant, tenant),
                )
            ]

    def mark_read(self, tenant, notification_id):
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE tenant_id=? AND id=?",
                (time.time(), tenant, notification_id),
            )
            if not cursor.rowcount:
                cursor = connection.execute(
                    "UPDATE agent_notifications SET read_at=COALESCE(read_at,?) WHERE "
                    "tenant_id=? AND id=?",
                    (time.time(), tenant, notification_id),
                )
                if not cursor.rowcount:
                    raise NotFound("Notification not found")
