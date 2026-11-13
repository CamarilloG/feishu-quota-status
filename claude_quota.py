"""本机查询 Claude 订阅额度，结果写进 claude_rate_limits.json（与 claude_statusline.py 同一格式）。

查询本身在 lark_status.agents.claude_usage（问官方 Claude Code 引擎的 get_usage，不碰凭据、不耗额度）。
引擎查不到时，退回 Claude Code 自己记在 ~/.claude.json 的 cachedUsageUtilization（同一份数据，
每次 /usage 或 get_usage 都会刷新），前提是它比现有缓存新。
"""
import json
import os
import time

from lark_status import agents

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_rate_limits.json")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
FIELDS = (("primary", "five_hour"), ("secondary", "seven_day"))


def _to_cache(rl):
    """统一结构 -> statusline 同款 {five_hour/seven_day: {used_percentage, resets_at}}。"""
    return {field: {"used_percentage": rl[key]["used_percent"], "resets_at": rl[key]["resets_at"]}
            for key, field in FIELDS if key in rl}


def _from_record():
    """Claude Code 自己记下的最近一次用量：(抓取时间秒, statusline 格式) 或 None。"""
    try:
        record = json.load(open(CLAUDE_JSON, encoding="utf-8")).get("cachedUsageUtilization") or {}
    except (FileNotFoundError, ValueError):
        return None
    rl = agents.claude_windows(record.get("utilization"))
    return (int(record.get("fetchedAtMs", 0) / 1000), _to_cache(rl)) if rl else None


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
        rl = _to_cache(agents.claude_usage(claude_cli, cwd=os.path.dirname(CACHE_FILE)))
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
