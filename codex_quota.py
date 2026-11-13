"""本机查询 Codex 订阅额度：问官方 Codex CLI 的 app-server（account/rateLimits/read）。

不读日志、不碰登录凭据，Codex 没在跑时也能拿到实时数据，不消耗额度。
返回 update.py 内部用的 {primary/secondary: {used_percent, window_minutes, resets_at}} 结构。
做法参考 agent-hud-open（github.com/jazzenchen/agent-hud-open，Apache-2.0）。
"""
import json
import select
import subprocess
import time

TIMEOUT = 30


def _rpc(proc, message):
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def _read_limits(proc):
    """initialize -> initialized -> account/rateLimits/read，返回 result；超时或进程退出返回 None。"""
    _rpc(proc, {"id": 1, "method": "initialize",
                "params": {"clientInfo": {"name": "feishu_quota_status", "title": "feishu-quota-status",
                                          "version": "1.0"}}})
    deadline = time.time() + TIMEOUT
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], max(0.0, deadline - time.time()))
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("error"):
            raise RuntimeError(f"Codex app-server：{(msg['error'] or {}).get('message')}")
        if msg.get("id") == 1:
            _rpc(proc, {"method": "initialized"})
            _rpc(proc, {"id": 2, "method": "account/rateLimits/read"})
        elif msg.get("id") == 2:
            return msg.get("result") or {}


def fetch(codex_cli="codex"):
    proc = subprocess.Popen([codex_cli, "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        result = _read_limits(proc)
    finally:
        proc.kill()
        proc.communicate()
    if result is None:
        raise RuntimeError(f"Codex app-server 没有在 {TIMEOUT} 秒内返回额度")
    limits = (result.get("rateLimitsByLimitId") or {}).get("codex") or result.get("rateLimits") or {}
    rl = {}
    for key in ("primary", "secondary"):
        w = limits.get(key)
        if w and w.get("usedPercent") is not None:
            rl[key] = {"used_percent": float(w["usedPercent"]), "window_minutes": w.get("windowDurationMins"),
                       "resets_at": w.get("resetsAt")}
    if not rl:
        raise RuntimeError("Codex 没有返回额度窗口：可能未用 ChatGPT 登录，运行 codex login")
    # 服务端说已经撞线，但百分比还没到 100 时，把用量最高的窗口记为用尽
    if limits.get("rateLimitReachedType"):
        max(rl.values(), key=lambda w: w["used_percent"])["used_percent"] = 100
    return rl


if __name__ == "__main__":
    print(json.dumps(fetch(), ensure_ascii=False))
