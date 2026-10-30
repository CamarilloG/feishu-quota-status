#!/usr/bin/env python3
"""一次性初始化：查出你的 open_id，在企业里建一个系统状态，写进 config.json。

前提：lark-cli 已登录（user 身份），应用已开通
personal_settings:status:system_status_update 和 personal_settings:status:system_status_operate。
注意系统状态是全企业共享的定义（每个企业最多 10 个），但只会显示在被开启的人身上。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")
EXAMPLE_FILE = os.path.join(HERE, "config.example.json")


def lark(cfg, *args):
    proc = subprocess.run([cfg["lark_cli"], *args], capture_output=True, text=True)
    res = json.loads(proc.stdout or proc.stderr)
    if not res.get("ok"):
        sys.exit(f"lark-cli {' '.join(args[:3])} 失败：{json.dumps(res.get('error'), ensure_ascii=False)}")
    return res["data"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", default="额度加载中", help="系统状态的初始名称，之后会被自动改写")
    ap.add_argument("--priority", type=int, default=9, help="0-9，不能和企业里已有的系统状态重复")
    args = ap.parse_args()

    path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else EXAMPLE_FILE
    cfg = json.load(open(path, encoding="utf-8"))

    if not str(cfg.get("user_open_id", "")).startswith("ou_"):
        cfg["user_open_id"] = lark(cfg, "contact", "+get-user", "--as", "user")["user"]["open_id"]
        print("open_id:", cfg["user_open_id"])

    if not str(cfg.get("system_status_id", "")).isdigit():
        body = {"title": args.title, "icon_key": "StatusFlashOfInspiration", "color": "GRAY",
                "priority": args.priority}
        data = lark(cfg, "api", "POST", "/open-apis/personal_settings/v1/system_statuses",
                    "--as", "bot", "--data", json.dumps(body, ensure_ascii=False))
        cfg["system_status_id"] = data["system_status"]["system_status_id"]
        print("system_status_id:", cfg["system_status_id"])

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("已写入", CONFIG_FILE)


if __name__ == "__main__":
    main()
