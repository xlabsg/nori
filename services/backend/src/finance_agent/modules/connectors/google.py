"""Bounded, read-only Google API transport and resource normalization."""

import base64
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import quote

import httpx

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]


class MailHTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self.ignored = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored = True
        elif tag in {"br", "p", "div", "li", "tr"} and not self.ignored:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = False

    def handle_data(self, data):
        if not self.ignored:
            self.chunks.append(data)


class ConnectorError(Exception):
    def __init__(self, code="connector_unavailable", retry_after=30):
        self.code = code
        self.retry_after = min(max(retry_after, 1), 3600)
        super().__init__(code)


class GoogleAPI:
    def __init__(self, credentials, save, client_id, client_secret, client=None):
        self.credentials = credentials
        self.save = save
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = client or httpx.Client(timeout=20, trust_env=False)
        self.deadline = time.monotonic() + 90

    def close(self):
        self.client.close()

    def token(self):
        if self.credentials.get("expires_at", 0) > time.time() + 60:
            return self.credentials["access_token"]
        if not self.credentials.get("refresh_token"):
            raise ConnectorError("needs_reconnect")
        try:
            response = self.client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.credentials["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code in {400, 401}:
                raise ConnectorError("needs_reconnect")
            if response.status_code != 200:
                raise ConnectorError()
            data = response.json()
            self.credentials.update(
                access_token=data["access_token"], expires_at=time.time() + int(data["expires_in"])
            )
            self.save(self.credentials)
            return self.credentials["access_token"]
        except (httpx.HTTPError, KeyError, ValueError):
            raise ConnectorError() from None

    def get(self, resource, path, params=None):
        if time.monotonic() >= self.deadline:
            raise ConnectorError("sync_timeout")
        roots = {
            "gmail": "https://gmail.googleapis.com/gmail/v1/users/me/",
            "calendar": "https://www.googleapis.com/calendar/v3/",
        }
        try:
            response = self.client.get(
                roots[resource] + path,
                params=params,
                headers={"Authorization": "Bearer " + self.token()},
            )
            if response.status_code == 401:
                raise ConnectorError("needs_reconnect")
            if response.status_code in {404, 410}:
                raise ConnectorError("cursor_expired")
            if response.status_code == 429:
                delay = response.headers.get("Retry-After", "60")
                raise ConnectorError("rate_limited", int(delay) if delay.isdigit() else 60)
            if response.status_code == 403:
                raise ConnectorError(self.permission_error(response, resource))
            if response.status_code != 200:
                raise ConnectorError("connector_unavailable")
            return response.json()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ConnectorError() from None

    @staticmethod
    def permission_error(response, resource):
        # Only expose recognized reason codes, never provider messages or account details.
        try:
            error = response.json().get("error", {})
            if not isinstance(error, dict):
                return "permission_denied"
            reasons = {
                item.get("reason")
                for key in ("errors", "details")
                for item in error.get(key, [])
                if isinstance(item, dict) and isinstance(item.get("reason"), str)
            }
        except (ValueError, AttributeError, TypeError):
            return "permission_denied"
        if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
            return resource + "_api_disabled"
        if reasons & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
            return "insufficient_scopes"
        if "domainPolicy" in reasons:
            return "domain_policy_denied"
        if reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
            return "rate_limited"
        return "permission_denied"

    def pages(self, resource, path, params=None):
        params = dict(params or {})
        pages = []
        # All pages must finish before cursor commit. Excessive backlogs are visible failures.
        for _ in range(10):
            data = self.get(resource, path, params)
            pages.append(data)
            if not data.get("nextPageToken"):
                return pages
            params["pageToken"] = data["nextPageToken"]
        raise ConnectorError("sync_backlog_limit")

    def mail(self, identifier, max_text=16000):
        data = self.get("gmail", "messages/" + quote(identifier, safe=""), {"format": "full"})
        headers = {
            h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])
        }

        def text(part, mime="text/plain"):
            if part.get("mimeType") == mime and part.get("body", {}).get("data"):
                encoded = part["body"]["data"]
                return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode(
                    "utf-8", errors="replace"
                )
            return "\n".join(value for p in part.get("parts", []) if (value := text(p, mime)))

        body = text(data.get("payload", {}))
        source = "plain"
        if not body:
            html = text(data.get("payload", {}), "text/html")
            parser = MailHTMLText()
            parser.feed(html)
            body = "".join(parser.chunks).strip()
            source = "html" if body else "snippet"
        body = body or data.get("snippet", "")
        return {
            "id": data["id"],
            "version": str(data.get("internalDate", "0")),
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "received_at": int(data.get("internalDate", "0")) / 1000,
            "text": body[:max_text] if max_text is not None else body,
            "text_source": source,
            "text_truncated": source == "snippet"
            or (max_text is not None and len(body) > max_text),
            "url": "https://mail.google.com/mail/u/0/#all/" + data["id"],
            "labels": data.get("labelIds", []),
        }

    def search_mail(self, *, unread=False, sender=None, after=None, before=None, limit=20):
        query = ["in:inbox"]
        if unread:
            query.append("is:unread")
        if sender:
            query.append("from:" + sender)
        if after:
            query.append("after:" + str(int(after)))
        if before:
            query.append("before:" + str(int(before)))
        data = self.get("gmail", "messages", {"q": " ".join(query), "maxResults": limit})
        records = [self.mail(item["id"]) for item in data.get("messages", [])]
        return {
            "gmail": records,
            "calendar": [],
            "truncated": bool(data.get("nextPageToken")),
            "has_more": bool(data.get("nextPageToken")),
        }

    def upcoming(self, now, horizon=86400):
        from datetime import timedelta

        start = datetime.fromtimestamp(now, UTC)
        return [
            self.event(event)
            for page in self.pages(
                "calendar",
                "calendars/primary/events",
                {
                    "timeMin": start.isoformat(),
                    "timeMax": (start + timedelta(seconds=horizon)).isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 250,
                },
            )
            for event in page.get("items", [])
        ]

    def sync_mail(self, cursor, since):
        if not cursor:
            # Initialize before listing so arrivals during the baseline fetch remain discoverable.
            current = self.get("gmail", "profile")["historyId"]
            identifiers = {
                m["id"]
                for page in self.pages(
                    "gmail",
                    "messages",
                    {
                        "q": f"after:{int(since)} in:inbox",
                        "maxResults": 100,
                    },
                )
                for m in page.get("messages", [])
            }
        else:
            try:
                pages = self.pages(
                    "gmail",
                    "history",
                    {"startHistoryId": cursor, "historyTypes": "messageAdded", "maxResults": 100},
                )
            except ConnectorError as error:
                if error.code != "cursor_expired":
                    raise
                return self.sync_mail(None, since)
            current = pages[-1].get("historyId", cursor)
            identifiers = {
                m["message"]["id"]
                for p in pages
                for h in p.get("history", [])
                for m in h.get("messagesAdded", [])
            }
        if len(identifiers) > 200:
            raise ConnectorError("sync_backlog_limit")
        records = []
        for identifier in sorted(identifiers):
            try:
                item = self.mail(identifier)
            except ConnectorError as error:
                if error.code == "cursor_expired":  # Mail deleted between discovery and fetch.
                    continue
                raise
            if "INBOX" in item["labels"] and item["received_at"] >= since:
                records.append(item)
        return str(current), records

    def sync_calendar(self, cursor, since):
        params = {"maxResults": 250, "showDeleted": "true"}
        if cursor:
            params["syncToken"] = cursor
        try:
            pages = self.pages("calendar", "calendars/primary/events", params)
        except ConnectorError as error:
            if cursor and error.code == "cursor_expired":
                return self.sync_calendar(None, since)
            raise
        records = [self.event(e) for p in pages for e in p.get("items", [])]
        if cursor:
            for record in records:
                if record["status"] == "cancelled" and not record["updated"]:
                    record["updated"] = datetime.now(UTC).isoformat()
                    record["version"] = "cancelled"
        return pages[-1]["nextSyncToken"], records

    @staticmethod
    def event(data):
        return {
            "id": data["id"],
            "version": data.get("updated", data.get("etag", "initial")),
            "title": data.get("summary", ""),
            "status": data.get("status", "confirmed"),
            "location": data.get("location", "")[:1000],
            "meeting_url": data.get("hangoutLink", ""),
            "start": data.get("start", {}),
            "end": data.get("end", {}),
            "description": data.get("description", "")[:8000],
            "url": data.get("htmlLink", "https://calendar.google.com/calendar/u/0/r"),
            "updated": data.get("updated", ""),
        }

    def digest(self, now, timezone="UTC", resources=None):
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        resources = set(resources or ["gmail", "calendar"])
        local = datetime.fromtimestamp(now, ZoneInfo(timezone))
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        events = (
            [
                self.event(e)
                for p in self.pages(
                    "calendar",
                    "calendars/primary/events",
                    {
                        "timeMin": start.isoformat(),
                        "timeMax": (start + timedelta(days=1)).isoformat(),
                        "singleEvents": "true",
                        "orderBy": "startTime",
                        "maxResults": 250,
                    },
                )
                for e in p.get("items", [])
            ]
            if "calendar" in resources
            else []
        )
        mail_ids = (
            [
                m["id"]
                for p in self.pages(
                    "gmail",
                    "messages",
                    {
                        "q": f"after:{int(now - 86400)} in:inbox",
                        "maxResults": 100,
                    },
                )
                for m in p.get("messages", [])
            ]
            if "gmail" in resources
            else []
        )
        mails = [self.mail(identifier) for identifier in mail_ids[:100]]
        return {
            "gmail": mails[:100],
            "calendar": events[:100],
            "mail_window_hours": 24,
            "calendar_date": start.date().isoformat(),
            "timezone": timezone,
            "truncated": len(mail_ids) > 100 or len(events) > 100,
        }
