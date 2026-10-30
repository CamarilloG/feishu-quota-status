#!/usr/bin/env python3
"""把 Claude 或 Codex 的剩余额度写进飞书系统状态，图标按额度档位切换。

显示哪一边由 config.json 的 source 决定（菜单栏应用会改它）。每次运行把两边的额度写进 status.json，
供菜单栏应用展示。

个人配置（飞书系统状态 ID、你的 open_id、lark-cli 路径、时区）都在 config.json，见 config.example.json。

有 5 小时窗口时看 5 小时窗口（显示恢复时刻）；只有周窗口时（如 Pro 的单一周额度）看周窗口
（显示恢复日期）。

Codex 的数据来自 ~/.codex/sessions 下最新会话日志里的 rate_limits（只有 Codex 运行时才会刷新）。
Claude 的数据由 claude_quota.py 本机查询，查询频率跟着 ~/.claude/projects 的会话活动走：
10 分钟内有活动每 10 分钟查一次，2 小时内有活动每 30 分钟查一次，更久没活动就不查，沿用缓存推算。
状态文字变化时：PATCH 名称 -> batch_close -> batch_open（客户端才会显示新文字）；
文字没变时只 batch_open 续期。状态有效期设为 STATUS_TTL，电脑休眠后会自然过期。
"""
import glob
import traceback
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import claude_quota

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")
STATUS_FILE = os.path.join(HERE, "status.json")
NAMES = {"claude": "Claude", "codex": "Codex"}
TITLE_MAX = 20  # 飞书系统状态名称上限，1 个汉字算 2
ACTIVITY_TIERS = ((10 * 60, 9 * 60), (2 * 3600, 29 * 60))  # (距上次会话活动, 最短查询间隔)
ICON_PLENTY = "StatusFlashOfInspiration"
ICON_LOW = "Typing"
ICON_OUT = "GeneralVacation"
LOW_THRESHOLD = 30
SHORT_WINDOW_MINUTES = 300
DEFAULTS = {"source": "claude", "lark_cli": "lark-cli", "utc_offset_hours": 8}
STATUS_TTL = 30 * 60
STATE_FILE = os.path.join(HERE, "last_title.txt")
STATUS_API = "/open-apis/personal_settings/v1/system_statuses"


def latest_codex_rate_limits():
    """返回最新的 rate_limits。

    额度用尽后 Codex 不再发请求，日志里不会出现 100% 的记录，只会在最后一条 rate_limits 之后
    出现 "hit your usage limit" 报错；这种情况下把用量最高的窗口记为 100%。
    """
    files = sorted(glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")),
                   key=os.path.getmtime, reverse=True)
    for path in files[:5]:
        last, limit_hit = None, False
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
        if last:
            if limit_hit:
                windows = [w for w in (last.get("primary"), last.get("secondary")) if w]
                max(windows, key=lambda w: w.get("used_percent") or 0)["used_percent"] = 100
            return last
    return None


def last_claude_activity():
    newest = 0
    for proj in glob.glob(os.path.expanduser("~/.claude/projects/*")):
        for path in glob.glob(os.path.join(proj, "*.jsonl")):
            newest = max(newest, os.path.getmtime(path))
    return newest


