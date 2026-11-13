"""AI 订阅额度：Claude / Codex 剩多少，写进状态栏。

取数交给官方 CLI（lark_status.agents）：Claude 问 Claude Code 引擎的 get_usage，Codex 问
codex app-server 的 account/rateLimits/read。这里不读也不写任何凭据、不自己调接口、不耗额度，
登录和续期都是官方 CLI 的事。Codex 查不到时退回 ~/.codex/sessions 会话日志。

查不到就返回 None，状态栏自然退回下一个场景，不会挂一个错的数字上去。
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime

from .. import agents

SHORT_WINDOW_MINUTES = 300
LOW_THRESHOLD = 30


def claude_rate_limits(claude_cli: str = "claude") -> dict | None:
    try:
        return agents.claude_usage(claude_cli)
    except Exception as exc:
        print(f"[quota] Claude 查询失败：{exc}", file=sys.stderr)
        return None


def codex_rate_limits(codex_cli: str = "codex") -> dict | None:
    try:
        return agents.codex_usage(codex_cli)
    except Exception as exc:
        print(f"[quota] Codex app-server 查询失败，改读会话日志：{exc}", file=sys.stderr)
        return codex_rate_limits_from_logs()


def codex_rate_limits_from_logs() -> dict | None:
    files = sorted(glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")),
                   key=os.path.getmtime, reverse=True)
    for path in files[:5]:
        last, limit_hit = None, False
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if '"rate_limits"' in line:
                        try:
                            rl = json.loads(line)["payload"].get("rate_limits")
                        except (ValueError, KeyError, AttributeError):
                            continue
                        if rl and (rl.get("primary") or rl.get("secondary")):
                            last, limit_hit = rl, False
                    elif last and "hit your usage limit" in line:
                        limit_hit = True
        except OSError:
            continue
        if last:
            if limit_hit:
                windows = [w for w in (last.get("primary"), last.get("secondary")) if w]
                if windows:
                    max(windows, key=lambda w: w.get("used_percent") or 0)["used_percent"] = 100
            for w in (last.get("primary"), last.get("secondary")):
                if w:
                    w.setdefault("window_minutes", SHORT_WINDOW_MINUTES)
            return last
    return None


# ---------- 把额度变成一行字 ----------

def build(rl: dict | None, now: int, name: str, tz_offset: int = 8) -> tuple[str, str] | None:
    if not rl:
        return None
    windows = [w for w in (rl.get("primary"), rl.get("secondary")) if w]
    if not windows:
        return None

    def fmt(ts: int, short: bool) -> str:
        dt = datetime.utcfromtimestamp(ts + tz_offset * 3600)
        return dt.strftime("%H:%M" if short else "%m/%d")

    exhausted = [w for w in windows
                 if (w.get("used_percent") or 0) >= 100 and (w.get("resets_at") or 0) > now]
    if exhausted:
        w = max(exhausted, key=lambda x: x["resets_at"])
        short = (w.get("window_minutes") or 0) <= SHORT_WINDOW_MINUTES
        return f"🏖️ 已陨落 {fmt(w['resets_at'], short)}恢复", "GeneralVacation"

    short_windows = [w for w in windows if (w.get("window_minutes") or 0) <= SHORT_WINDOW_MINUTES]
    if short_windows:
        window, is_short = short_windows[0], True
    else:
        window, is_short = max(windows, key=lambda x: x.get("window_minutes") or 0), False

    resets_at = window.get("resets_at") or 0
    if resets_at and resets_at <= now:
        return f"⚡ {name}额度已恢复", "StatusFlashOfInspiration"
    left = max(0, round(100 - (window.get("used_percent") or 0)))
    reset = fmt(resets_at, is_short) if resets_at else "?"
    if left == 0:
        return f"🏖️ 已陨落 {reset}恢复", "GeneralVacation"
    if left == 100:
        return f"⚡ {name}额度满", "StatusFlashOfInspiration"
    icon = "Typing" if left < LOW_THRESHOLD else "StatusFlashOfInspiration"
    return f"{name}剩{left}% {reset}恢复", icon


class Quota:
    """额度场景。provider 可选 claude / codex。"""

    name = "quota"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.provider = self.cfg.get("provider", "claude")
        self.claude_cli = self.cfg.get("claude_cli", "claude")
        self.codex_cli = self.cfg.get("codex_cli", "codex")
        self.tz_offset = int(self.cfg.get("utc_offset_hours", 8))
        self._cache: tuple[int, dict | None] | None = None

    def render(self, now: int) -> tuple[str, str] | None:
        # 额度不需要每秒查，5 分钟一次足够
        if self._cache and now - self._cache[0] < int(self.cfg.get("min_interval", 300)):
            return build(self._cache[1], now, self._display_name(), self.tz_offset)
        if self.provider == "codex":
            rl = codex_rate_limits(self.codex_cli)
        else:
            rl = claude_rate_limits(self.claude_cli)
        self._cache = (now, rl)
        return build(rl, now, self._display_name(), self.tz_offset)

    def _display_name(self) -> str:
        return {"claude": "Claude", "codex": "Codex"}.get(self.provider, self.provider.title())
