"""本机查询 Claude 订阅额度，结果写进 claude_rate_limits.json（与 claude_statusline.py 同一格式）。

凭证取自终端 claude 登录后存在钥匙串里的 claudeAiOauth；access_token 临期时自己续期并写回钥匙串
（refresh_token 会轮换，写回后终端 claude 读到的也是新的）。
用的是 Claude Code 自己的公开 OAuth client 与 /api/oauth/usage 端点，均非官方文档接口，随时可能变。
"""
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime

KEYCHAIN_SERVICE = "Claude Code-credentials"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_SKEW = 300
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_rate_limits.json")


def _read_keychain():
    out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError("钥匙串里没有 Claude Code-credentials")
    return json.loads(out.stdout)


def _store_keychain(data):
    # 十六进制经参数传入。不要用 security -i：它会截断长行，曾把凭据写成半截。
    account = os.environ.get("USER") or os.getlogin()
    hexdata = json.dumps(data, separators=(",", ":")).encode().hex()
    out = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
                          "-a", account, "-X", hexdata], capture_output=True, text=True)
    return out.returncode == 0


def _write_keychain(data, original):
    """写入后读回校验，不一致就还原成 original。"""
    if _store_keychain(data):
        try:
            if _read_keychain() == data:
                return
        except (RuntimeError, ValueError):
            pass
    _store_keychain(original)
    raise RuntimeError("写回钥匙串校验失败，已还原原凭据")


def _http_json(req):
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _valid_access_token():
    data = _read_keychain()
    original = json.loads(json.dumps(data))
    oauth = data.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise RuntimeError("钥匙串里没有 Claude 登录，请先在终端运行 claude 登录")
    if time.time() < (oauth.get("expiresAt") or 0) / 1000 - REFRESH_SKEW:
        return oauth["accessToken"]
    if not oauth.get("refreshToken"):
        raise RuntimeError("登录缺少 refresh_token，请在终端重新登录 claude")
    body = json.dumps({"grant_type": "refresh_token", "refresh_token": oauth["refreshToken"],
                       "client_id": CLIENT_ID}).encode()
    d = _http_json(urllib.request.Request(TOKEN_ENDPOINT, data=body,
                                          headers={"Content-Type": "application/json"}))
    oauth["accessToken"] = d["access_token"]
    if d.get("refresh_token"):
        oauth["refreshToken"] = d["refresh_token"]
    if d.get("expires_in"):
        oauth["expiresAt"] = int((time.time() + int(d["expires_in"])) * 1000)
    data["claudeAiOauth"] = oauth
    _write_keychain(data, original)
    return oauth["accessToken"]


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def fetch():
    """查询一次额度并写缓存，返回 statusline 同款的 rate_limits。"""
    token = _valid_access_token()
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
