"""本机查询 Claude 订阅额度，结果写进 claude_rate_limits.json（与 claude_statusline.py 同一格式）。

凭证取自终端 claude 登录后存在钥匙串里的 claudeAiOauth。access_token 临期时不自己续期
（platform.claude.com 会拦截非官方客户端），而是跑一次官方 claude CLI 的最小请求，让它自己续期、
自己写钥匙串，然后重读。每次续期消耗极少量额度，大约 8 小时一次。
/api/oauth/usage 不是官方文档接口，随时可能变。
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_SKEW = 300
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_rate_limits.json")
# 让官方 CLI 续期用的最小请求：不保存会话，免得被当成「会话活动」
REFRESH_ARGS = ["-p", "ok", "--model", "haiku", "--no-session-persistence"]


def _read_oauth():
    out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError("钥匙串里没有 Claude Code-credentials，请先在终端运行 claude 登录")
    oauth = json.loads(out.stdout).get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("钥匙串里没有 Claude 登录，请先在终端运行 claude 登录")
    return oauth


def _fresh(oauth):
    return time.time() < (oauth.get("expiresAt") or 0) / 1000 - REFRESH_SKEW


def _http_json(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        raise RuntimeError(f"{req.full_url} HTTP {e.code}: {body}") from None


def _valid_access_token(claude_cli="claude"):
    oauth = _read_oauth()
    if _fresh(oauth):
        return oauth["accessToken"]
    proc = subprocess.run([claude_cli, *REFRESH_ARGS], capture_output=True, text=True,
                          timeout=180, cwd=os.path.dirname(CACHE_FILE))
    oauth = _read_oauth()
    if not _fresh(oauth):
        raise RuntimeError(f"claude CLI 没有续期 token（exit {proc.returncode}）：{proc.stderr.strip()[:200]}")
    return oauth["accessToken"]


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def fetch(claude_cli="claude"):
    """查询一次额度并写缓存，返回 statusline 同款的 rate_limits。"""
    token = _valid_access_token(claude_cli)
    d = _http_json(urllib.request.Request(
        USAGE_ENDPOINT, headers={"Authorization": f"Bearer {token}", "anthropic-beta": OAUTH_BETA}))
    rl = {}
    for field in ("five_hour", "seven_day"):
        w = d.get(field) or {}
        if w.get("utilization") is not None:
            rl[field] = {"used_percentage": float(w["utilization"]), "resets_at": _epoch(w.get("resets_at"))}
    if not rl:
        raise RuntimeError("usage 响应没有额度窗口数据")
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"captured_at": int(time.time()), "rate_limits": rl}, f)
    os.replace(tmp, CACHE_FILE)
    return rl


if __name__ == "__main__":
    print(json.dumps(fetch(), ensure_ascii=False))
