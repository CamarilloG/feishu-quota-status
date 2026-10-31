"""AI 订阅额度：Claude / Codex 剩多少，写进状态栏。

额度取值的核心逻辑与 claude_quota.py 一致（那份已经跑验证过），这里只做两件事：

  1. 凭证读取按平台分支：macOS 走钥匙串，Linux/Windows 走
     ~/.claude/.credentials.json 或 ANTHROPIC_CREDENTIALS 环境变量。
  2. 把结果转成一行状态文字。

关于 token 续期 —— 重要：**不要自己调 refresh 接口**。
platform.claude.com 会拦截非官方客户端（Cloudflare 1010），续期会失败，
之后缓存失效、状态退回「额度已恢复」。正确做法是跑一次官方 claude CLI 的最小请求，
让它自己续期、自己写钥匙串，然后重读。每次续期消耗极少量额度，大约 8 小时一次。

⚠️ /api/oauth/usage 是未公开接口，随时可能变。变了就返回 None，状态栏自然退回下一个场景，
   不会挂一个错的数字上去。
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_SKEW = 300
SHORT_WINDOW_MINUTES = 300
LOW_THRESHOLD = 30
# 让官方 CLI 续期用的最小请求：不保存会话，免得被当成「会话活动」
REFRESH_ARGS = ["-p", "ok", "--model", "haiku", "--no-session-persistence"]


# ---------- 凭证：按平台分支 ----------

def _cred_file() -> str:
    return os.path.expanduser("~/.claude/.credentials.json")


def _read_cred_blob() -> dict:
    """读出完整凭证结构（含 claudeAiOauth）。"""
    env = os.environ.get("ANTHROPIC_CREDENTIALS")
    if env:
        return json.loads(env)
    if sys.platform == "darwin":
        out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return json.loads(out.stdout)
    path = _cred_file()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raise RuntimeError("找不到 Claude 凭证，请先在终端运行 claude 登录")


def _read_oauth() -> dict:
    oauth = _read_cred_blob().get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("凭证里没有 Claude 登录信息，请先在终端运行 claude 登录")
    return oauth


def _fresh(oauth: dict) -> bool:
    return time.time() < (oauth.get("expiresAt") or 0) / 1000 - REFRESH_SKEW


def _http_json(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        raise RuntimeError(f"{req.full_url} HTTP {e.code}: {body}") from None


def _valid_access_token(claude_cli: str = "claude") -> str:
    """拿一个可用的 access token。

    临期时不自己续期，而是跑官方 CLI 让它自己续 —— 自己续会被 Cloudflare 拦。
    """
    oauth = _read_oauth()
    if _fresh(oauth):
        return oauth["accessToken"]

    subprocess.run([claude_cli, *REFRESH_ARGS], capture_output=True, text=True, timeout=180)
    oauth = _read_oauth()
    if not _fresh(oauth):
        raise RuntimeError(f"claude CLI 没有续期 token，检查 {claude_cli!r} 是否在 PATH 里")
    return oauth["accessToken"]


def _epoch(iso: str | None) -> int | None:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def claude_rate_limits(claude_cli: str = "claude") -> dict | None:
    try:
        token = _valid_access_token(claude_cli)
        d = _http_json(urllib.request.Request(
            USAGE_ENDPOINT, headers={"Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA}))
    except Exception as exc:
        print(f"[quota] Claude 查询失败：{exc}", file=sys.stderr)
        return None
    out = {}
    for key, field, minutes in (("primary", "five_hour", 300), ("secondary", "seven_day", 10080)):
        w = d.get(field) or {}
        if w.get("utilization") is not None:
            out[key] = {"used_percent": float(w["utilization"]),
                        "window_minutes": minutes, "resets_at": _epoch(w.get("resets_at"))}
    return out or None


def codex_rate_limits() -> dict | None:
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
        self.tz_offset = int(self.cfg.get("utc_offset_hours", 8))
        self._cache: tuple[int, dict | None] | None = None

    def render(self, now: int) -> tuple[str, str] | None:
        # 额度不需要每秒查，5 分钟一次足够
        if self._cache and now - self._cache[0] < int(self.cfg.get("min_interval", 300)):
            return build(self._cache[1], now, self._display_name(), self.tz_offset)
        if self.provider == "codex":
            rl = codex_rate_limits()
        else:
            rl = claude_rate_limits(self.claude_cli)
        self._cache = (now, rl)
        return build(rl, now, self._display_name(), self.tz_offset)

    def _display_name(self) -> str:
        return {"claude": "Claude", "codex": "Codex"}.get(self.provider, self.provider.title())
