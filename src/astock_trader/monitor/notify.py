"""通知分发 —— 把监控事件推到人真正会看到的地方。

设计取向：**零新增依赖**。所有通道都是普通的 HTTP POST/GET，用项目已有的
``requests`` 就能发，因此不需要引入 Apprise 之类的框架；代价是通道种类要自己
维护，但换来的是可控、可测、不会有隐式依赖。

支持的通道（``type`` 取值）：

============  ==========================================================
``console``   打到终端（默认，永远可用）
``webhook``   通用 JSON POST，body 为事件 dict；适合接自己的服务
``wecom``     企业微信群机器人
``dingtalk``  钉钉群机器人
``feishu``    飞书群机器人
``serverchan``Server 酱（``sctapi.ftqq.com``）
``pushplus``  PushPlus
``bark``      Bark（iOS）
============  ==========================================================

配置示例::

    {"notify": {"min_level": "notice", "channels": [
      {"type": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"},
      {"type": "webhook", "url": "https://example.com/hook", "headers": {"X-Token": "..."}}
    ]}}

任何通道发送失败只记 warning，**不抛出** —— 通知挂掉不该让监控循环停摆。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .events import LEVEL_ORDER, MonitorEvent

logger = logging.getLogger(__name__)

__all__ = ["Notifier", "build_notifier", "CHANNEL_TYPES"]

_TIMEOUT = 10


def _post(url: str, *, json_body: dict | None = None, data: dict | None = None, headers: dict | None = None) -> None:
    import requests

    resp = requests.post(url, json=json_body, data=data, headers=headers or {}, timeout=_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


def _get(url: str, *, params: dict | None = None, headers: dict | None = None) -> None:
    import requests

    resp = requests.get(url, params=params, headers=headers or {}, timeout=_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# 单通道发送
# ---------------------------------------------------------------------------


def _send_console(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    if event is not None:
        print(event.one_line(), flush=True)
    else:
        print(f"{title}\n{body}", flush=True)


def _send_webhook(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    payload = event.to_dict() if event is not None else {"title": title, "body": body}
    _post(channel["url"], json_body=payload, headers=channel.get("headers"))


def _send_wecom(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    _post(channel["url"], json_body={"msgtype": "text", "text": {"content": f"{title}\n{body}"}})


def _send_dingtalk(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    _post(channel["url"], json_body={"msgtype": "text", "text": {"content": f"{title}\n{body}"}})


def _send_feishu(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    _post(channel["url"], json_body={"msg_type": "text", "content": {"text": f"{title}\n{body}"}})


def _send_serverchan(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    send_key = channel.get("send_key") or channel.get("key")
    if not send_key:
        raise ValueError("serverchan 通道缺少 send_key")
    _post(f"https://sctapi.ftqq.com/{send_key}.send", data={"title": title, "desp": body})


def _send_pushplus(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    token = channel.get("token")
    if not token:
        raise ValueError("pushplus 通道缺少 token")
    _post("https://www.pushplus.plus/send", json_body={"token": token, "title": title, "content": body})


def _send_bark(channel: dict[str, Any], title: str, body: str, event: MonitorEvent | None) -> None:
    base = channel.get("url") or "https://api.day.app"
    key = channel.get("key")
    if not key:
        raise ValueError("bark 通道缺少 key")
    _post(f"{base.rstrip('/')}/{key}", json_body={"title": title, "body": body})


CHANNEL_TYPES: dict[str, Any] = {
    "console": _send_console,
    "webhook": _send_webhook,
    "wecom": _send_wecom,
    "dingtalk": _send_dingtalk,
    "feishu": _send_feishu,
    "serverchan": _send_serverchan,
    "pushplus": _send_pushplus,
    "bark": _send_bark,
}


class Notifier:
    """按配置把事件推到一个或多个通道。"""

    def __init__(self, channels: list[dict[str, Any]], min_level: str = "info"):
        self.channels = [c for c in channels if c.get("type") in CHANNEL_TYPES]
        unknown = [c.get("type") for c in channels if c.get("type") not in CHANNEL_TYPES]
        if unknown:
            logger.warning("忽略未知通知通道：%s", unknown)
        if not self.channels:
            self.channels = [{"type": "console"}]
        self.min_level = LEVEL_ORDER.get(min_level, 0)

    def should_send(self, event: MonitorEvent) -> bool:
        return event.severity >= self.min_level

    def send(self, event: MonitorEvent) -> int:
        """推送一条事件，返回成功通道数。"""
        if not self.should_send(event):
            return 0
        return self.send_raw(event.one_line(), event.message, event)

    def send_raw(self, title: str, body: str, event: MonitorEvent | None = None) -> int:
        ok = 0
        for channel in self.channels:
            sender = CHANNEL_TYPES[channel["type"]]
            try:
                sender(channel, title, body, event)
                ok += 1
            except Exception as exc:
                logger.warning("通知通道 %s 发送失败：%s", channel["type"], exc)
        return ok

    def test(self) -> int:
        """发一条测试消息，用于 ``watch --test-notify``。"""
        return self.send_raw("TradingVane 监控测试", f"通知通道连通性测试（{len(self.channels)} 个通道）", None)


def build_notifier(spec: dict[str, Any] | None = None) -> Notifier:
    """从配置 dict 构建 :class:`Notifier`。"""
    spec = spec or {}
    return Notifier(spec.get("channels") or [{"type": "console"}], min_level=str(spec.get("min_level", "info")))


def format_event_json(event: MonitorEvent) -> str:
    """事件的美化 JSON，便于 webhook 调试。"""
    return json.dumps(event.to_dict(), ensure_ascii=False, indent=2)
