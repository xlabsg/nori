import hashlib
import hmac
import http.client
import ipaddress
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit

from finance_agent.modules.tasks.service import new_id


def signed_headers(secret, body, timestamp):
    signature = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return {"X-Finance-Timestamp": str(timestamp), "X-Finance-Signature": f"sha256={signature}"}


def public_target(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Callback requires HTTPS port 443 without credentials or fragment")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Callback destination must resolve only to public addresses")
    return parsed, addresses[0][4][0]


def send_webhook(url, body, headers):
    parsed, address = public_target(url)

    class PinnedConnection(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((address, 443), timeout=10)
            try:
                self.sock = ssl.create_default_context().wrap_socket(
                    raw, server_hostname=parsed.hostname
                )
            except BaseException:
                raw.close()
                raise

    connection = PinnedConnection(parsed.hostname, timeout=10)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    try:
        connection.request("POST", path, body, {**headers, "Content-Type": "application/json"})
        response = connection.getresponse()
        # Do not follow redirects or persist response bodies, which may contain private content.
        return response.status
    finally:
        connection.close()


class CallbackDispatcher:
    def __init__(self, database, callbacks, transport=send_webhook, agent_tasks=False):
        self.database = database
        self.callbacks = callbacks
        self.transport = transport
        self.table = "agent_deliveries" if agent_tasks else "deliveries"
        self.agent_tasks = agent_tasks

    def tick(self, now=None):
        now = time.time() if now is None else now
        token = new_id()
        with self.database.transaction() as connection:
            row = connection.execute(
                (
                    "SELECT d.* FROM agent_deliveries d "
                    if self.agent_tasks
                    else "SELECT d.*,e.payload_json FROM deliveries d "
                    "JOIN events e ON e.id=d.event_id "
                )
                + "WHERE (d.status='pending' AND d.next_at<=?) OR "
                "(d.status='delivering' AND d.lease_until<=?) ORDER BY d.created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if row is None:
                return False
            if row["attempts"] >= 8 or now - row["created_at"] >= 86400:
                connection.execute(
                    f"UPDATE {self.table} SET status='dead_letter',last_error='retry_exhausted',"
                    "lease_token=NULL,lease_until=NULL WHERE event_id=?",
                    (row["event_id"],),
                )
                return True
            connection.execute(
                f"UPDATE {self.table} SET status='delivering',attempts=attempts+1,"
                "lease_token=?,lease_until=? WHERE event_id=?",
                (token, now + 30, row["event_id"]),
            )
        config = self.callbacks.get(row["tenant_id"])
        body = row["payload_json"].encode()
        error = None
        revoked = config is None
        if revoked:
            error = "endpoint_revoked"
        else:
            headers = signed_headers(config["secret"], body, int(now))
            headers["X-Finance-Event-Id"] = row["event_id"]
            try:
                status_code = self.transport(config["url"], body, headers)
                if not 200 <= status_code < 300:
                    error = f"http_{status_code}"
            except (OSError, ValueError, http.client.HTTPException):
                error = "transport_failed"
        attempts = row["attempts"] + 1
        state = "delivered" if error is None else "pending"
        if error and (revoked or attempts >= 8):
            state = "dead_letter"
        delay = min(3600, 5 * 2**attempts) + secrets.randbelow(5)
        with self.database.transaction() as connection:
            connection.execute(
                f"UPDATE {self.table} SET status=?,next_at=?,last_error=?,"
                "lease_token=NULL,lease_until=NULL WHERE event_id=? AND lease_token=?",
                (state, now + delay, error, row["event_id"], token),
            )
        return True

    def list(self, tenant):
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    f"SELECT event_id,status,attempts,next_at,last_error FROM {self.table} "
                    "WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100",
                    (tenant,),
                )
            ]