def latest_claude_rate_limits(now):
    """按会话活动决定要不要现查，然后读缓存，转成和 Codex 一样的 primary/secondary 结构。"""
    try:
        cache = json.load(open(claude_quota.CACHE_FILE, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = None
    idle = now - last_claude_activity()
    age = now - cache["captured_at"] if cache else float("inf")
    if any(idle <= active and age >= interval for active, interval in ACTIVITY_TIERS):
        try:
            claude_quota.fetch()
            cache = json.load(open(claude_quota.CACHE_FILE, encoding="utf-8"))
        except Exception:
            traceback.print_exc()
    if not cache:
        return None
    rl = cache["rate_limits"]
    out = {}
    for key, field, minutes in (("primary", "five_hour", 300), ("secondary", "seven_day", 10080)):
        w = rl.get(field)
        if w and w.get("used_percentage") is not None:
            out[key] = {"used_percent": w["used_percentage"], "window_minutes": minutes,
                        "resets_at": w.get("resets_at")}
    return out or None


def fit(title):
    """超出飞书名称长度上限时去掉空格。"""
    if sum(2 if ord(c) > 127 else 1 for c in title) > TITLE_MAX:
        title = title.replace(" ", "")
    return title


def build_status(rl, now, name):
    """返回 (状态文字, 图标, 剩余百分比)。"""
    windows = [w for w in (rl.get("primary"), rl.get("secondary")) if w]

    # 任一窗口用尽就显示已陨落，恢复时间取用尽窗口里最晚的那个
    exhausted = [w for w in windows
                 if w["used_percent"] >= 100 and (w.get("resets_at") or 0) > now]
    if exhausted:
        w = max(exhausted, key=lambda w: w["resets_at"])
        fmt = "%H:%M" if (w.get("window_minutes") or 0) <= SHORT_WINDOW_MINUTES else "%m/%d"
        return f"已陨落 {datetime.fromtimestamp(w['resets_at'], DISPLAY_TZ).strftime(fmt)}恢复", ICON_OUT, 0

    short = [w for w in windows if (w.get("window_minutes") or 0) <= SHORT_WINDOW_MINUTES]
    if short:
        window, reset_fmt = short[0], "%H:%M"
    else:
        window = max(windows, key=lambda w: w.get("window_minutes") or 0)
        reset_fmt = "%m/%d"
    resets_at = window.get("resets_at") or 0
    if resets_at and resets_at <= now:
        return f"{name}额度已恢复", ICON_PLENTY, 100
    left = max(0, round(100 - window["used_percent"]))
    reset = datetime.fromtimestamp(resets_at, DISPLAY_TZ).strftime(reset_fmt) if resets_at else "?"
    if left == 0:
        return f"已陨落 {reset}恢复", ICON_OUT, 0
    if left == 100:
        return f"{name}额度满", ICON_PLENTY, 100
    icon = ICON_LOW if left < LOW_THRESHOLD else ICON_PLENTY
    return fit(f"{name}剩{left}% {reset}恢复"), icon, left


def load_config():
    try:
        cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cfg = {}
    cfg = {**DEFAULTS, **cfg}
    if cfg["source"] not in NAMES:
        cfg["source"] = DEFAULTS["source"]
    return cfg


CONFIG = load_config()
DISPLAY_TZ = timezone(timedelta(hours=CONFIG["utc_offset_hours"]))


def lark(method, path, data, params=None):
    cmd = [CONFIG["lark_cli"], "api", method, path, "--as", "bot",
           "--data", json.dumps(data, ensure_ascii=False)]
    if params:
        cmd += ["--params", json.dumps(params)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    res = json.loads(proc.stdout or proc.stderr)
    if not res.get("ok"):
        raise RuntimeError(f"{method} {path}: {json.dumps(res.get('error'), ensure_ascii=False)}")
    return res


def write_status(now, source, all_rl):
    """给菜单栏应用：两边各自的窗口明细和按飞书规则算出的文字。"""
    out = {"updated_at": now, "source": source, "sources": {}}
    for key, rl in all_rl.items():
        if not rl:
            out["sources"][key] = None
            continue
        title, icon, left = build_status(rl, now, NAMES[key])
        windows = [{"window_minutes": w.get("window_minutes"), "used_percent": w["used_percent"],
                    "resets_at": w.get("resets_at")}
                   for w in (rl.get("primary"), rl.get("secondary")) if w]
        out["sources"][key] = {"title": title, "icon": icon, "left": left, "windows": windows}
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, STATUS_FILE)


def main():
    now = int(time.time())
    source = CONFIG["source"]
    all_rl = {"claude": latest_claude_rate_limits(now), "codex": latest_codex_rate_limits()}
    write_status(now, source, all_rl)
    if not CONFIG.get("system_status_id") or not CONFIG.get("user_open_id"):
        print("config.json 缺少 system_status_id / user_open_id，先运行 setup.py", file=sys.stderr)
        return 1
    rl = all_rl[source]
    if not rl:
        print(f"no {source} rate_limits found", file=sys.stderr)
        return 1
    title, icon, _ = build_status(rl, now, NAMES[source])
    state = f"{title}|{icon}"
    try:
        last_state = open(STATE_FILE, encoding="utf-8").read().strip()
    except FileNotFoundError:
        last_state = ""

    base = f"{STATUS_API}/{CONFIG['system_status_id']}"
    user = CONFIG["user_open_id"]
    id_params = {"user_id_type": "open_id"}
    if state != last_state:
        lark("PATCH", base, {"system_status": {"title": title, "icon_key": icon}, "update_fields": ["TITLE", "ICON"]})
        lark("POST", base + "/batch_close", {"user_list": [user]}, id_params)
    lark("POST", base + "/batch_open",
         {"user_list": [{"user_id": user, "end_time": str(now + STATUS_TTL)}]}, id_params)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state)
    print(time.strftime("%F %T"), title, icon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
