"""M0 推送测试 — PushPlus 用 monkeypatch 拦截 urllib, 不发真实网络请求."""
import json
import urllib.request

from arb.execution.notify import NullNotifier, PushPlusNotifier


def test_null_notifier_does_nothing():
    NullNotifier().send("t", "b")


def test_pushplus_sends_json_with_token(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    PushPlusNotifier(token="tok123").send("标题", "正文")
    assert captured["url"] == "https://www.pushplus.plus/send"
    assert captured["data"]["token"] == "tok123"
    assert captured["data"]["title"] == "标题"
    assert captured["data"]["content"] == "正文"


def test_pushplus_without_token_skips(monkeypatch, capsys):
    monkeypatch.delenv("PUSHPLUS_TOKEN", raising=False)
    PushPlusNotifier(token=None).send("t", "b")
    assert "未配置" in capsys.readouterr().err
