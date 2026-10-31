"""测核心那几个坑，以及场景的边界。不联网、不需要飞书凭证。"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lark_status import core
from lark_status.core import ALIASES, ICONS, StatusConfig, StatusWriter, fit_title, resolve_icon
from lark_status.source import humanize
from lark_status.sources.fish import Fish
from lark_status.sources.pomodoro import Pomodoro
from lark_status.sources.quota import build as build_quota


# ---------- 字符宽度 ----------

def test_ascii_fits_untouched():
    assert fit_title("CI failed") == "CI failed"


def test_chinese_counts_double():
    # 10 个汉字 = 20 字符，正好到上限
    s = "一二三四五六七八九十"
    assert fit_title(s) == s


def test_over_limit_drops_spaces_first():
    title = "Claude 剩 53% 15:49 恢复"
    out = fit_title(title)
    assert " " not in out
    assert sum(2 if ord(c) > 127 else 1 for c in out) <= 20


def test_over_limit_hard_truncates():
    out = fit_title("一二三四五六七八九十一二三四五六七八九十")
    assert sum(2 if ord(c) > 127 else 1 for c in out) <= 20


def test_never_exceeds_limit():
    for s in ["🐟 已摸鱼 2 小时 15 分钟", "❌ Deploy 构建挂了", "x" * 50]:
        assert sum(2 if ord(c) > 127 else 1 for c in fit_title(s)) <= 20


# ---------- 图标 ----------

def test_all_official_icons_accepted():
    for icon in ICONS:
        assert resolve_icon(icon) == icon


def test_alias_resolves():
    assert resolve_icon("coffee") == "Coffee"
    assert resolve_icon("FUN") == "StatusEnjoyLife"


def test_emoji_icon_rejected_with_help():
    with pytest.raises(ValueError) as e:
        resolve_icon("💀")
    assert "未知图标" in str(e.value)


def test_icon_count_is_18():
    assert len(ICONS) == 18


# ---------- 写入三步 ----------

class FakeWriter(StatusWriter):
    """把 lark-cli 调用记下来，不真的发请求。"""

    def __init__(self, tmp_path, last_state=""):
        cfg = StatusConfig(lark_cli="lark-cli", system_status_id="123", user_open_id="ou_x", ttl=1800)
        super().__init__(cfg, state_file=str(tmp_path / "last_state"))
        self.calls = []

    def _fake_lark(self, lark_cli, method, path, data, params=None):
        self.calls.append((method, path))
        return {"ok": True}


@pytest.fixture
def writer(tmp_path, monkeypatch):
    """造一个 FakeWriter，并把 core.lark_call 接到它的记录器上。"""
    w = FakeWriter(tmp_path)
    monkeypatch.setattr(core, "lark_call", w._fake_lark)
    return w


def test_text_change_triggers_three_steps(writer):
    writer.push("🐟 已摸鱼 5 分钟", "Coffee")
    assert [c[0] for c in writer.calls] == ["PATCH", "POST", "POST"]
    assert writer.calls[1][1].endswith("/batch_close")
    assert writer.calls[2][1].endswith("/batch_open")


def test_same_text_only_refreshes(writer):
    writer.push("🐟 已摸鱼 5 分钟", "Coffee")
    writer.calls.clear()
    writer.push("🐟 已摸鱼 5 分钟", "Coffee")
    # 文字没变，跳过改名和关闭，只续期
    assert [c[0] for c in writer.calls] == ["POST"]
    assert writer.calls[0][1].endswith("/batch_open")


def test_icon_change_also_triggers_rename(writer):
    writer.push("🐟 已摸鱼 5 分钟", "Coffee")
    writer.calls.clear()
    writer.push("🐟 已摸鱼 5 分钟", "StatusEnjoyLife")
    assert len(writer.calls) == 3


def test_dry_run_makes_no_calls(writer, monkeypatch):
    writer.dry_run = True
    out = writer.push("测试", "Coffee")
    assert out["dry_run"] is True
    assert writer.calls == []


def test_missing_config_raises(tmp_path):
    w = StatusWriter(StatusConfig(), state_file=str(tmp_path / "s"))
    with pytest.raises(RuntimeError) as e:
        w.push("测试", "Coffee")
    assert "setup.py" in str(e.value)


# ---------- 场景 ----------

def test_fish_idle_returns_none(tmp_path):
    assert Fish(str(tmp_path / "fish.json")).render(int(time.time())) is None


def test_fish_after_start(tmp_path):
    f = Fish(str(tmp_path / "fish.json"))
    now = 1_000_000
    f.start(now)
    title, icon = f.render(now + 47 * 60)
    assert "47 分钟" in title
    assert icon == "Coffee"


def test_fish_long_session_switches_icon(tmp_path):
    f = Fish(str(tmp_path / "fish.json"))
    now = 1_000_000
    f.start(now)
    assert f.render(now + 3 * 3600)[1] == "StatusEnjoyLife"


def test_fish_stop_accumulates(tmp_path):
    f = Fish(str(tmp_path / "fish.json"))
    f.start(1000)
    state = f.stop(1000 + 600)
    assert state["total"] == 600
    assert f.render(2000) is None


def test_pomodoro_countdown(tmp_path):
    p = Pomodoro(str(tmp_path / "pomo.json"))
    now = 1_000_000
    p.start(25, now)
    title, icon = p.render(now + 12 * 60)
    assert "剩 13 分钟" in title
    assert icon == "GeneralMoonRest"


def test_pomodoro_finished(tmp_path):
    p = Pomodoro(str(tmp_path / "pomo.json"))
    now = 1_000_000
    p.start(25, now)
    title, _ = p.render(now + 25 * 60 + 300)
    assert "专注结束" in title


def test_pomodoro_idle_returns_none(tmp_path):
    assert Pomodoro(str(tmp_path / "pomo.json")).render(1000) is None


# ---------- 额度 ----------

def test_quota_build_normal():
    rl = {"primary": {"used_percent": 47, "window_minutes": 300, "resets_at": 1_700_000_000}}
    title, icon = build_quota(rl, 1_699_000_000, "Claude")
    assert "剩53%" in title
    assert icon == "StatusFlashOfInspiration"


def test_quota_build_low_switches_icon():
    rl = {"primary": {"used_percent": 91, "window_minutes": 300, "resets_at": 1_700_000_000}}
    assert build_quota(rl, 1_699_000_000, "Claude")[1] == "Typing"


def test_quota_build_exhausted():
    rl = {"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": 1_700_000_000}}
    title, icon = build_quota(rl, 1_699_000_000, "Claude")
    assert "已陨落" in title
    assert icon == "GeneralVacation"


def test_quota_none_returns_none():
    assert build_quota(None, 1_000_000, "Claude") is None


# ---------- 人话 ----------

@pytest.mark.parametrize("seconds,expected", [
    (30, "30 秒"),
    (60, "1 分钟"),
    (47 * 60, "47 分钟"),
    (3600, "1 小时"),
    (3600 + 900, "1 小时 15 分"),
    (86400 * 3, "3 天"),
])
def test_humanize(seconds, expected):
    assert humanize(seconds) == expected
