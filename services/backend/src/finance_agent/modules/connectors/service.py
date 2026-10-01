import hashlib
import json
import os
import secrets
import time
import uuid
from urllib.parse import urlparse

from google_auth_oauthlib.flow import Flow

from finance_agent.modules.connectors.google import SCOPES, ConnectorError, GoogleAPI
from finance_agent.modules.connectors.vault import CredentialVault
from finance_agent.modules.tasks.service import Conflict, NotFound


class ConnectorService:
    def __init__(self, database, vault=None, api_factory=None):
        self.database = database
        self.vault = vault or CredentialVault()
        self.api_factory = api_factory or GoogleAPI
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get(
            "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8767/api/connectors/google/callback"
        )

    @property
    def configured(self):
        parsed = urlparse(self.redirect_uri)
        return bool(
            self.client_id
            and self.client_secret
            and (
                parsed.scheme == "https"
                or parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1"}
            )
            and parsed.path == "/api/connectors/google/callback"
        )

    def flow(self, verifier):
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=SCOPES,
            redirect_uri=self.redirect_uri,
            code_verifier=verifier,
        )

    def authorize(self, tenant, browser):
        if not self.configured:
            raise ConnectorError("google_not_configured")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        flow = self.flow(verifier)
        url, _ = flow.authorization_url(state=state, access_type="offline", prompt="consent")
        with self.database.transaction() as c:
            c.execute("DELETE FROM oauth_requests WHERE expires_at<?", (time.time(),))
            c.execute(
                "INSERT INTO oauth_requests VALUES (?,?,?,?,?)",
                (
                    hashlib.sha256(state.encode()).hexdigest(),
                    tenant,
                    hashlib.sha256(browser.encode()).hexdigest(),
                    self.vault.seal(verifier),
                    time.time() + 600,
                ),
            )
        return url

    def callback(self, state, code, browser):
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT * FROM oauth_requests WHERE state_hash=?",
                (hashlib.sha256(state.encode()).hexdigest(),),
            ).fetchone()
            if (
                not row
                or row["expires_at"] < time.time()
                or not secrets.compare_digest(
                    row["browser_hash"], hashlib.sha256(browser.encode()).hexdigest()
                )
            ):
                raise Conflict("Google 授权已过期或浏览器不匹配，请重新连接")
            c.execute("DELETE FROM oauth_requests WHERE state_hash=?", (row["state_hash"],))
        try:
            flow = self.flow(self.vault.open(row["verifier"]))
            flow.fetch_token(code=code, timeout=20)
            credentials = flow.credentials
            scopes = credentials.granted_scopes or credentials.scopes or []
            if not set(SCOPES).issubset(scopes):
                raise ConnectorError("insufficient_scopes")
            data = {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "expires_at": time.time() + 3000,
            }
            api = self.api_factory(data, lambda _: None, self.client_id, self.client_secret)
            try:
                account = api.get("gmail", "profile")["emailAddress"]
            finally:
                api.close()
            return self.store(row["tenant_id"], account, data, scopes)
        except ConnectorError:
            raise
        except Exception:
            raise ConnectorError("oauth_exchange_failed") from None

    def store(self, tenant, account, credentials, scopes=SCOPES):
        with self.database.transaction() as c:
            previous = c.execute(
                "SELECT * FROM connections WHERE tenant_id=? AND account=? AND provider='google'",
                (tenant, account),
            ).fetchone()
            identifier = previous["id"] if previous else str(uuid.uuid4())
            if previous and not credentials.get("refresh_token") and previous["credentials"]:
                credentials["refresh_token"] = self.vault.open(previous["credentials"]).get(
                    "refresh_token"
                )
            if not credentials.get("refresh_token"):
                raise ConnectorError("offline_access_missing")
            c.execute(
                "INSERT INTO connections(id,tenant_id,provider,account,status,scopes_json"
                ",credentials,created_at) "
                "VALUES (?,?,'google',?,'connected',?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "status='connected',scopes_json=excluded.scopes_json,credentials=excluded.credentials",
                (
                    identifier,
                    tenant,
                    account,
                    json.dumps(scopes),
                    self.vault.seal(credentials),
                    time.time(),
                ),
            )
        return {"id": identifier, "account": account, "status": "connected"}

    def list(self, tenant):
        with self.database.connect() as c:
            rows = [
                dict(row)
                for row in c.execute(
                    "SELECT id,provider,account,status,scopes_json,created_at,last_sync_a"
                    "t FROM connections WHERE tenant_id=? ORDER BY created_at",
                    (tenant,),
                )
            ]
        for row in rows:
            row["scopes"] = json.loads(row.pop("scopes_json"))
        return {"google_configured": self.configured, "connections": rows}

    def get(self, tenant, identifier):
        with self.database.connect() as c:
            row = c.execute(
                "SELECT * FROM connections WHERE id=? AND tenant_id=?", (identifier, tenant)
            ).fetchone()
        if not row:
            raise NotFound("Connection not found")
        if row["status"] != "connected":
            raise ConnectorError("needs_reconnect")
        return dict(row)

    def api(self, tenant, identifier):
        row = self.get(tenant, identifier)

        def save(credentials):
            with self.database.transaction() as c:
                if not c.execute(
                    "UPDATE connections SET credentials=? WHERE id=? AND tenant_id=? AND "
                    "status='connected'",
                    (self.vault.seal(credentials), identifier, tenant),
                ).rowcount:
                    raise ConnectorError("needs_reconnect")

        return self.api_factory(
            self.vault.open(row["credentials"]), save, self.client_id, self.client_secret
        )

    def mark_error(self, tenant, identifier, error):
        if error.code not in {"needs_reconnect", "permission_denied"}:
            return
        with self.database.transaction() as c:
            c.execute(
                "UPDATE connections SET status='needs_reconnect' WHERE id=? AND "
                "tenant_id=? AND status!='disconnected'",
                (identifier, tenant),
            )
            c.execute(
                "UPDATE agent_tasks SET status='needs_connection',error_code=?,next_at=NU"
                "LL WHERE tenant_id=? AND connection_id=? AND status='enabled'",
                (error.code, tenant, identifier),
            )

    def sync(self, tenant, identifier, resources):
        self.get(tenant, identifier)
        lease = secrets.token_hex(16)
        now = time.time()
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT created_at,sync_until FROM connections WHERE id=? AND "
                "tenant_id=? AND status='connected'",
                (identifier, tenant),
            ).fetchone()
            if not row:
                raise ConnectorError("needs_reconnect")
            if row["sync_until"] and row["sync_until"] > now:
                raise ConnectorError("sync_busy", 15)
            c.execute(
                "UPDATE connections SET sync_lease=?,sync_until=? WHERE id=?",
                (lease, now + 600, identifier),
            )
        api = None
        try:
            api = self.api(tenant, identifier)
            for resource in resources:
                if resource not in {"gmail", "calendar"}:
                    raise ValueError("Unsupported resource")
                with self.database.connect() as c:
                    cursor = c.execute(
                        "SELECT cursor FROM connector_cursors WHERE connection_id=? AND resource=?",
                        (identifier, resource),
                    ).fetchone()
                cursor, records = getattr(
                    api, "sync_" + ("mail" if resource == "gmail" else "calendar")
                )(cursor[0] if cursor else None, row["created_at"])
                with self.database.transaction() as c:
                    if not c.execute(
                        "SELECT 1 FROM connections WHERE id=? AND status='connected' AND "
                        "sync_lease=?",
                        (identifier, lease),
                    ).fetchone():
                        raise ConnectorError("needs_reconnect")
                    for record in records:
                        c.execute(
                            "INSERT OR IGNORE INTO connector_changes(connection_id,resour"
                            "ce,external_id,version,payload_json,created_at) VALUES "
                            "(?,?,?,?,?,?)",
                            (
                                identifier,
                                resource,
                                record["id"],
                                record["version"],
                                json.dumps(record),
                                now,
                            ),
                        )
                    c.execute(
                        "INSERT INTO connector_cursors VALUES (?,?,?,?) ON "
                        "CONFLICT(connection_id,resource) DO UPDATE SET "
                        "cursor=excluded.cursor,updated_at=excluded.updated_at",
                        (identifier, resource, cursor, now),
                    )
                    c.execute("UPDATE connections SET last_sync_at=? WHERE id=?", (now, identifier))
        except ConnectorError as error:
            self.mark_error(tenant, identifier, error)
            raise
        finally:
            if api:
                api.close()
            with self.database.transaction() as c:
                c.execute(
                    "UPDATE connections SET sync_lease=NULL,sync_until=NULL WHERE id=? "
                    "AND sync_lease=?",
                    (identifier, lease),
                )

    def read(self, tenant, identifier, mode="digest", timezone="UTC", resources=None):
        api = self.api(tenant, identifier)
        try:
            result = api.digest(time.time(), timezone, resources=resources)
            self.get(tenant, identifier)  # Disconnection racing a request invalidates its result.
            return result
        except ConnectorError as error:
            self.mark_error(tenant, identifier, error)
            raise
        finally:
            api.close()

    def search_mail(self, tenant, identifier, **filters):
        api = self.api(tenant, identifier)
        try:
            result = api.search_mail(**filters)
            self.get(tenant, identifier)
            return result
        except ConnectorError as error:
            self.mark_error(tenant, identifier, error)
            raise
        finally:
            api.close()

    def mail_detail(self, tenant, identifier, message_id, offset=0):
        api = self.api(tenant, identifier)
        try:
            result = api.mail(message_id, max_text=None)
            self.get(tenant, identifier)
            total = len(result["text"])
            result["text"] = result["text"][offset : offset + 4000]
            result["text_truncated"] = (
                result.get("text_source") == "snippet" or offset > 0 or offset + 4000 < total
            )
            result.update(
                offset=offset,
                total_characters=total,
                next_offset=offset + 4000 if offset + 4000 < total else None,
            )
            for key in ("subject", "from", "url"):
                result[key] = result[key][:1000]
            return result
        except ConnectorError as error:
            self.mark_error(tenant, identifier, error)
            raise
        finally:
            api.close()

    def disconnect(self, tenant, identifier):
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT credentials FROM connections WHERE id=? AND tenant_id=?",
                (identifier, tenant),
            ).fetchone()
            if not row:
                raise NotFound("Connection not found")
            c.execute(
                "UPDATE connections SET status='disconnected',credentials='',sync_lease=N"
                "ULL,sync_until=NULL WHERE id=?",
                (identifier,),
            )
            c.execute(
                "UPDATE agent_tasks SET status='needs_connection',next_at=NULL,error_code"
                "='needs_reconnect' WHERE connection_id=? AND tenant_id=? AND "
                "status='enabled'",
                (identifier, tenant),
            )
            c.execute(
                "UPDATE agent_task_runs SET status='cancelled',lease_token=NULL,lease_until=NULL "
                "WHERE task_id IN (SELECT id FROM agent_tasks "
                "WHERE connection_id=? AND tenant_id=?) "
                "AND status IN ('queued','retrying','running')",
                (identifier, tenant),
            )
            c.execute(
                "DELETE FROM connector_changes WHERE connection_id=? AND id NOT IN "
                "(SELECT change_id FROM agent_task_batches)",
                (identifier,),
            )
        # Local invalidation is unconditional, even if provider revocation fails.
        if row["credentials"]:
            import httpx

            try:
                data = self.vault.open(row["credentials"])
                httpx.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": data.get("refresh_token") or data["access_token"]},
                    timeout=10,
                    trust_env=False,
                )
            except Exception:
                pass
