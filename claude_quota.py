"""本机查询 Claude 订阅额度，结果写进 claude_rate_limits.json（与 claude_statusline.py 同一格式）。

不自己调接口、不碰 token：启动官方 Claude Code 引擎（claude -p，stream-json），发一条
control_request get_usage，由引擎用它自己的登录查询并负责续期。不调用模型，不消耗额度。
引擎查不到时，退回 Claude Code 自己记在 ~/.claude.json 的 cachedUsageUtilization（同一份数据，
每次 /usage 或 get_usage 都会刷新）。做法参考 agent-hud-open（github.com/jazzenchen/agent-hud-open，Apache-2.0）。
"""
import json
import os
import select
import subprocess
import time
from datetime import datetime

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_rate_limits.json")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
ENGINE_ARGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--settings", '{"disableAllHooks":true}']
REQUEST_ID = "feishu-quota-usage"
ENGINE_TIMEOUT = 40


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def _windows(limits):
    """get_usage 的 rate_limits -> statusline 同款 {five_hour/seven_day: {used_percentage, resets_at}}。"""
    rl = {}
    for field in ("five_hour", "seven_day"):
        w = (limits or {}).get(field) or {}
        if w.get("utilization") is not None:
            rl[field] = {"used_percentage": float(w["utilization"]), "resets_at": _epoch(w.get("resets_at"))}
    return rl


def _read_response(proc):
    """读引擎 stdout，直到拿到 get_usage 的 control_response；超时或进程结束返回 None。"""
    deadline = time.time() + ENGINE_TIMEOUT
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
        if msg.get("type") == "control_response":
            return msg.get("response") or {}


def _from_engine(claude_cli):
    proc = subprocess.Popen([claude_cli, *ENGINE_ARGS], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(CACHE_FILE),
                            env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "feishu-quota-status"})
    try:
        request = {"type": "control_request", "request_id": REQUEST_ID,
                   "request": {"subtype": "get_usage", "skip_behaviors": True}}
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        resp = _read_response(proc)
    finally:
        proc.kill()
        stderr = (proc.communicate()[1] or "").strip()[:200]
    if resp is None:
        raise RuntimeError(f"引擎没有在 {ENGINE_TIMEOUT} 秒内返回用量：{stderr}")
    if resp.get("subtype") == "error":
        raise RuntimeError(f"Claude Code 引擎查询失败：{resp.get('error')}")
    payload = resp.get("response") or {}
    if payload.get("rate_limits_available") is not True:
        raise RuntimeError("Claude Code 没有订阅额度数据：可能已退出登录，运行 claude auth login")
    rl = _windows(payload.get("rate_limits"))
    if not rl:
        raise RuntimeError("这次没有读到 Claude 额度，稍后重试")
    return rl


def _from_record():
    """Claude Code 自己记下的最近一次用量：(抓取时间秒, rate_limits) 或 None。"""
    try:
        record = json.load(open(CLAUDE_JSON, encoding="utf-8")).get("cachedUsageUtilization") or {}
    except (FileNotFoundError, ValueError):
        return None
    rl = _windows(record.get("utilization"))
    return (int(record.get("fetchedAtMs", 0) / 1000), rl) if rl else None


def _save(captured_at, rl):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"captured_at": captured_at, "rate_limits": rl}, f)
    os.replace(tmp, CACHE_FILE)


def fetch(claude_cli="claude"):
    """查询一次额度并写缓存，返回 statusline 同款的 rate_limits。

    引擎失败时，若 Claude Code 自己的记录比现有缓存新就用它，否则把引擎的错误抛出去。
    """
    try:
        rl = _from_engine(claude_cli)
    except Exception:
        record = _from_record()
        try:
            cached_at = json.load(open(CACHE_FILE, encoding="utf-8"))["captured_at"]
        except (FileNotFoundError, ValueError, KeyError):
            cached_at = 0
        if record and record[0] > cached_at:
            _save(*record)
            return record[1]
        raise
    _save(int(time.time()), rl)
    return rl


if __name__ == "__main__":
    print(json.dumps(fetch(), ensure_ascii=False))
