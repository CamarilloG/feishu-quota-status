"""lark_status 命令行入口。

    lark-status tick                    # 跑一轮（给定时任务/launchd 调用）
    lark-status tick --dry-run          # 只算不写，看会显示什么
    lark-status now                     # 显示当前各场景会算出什么

    lark-status fish start|stop
    lark-status pomodoro start [分钟] | stop

    lark-status setup                   # 一次性：建系统状态、填 config

原有的额度路径不受影响：update.py 照旧工作，launchd 里跑的还是它。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .runner import build_sources, load_config, pick, tick

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")
DEFAULT_STATE = os.path.join(HERE, "state")


def cmd_tick(args) -> int:
    result = tick(args.config, args.state_dir, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_now(args) -> int:
    """把每个场景单独算一遍，方便调顺序。"""
    from .core import fit_title

    cfg = load_config(args.config)
    order = cfg.get("sources") or ["pomodoro", "fish", "quota", "ci"]
    os.makedirs(args.state_dir, exist_ok=True)
    sources = build_sources(cfg, args.state_dir)
    now = int(time.time())

    rows = []
    for name in order:
        src = sources.get(name)
        if not src:
            continue
        try:
            out = src.render(now)
        except Exception as exc:
            rows.append((name, "出错", str(exc)[:60]))
            continue
        rows.append((name, out[1], fit_title(out[0])) if out else (name, "-", "（无内容，让给下一个）"))

    picked = pick(sources, order, now)
    width = max((len(r[0]) for r in rows), default=8)
    for name, icon, title in rows:
        mark = " <- 显示" if picked and picked[0] == name else ""
        print(f"{name.ljust(width)}  {icon:<26} {title}{mark}")
    if not picked:
        print("\n（所有场景都没有内容，会关掉状态）")
    return 0


def cmd_fish(args) -> int:
    from .source import humanize
    from .sources.fish import Fish

    fish = Fish(os.path.join(args.state_dir, "fish.json"))
    if args.action == "start":
        fish.start()
        print("开始摸鱼，状态交给定时任务更新")
    else:
        state = fish.stop()
        print(f"回来了。累计摸鱼 {humanize(state.get('total', 0))}，共 {state.get('sessions', 0)} 次")
    return 0


def cmd_pomodoro(args) -> int:
    from .sources.pomodoro import Pomodoro

    pomo = Pomodoro(os.path.join(args.state_dir, "pomodoro.json"))
    if args.action == "start":
        minutes = args.minutes or 25
        pomo.start(minutes)
        print(f"专注 {minutes} 分钟，开始")
    else:
        pomo.stop()
        print("专注结束")
    return 0


def cmd_setup(args) -> int:
    """创建系统状态并写回 config.json。

    注意：系统状态是全企业共享的定义，每企业最多 10 个，管理员后台可见。
    如果你已经用 setup.py 配好了，这里会跳过（复用现成的 system_status_id）。
    """
    import subprocess

    cfg = load_config(args.config)
    lark_cli = cfg.get("lark_cli", "lark-cli")

    def lark(*argv):
        proc = subprocess.run([lark_cli, *argv], capture_output=True, text=True)
        try:
            res = json.loads(proc.stdout or proc.stderr)
        except ValueError:
            sys.exit(f"lark-cli 输出异常：{(proc.stdout or proc.stderr)[:300]}")
        if not res.get("ok"):
            sys.exit(f"失败：{json.dumps(res.get('error'), ensure_ascii=False)}")
        return res["data"]

    if not str(cfg.get("user_open_id", "")).startswith("ou_"):
        cfg["user_open_id"] = lark("contact", "+get-user", "--as", "user")["user"]["open_id"]
        print("open_id:", cfg["user_open_id"])

    if not str(cfg.get("system_status_id", "")).isdigit():
        body = {"title": args.title, "icon_key": "StatusFlashOfInspiration", "color": "GRAY",
                "priority": args.priority}
        data = lark("api", "POST", "/open-apis/personal_settings/v1/system_statuses",
                    "--as", "bot", "--data", json.dumps(body, ensure_ascii=False))
        cfg["system_status_id"] = data["system_status"]["system_status_id"]
        print("system_status_id:", cfg["system_status_id"])
    else:
        print("复用已有的 system_status_id:", cfg["system_status_id"])

    cfg.setdefault("lark_cli", lark_cli)
    cfg.setdefault("sources", ["pomodoro", "fish", "quota", "ci"])
    with open(args.config, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("已写入", args.config)
    return 0


def _force_utf8_stdio() -> None:
    """Windows 控制台默认 GBK，打 emoji 会抛 UnicodeEncodeError。

    状态文字里全是 🐟🍅⚡，所以统一改成 UTF-8，编不出来退化成 ? 而不是崩掉。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(prog="lark-status", description="把一行字写进飞书状态栏")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--state-dir", default=DEFAULT_STATE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_tick = sub.add_parser("tick", help="跑一轮，给定时任务调用")
    p_tick.add_argument("--dry-run", action="store_true")
    p_tick.set_defaults(func=cmd_tick)

    p_now = sub.add_parser("now", help="看当前各场景会算出什么")
    p_now.set_defaults(func=cmd_now)

    p_fish = sub.add_parser("fish", help="摸鱼计时器")
    p_fish.add_argument("action", choices=["start", "stop"])
    p_fish.set_defaults(func=cmd_fish)

    p_pomo = sub.add_parser("pomodoro", help="番茄钟")
    p_pomo.add_argument("action", choices=["start", "stop"])
    p_pomo.add_argument("minutes", nargs="?", type=int)
    p_pomo.set_defaults(func=cmd_pomodoro)

    p_setup = sub.add_parser("setup", help="一次性初始化（已有配置会复用）")
    p_setup.add_argument("--title", default="lark-status")
    p_setup.add_argument("--priority", type=int, default=9)
    p_setup.set_defaults(func=cmd_setup)

    args = ap.parse_args(argv)
    os.makedirs(args.state_dir, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
