#!/usr/bin/env python3
"""Claude Code statusLine 脚本：把 stdin JSON 里的 rate_limits 缓存下来，供 update.py 读取。

rate_limits 只在 Pro/Max 订阅、且会话收到第一次 API 响应后才会出现；没有时不覆盖旧缓存。
"""
import json
import os
import sys
import time

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_rate_limits.json")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    rl = data.get("rate_limits") or {}
    if rl.get("five_hour") or rl.get("seven_day"):
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"captured_at": int(time.time()), "rate_limits": rl}, f)
        os.replace(tmp, CACHE_FILE)

    five = rl.get("five_hour") or {}
    model = (data.get("model") or {}).get("display_name", "")
    if "used_percentage" in five:
        print(f"[{model}] 5h {round(five['used_percentage'])}%")
    else:
        print(f"[{model}]")


if __name__ == "__main__":
    main()
