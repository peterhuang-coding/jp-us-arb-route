"""异常推送 (spec §8). 默认微信 PushPlus; 接口抽象, Telegram 预留.

token 来源: PUSHPLUS_TOKEN 环境变量. 未配置时降级为 no-op + stderr 提示.
(真实平台密钥进 macOS Keychain 的改造随 M1 适配器一起做.)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class NullNotifier:
    """dry-run / 测试用, 不发任何消息."""

    def send(self, title: str, body: str) -> None:
        return None


class PushPlusNotifier:
    """微信 PushPlus 推送. token 显式传入或读 PUSHPLUS_TOKEN."""

    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("PUSHPLUS_TOKEN")

    def send(self, title: str, body: str) -> None:
        if not self.token:
            print("[notify] PUSHPLUS_TOKEN 未配置, 跳过推送", file=sys.stderr)
            return None
        payload = json.dumps({
            "token": self.token, "title": title, "content": body, "template": "txt",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except OSError as exc:  # URLError / HTTPError / socket 超时均为 OSError 子类
            print(f"[notify] 推送失败: {exc}", file=sys.stderr)
