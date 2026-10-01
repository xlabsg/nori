"""Authenticated noVNC access and bounded visual actions on the same Linux desktop."""

import base64
import time
import uuid
from typing import Literal

from pydantic import Field

from finance_agent.modules.analytics.schemas import StrictModel
from finance_agent.modules.execution.terminal import TerminalUnavailable


class DesktopAction(StrictModel):
    action: Literal["screenshot", "click", "double_click", "move", "scroll", "type", "key"]
    x: int = Field(default=0, ge=0, lt=1280)
    y: int = Field(default=0, ge=0, lt=800)
    text: str = Field(default="", max_length=4000)
    key: Literal[
        "Return",
        "Tab",
        "Escape",
        "BackSpace",
        "Delete",
        "Home",
        "End",
        "Up",
        "Down",
        "Left",
        "Right",
        "ctrl+l",
        "ctrl+a",
        "ctrl+c",
        "ctrl+v",
        "ctrl+w",
        "alt+F4",
        "super",
    ] = "Return"
    direction: Literal["up", "down"] = "down"
    clicks: int = Field(default=3, ge=1, le=10)


class DesktopService:
    def __init__(self, terminal):
        self.terminal = terminal

    def endpoint(self, tenant, conversation):
        self.terminal.authorize(tenant, conversation)
        item = self.terminal.inspect(self.terminal.name(tenant, conversation))
        if not item or not item["State"]["Running"]:
            raise TerminalUnavailable("Desktop stopped")
        ports = item["NetworkSettings"]["Ports"].get("6080/tcp")
        if not ports or ports[0]["HostIp"] != "127.0.0.1":
            raise TerminalUnavailable("Desktop must be bound to localhost")
        return "127.0.0.1:" + str(int(ports[0]["HostPort"]))

    def ready(self, tenant, conversation):
        self.terminal.ensure(tenant, conversation)
        endpoint = self.endpoint(tenant, conversation)
        import httpx

        for _ in range(30):
            try:
                response = httpx.get("http://" + endpoint + "/vnc.html", timeout=1, trust_env=False)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise TerminalUnavailable("Desktop is still starting")

    def action(self, tenant, conversation, request):
        self.ready(tenant, conversation)
        name = self.terminal.name(tenant, conversation)
        prefix = ["exec", "--env=DISPLAY=:99", name]
        if request.action in {"click", "double_click", "move"}:
            args = ["xdotool", "mousemove", "--sync", str(request.x), str(request.y)]
            if request.action != "move":
                args += ["click", "--repeat", "2" if request.action == "double_click" else "1", "1"]
            self.terminal.docker_call(*prefix, *args)
        elif request.action == "type":
            self.terminal.docker_call(
                *prefix, "xdotool", "type", "--clearmodifiers", "--delay", "1", "--", request.text
            )
        elif request.action == "key":
            self.terminal.docker_call(*prefix, "xdotool", "key", "--clearmodifiers", request.key)
        elif request.action == "scroll":
            self.terminal.docker_call(
                *prefix,
                "xdotool",
                "click",
                "--repeat",
                str(request.clicks),
                "4" if request.direction == "up" else "5",
            )
        # Observe the actual desktop after each action, rather than claiming an action's effect.
        time.sleep(0.15)
        path = "/tmp/desktop-" + uuid.uuid4().hex + ".jpg"
        try:
            self.terminal.docker_call(*prefix, "scrot", "-q", "45", path)
            result = self.terminal.docker_call(*prefix, "base64", "-w0", path)
            if len(result.stdout) > 500000:
                raise TerminalUnavailable("Desktop screenshot too large")
            return {
                "action": request.action,
                "width": 1280,
                "height": 800,
                "mime_type": "image/jpeg",
                "screenshot_base64": result.stdout,
            }
        finally:
            self.terminal.docker_call(*prefix, "rm", "-f", path, check=False)

    def screenshot(self, tenant, conversation):
        result = self.action(tenant, conversation, DesktopAction(action="screenshot"))
        return base64.b64decode(result["screenshot_base64"])
