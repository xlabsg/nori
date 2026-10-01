import re
import secrets
import time
import uuid

import httpx
from pydantic import Field, SecretStr

from finance_agent.modules.analytics.schemas import StrictModel
from finance_agent.modules.connectors.vault import CredentialVault
from finance_agent.modules.notifications.preferences import PreferenceService, next_allowed


class TelegramConfig(StrictModel):
    bot_token: SecretStr
    chat_id: str = Field(pattern=r"^-?\d{1,20}$")


class TelegramError(Exception):
    def __init__(self, code, retry_after=30):
        self.code = code
        self.retry_after = min(max(retry_after, 1), 3600)
        super().__init__(code)


class TelegramService:
    def __init__(self, database, vault=None, client_factory=None):
        self.database = database
        self.vault = vault or CredentialVault()
        self.client_factory = client_factory or (
            lambda: httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
        )

    def status(self, tenant):
        with self.database.connect() as c:
            row = c.execute(
                "SELECT enabled FROM notification_channels WHERE tenant_id=?", (tenant,)
            ).fetchone()
            delivery = c.execute(
                "SELECT status,error_code,sent_at FROM notification_outbox WHERE tenant_id=? "
                "ORDER BY rowid DESC LIMIT 1",
                (tenant,),
            ).fetchone()
        return {
            "configured": bool(row and row[0]),
            "last_delivery": dict(delivery) if delivery else None,
        }

    def configure(self, tenant, request):
        token = request.bot_token.get_secret_value().strip()
        if not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,220}", token):
            raise TelegramError("telegram_invalid_config")
        generation = secrets.token_hex(16)
        credentials = self.vault.seal({"bot_token": token, "chat_id": request.chat_id})
        with self.database.transaction() as c:
            c.execute(
                "INSERT INTO notification_channels VALUES (?,?,?,1,?) ON CONFLICT(tenant_id) "
                "DO UPDATE SET credentials=excluded.credentials,generation=excluded.generation,"
                "enabled=1,updated_at=excluded.updated_at",
                (tenant, credentials, generation, time.time()),
            )
            c.execute(
                "UPDATE notification_outbox SET status='cancelled',lease_token=NULL WHERE "
                "tenant_id=? AND status IN ('pending','sending')",
                (tenant,),
            )
        return self.status(tenant)

    def disconnect(self, tenant):
        with self.database.transaction() as c:
            c.execute("DELETE FROM notification_channels WHERE tenant_id=?", (tenant,))
            c.execute(
                "UPDATE notification_outbox SET status='cancelled',lease_token=NULL WHERE "
                "tenant_id=? AND status IN ('pending','sending')",
                (tenant,),
            )

    @staticmethod
    def enqueue(c, tenant, identifier, text, now):
        channel = c.execute(
            "SELECT generation FROM notification_channels WHERE tenant_id=? AND enabled=1",
            (tenant,),
        ).fetchone()
        if channel:
            # Telegram has a 4096-character limit. One bounded summary, never split duplicates.
            summary = text if len(text) <= 3500 else text[:3400] + "\n…完整结果请查看工作区原对话。"
            c.execute(
                "INSERT OR IGNORE INTO notification_outbox(id,tenant_id,generation,text,next_at) "
                "VALUES (?,?,?,?,?)",
                (identifier, tenant, channel[0], summary, now),
            )
        return bool(channel)

    def test(self, tenant):
        with self.database.transaction() as c:
            if not self.enqueue(
                c, tenant, str(uuid.uuid4()), "Assistant 通知测试：Telegram 已接入。", time.time()
            ):
                raise TelegramError("telegram_not_configured")
        return {"queued": True}

    def send(self, credentials, text):
        # Never emit HTTP request URLs: the Telegram token is part of its endpoint.
        try:
            with self.client_factory() as client:
                response = client.post(
                    "https://api.telegram.org/bot" + credentials["bot_token"] + "/sendMessage",
                    json={
                        "chat_id": credentials["chat_id"],
                        "text": text,
                        "link_preview_options": {"is_disabled": True},
                    },
                )
            data = response.json()
            if not isinstance(data, dict):
                raise TelegramError("telegram_unavailable")
        except (httpx.HTTPError, ValueError):
            raise TelegramError("telegram_unavailable") from None
        if response.status_code == 429:
            delay = data.get("parameters", {}).get("retry_after", 60)
            raise TelegramError("telegram_rate_limited", delay if isinstance(delay, int) else 60)
        if response.status_code in {400, 401, 403}:
            raise TelegramError("telegram_access_denied")
        if response.status_code != 200 or not data.get("ok"):
            raise TelegramError("telegram_unavailable")

    def tick(self, now=None):
        now = time.time() if now is None else now
        with self.database.transaction() as c:
            c.execute(
                "UPDATE notification_outbox SET status='failed',error_code='lease_expired' "
                "WHERE status='sending' AND lease_until<? AND attempts>=5",
                (now,),
            )
            row = c.execute(
                "SELECT o.*,ch.credentials FROM notification_outbox o JOIN "
                "notification_channels ch "
                "ON ch.tenant_id=o.tenant_id AND ch.generation=o.generation AND ch.enabled=1 "
                "WHERE o.attempts<5 AND ((o.status='pending' AND o.next_at<=?) OR "
                "(o.status='sending' AND o.lease_until<?)) ORDER BY o.next_at LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            lease = secrets.token_hex(16)
            c.execute(
                "UPDATE notification_outbox SET status='sending',lease_token=?,lease_until=?,"
                "attempts=attempts+1 WHERE id=?",
                (lease, now + 60, row["id"]),
            )
        preferences = PreferenceService(self.database).get(row["tenant_id"])
        allowed = next_allowed(preferences, now)
        error = None
        if allowed <= now:
            try:
                self.send(self.vault.open(row["credentials"]), row["text"])
            except TelegramError as exc:
                error = exc
        with self.database.transaction() as c:
            if allowed > now:
                c.execute(
                    "UPDATE notification_outbox SET status='pending',next_at=?,attempts=attempts-1,"
                    "lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?",
                    (allowed, row["id"], lease),
                )
            elif error:
                terminal = row["attempts"] >= 4 or error.code == "telegram_access_denied"
                c.execute(
                    "UPDATE notification_outbox SET "
                    "status=?,error_code=?,next_at=?,lease_token=NULL,"
                    "lease_until=NULL WHERE id=? AND lease_token=?",
                    (
                        "failed" if terminal else "pending",
                        error.code,
                        now + error.retry_after * 2 ** row["attempts"],
                        row["id"],
                        lease,
                    ),
                )
            else:
                c.execute(
                    "UPDATE notification_outbox SET status='sent',sent_at=?,error_code=NULL,"
                    "lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?",
                    (now, row["id"], lease),
                )
        return True
