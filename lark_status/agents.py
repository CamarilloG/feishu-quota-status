"""问官方 CLI 要订阅额度：Claude Code 引擎的 get_usage、Codex app-server 的 account/rateLimits/read。

不自己调 Anthropic / OpenAI 的接口、不读也不写任何凭据、不调用模型、不消耗额度；
登录和 token 续期全是官方 CLI 自己的事。两个函数都返回统一结构：

    {"primary": {"used_percent", "window_minutes", "resets_at"}, "secondary": {...}}

失败抛 RuntimeError。按行读子进程输出用线程 + 队列做超时，Windows 上也能用。
做法参考 agent-hud-open（github.com/jazzenchen/agent-hud-open，Apache-2.0）。
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime

CLAUDE_ARGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--settings", '{"disableAllHooks":true}']
TIMEOUT = 40


def _epoch(iso: str | None) -> int | None:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


class _Process:
    """一个按 JSON 行通信的子进程，readline 带超时。"""

    def __init__(self, args: list[str], cwd: str | None = None, env: dict | None = None):
        exe = shutil.which(args[0]) or args[0]
        self.proc = subprocess.Popen([exe, *args[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=cwd,
                                     env={**os.environ, **(env or {})})
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def messages(self, timeout: float):
        """逐条产出 JSON 消息，直到超时或进程结束。"""
        deadline = time.time() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, deadline - time.time()))
            except queue.Empty:
                return
            if line is None:
                return
            try:
                yield json.loads(line)
            except ValueError:
                continue

    def close(self) -> str:
        self.proc.kill()
        try:
            return (self.proc.communicate(timeout=5)[1] or "").strip()[:200]
        except Exception:
            return ""


def claude_windows(limits: dict | None) -> dict:
    """get_usage / cachedUsageUtilization 的 rate_limits -> 统一结构。"""
    out = {}
    for key, field, minutes in (("primary", "five_hour", 300), ("secondary", "seven_day", 10080)):
        w = (limits or {}).get(field) or {}
        if w.get("utilization") is not None:
            out[key] = {"used_percent": float(w["utilization"]), "window_minutes": minutes,
                        "resets_at": _epoch(w.get("resets_at"))}
    return out


def claude_usage(claude_cli: str = "claude", cwd: str | None = None) -> dict:
    """启动 Claude Code 引擎，发 control_request get_usage。"""
    proc = _Process([claude_cli, *CLAUDE_ARGS], cwd=cwd,
                    env={"CLAUDE_CODE_ENTRYPOINT": "lark-status"})
    resp = None
    try:
        proc.send({"type": "control_request", "request_id": "lark-status-usage",
                   "request": {"subtype": "get_usage", "skip_behaviors": True}})
        for msg in proc.messages(TIMEOUT):
            if msg.get("type") == "control_response":
                resp = msg.get("response") or {}
                break
    finally:
        stderr = proc.close()
    if resp is None:
        raise RuntimeError(f"Claude Code 引擎没有在 {TIMEOUT} 秒内返回用量：{stderr}")
    if resp.get("subtype") == "error":
        raise RuntimeError(f"Claude Code 引擎查询失败：{resp.get('error')}")
    payload = resp.get("response") or {}
    if payload.get("rate_limits_available") is not True:
        raise RuntimeError("Claude Code 没有订阅额度数据：可能已退出登录，运行 claude auth login")
    rl = claude_windows(payload.get("rate_limits"))
    if not rl:
        raise RuntimeError("这次没有读到 Claude 额度，稍后重试")
    return rl


def codex_usage(codex_cli: str = "codex") -> dict:
    """启动 codex app-server，JSON-RPC 调 account/rateLimits/read。"""
    proc = _Process([codex_cli, "app-server", "--listen", "stdio://"])
    result = None
    try:
        proc.send({"id": 1, "method": "initialize",
                   "params": {"clientInfo": {"name": "lark_status", "title": "lark-status", "version": "1.0"}}})
        for msg in proc.messages(TIMEOUT):
            if msg.get("error"):
                raise RuntimeError(f"Codex app-server：{(msg['error'] or {}).get('message')}")
            if msg.get("id") == 1:
                proc.send({"method": "initialized"})
                proc.send({"id": 2, "method": "account/rateLimits/read"})
            elif msg.get("id") == 2:
                result = msg.get("result") or {}
                break
    finally:
        proc.close()
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
