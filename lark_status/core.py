"""飞书状态栏的坑，只在这里解决。别的东西一概不管。

这个模块存在的唯一理由：飞书系统状态那几个反直觉的约束，每个踩过的人都得重踩一遍。

  1. 改文字不能只 PATCH —— 必须 PATCH 名称 -> batch_close -> batch_open 三步，
     否则客户端不刷新，你会盯着旧数字怀疑自己代码没跑。
  2. 状态名上限 20，且一个汉字算 2 个字符；超长不会报错，只是吞空格。
  3. 图标只有 18 个官方枚举，emoji 一个都用不了。
  4. sync_setting.end_time 是唯一能让状态自动过期的开关，电脑合盖后不设它就挂假数据。
  5. 所有写操作都要 user_id_type=open_id，且 system_status 是全企业共享的定义。

update.py（原额度路径）和 lark_status.cli（新场景路径）都走这里，保证行为一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass

# 飞书系统状态名称上限：1 个汉字算 2 个字符
TITLE_MAX = 20

# 全部 18 个官方图标。emoji 一律用不了，别试了。
ICONS = (
    "GeneralDoNotDisturb", "GeneralInMeetingBusy", "Coffee", "GeneralBusinessTrip",
    "GeneralWorkFromHome", "StatusEnjoyLife", "GeneralTravellingCar", "StatusBus",
    "StatusInFlight", "Typing", "EatingFood", "SICK",
    "GeneralSun", "GeneralMoonRest", "StatusReading", "Status_PrivateMessage",
    "StatusFlashOfInspiration", "GeneralVacation",
)

# 给下面几个常用图标起个人话的名字，省得每次查表
ALIASES = {
    "busy": "GeneralDoNotDisturb",
    "meeting": "GeneralInMeetingBusy",
    "coffee": "Coffee",
    "trip": "GeneralBusinessTrip",
    "home": "GeneralWorkFromHome",
    "fun": "StatusEnjoyLife",
    "car": "GeneralTravellingCar",
    "flight": "StatusInFlight",
    "typing": "Typing",
    "eat": "EatingFood",
    "sick": "SICK",
    "sun": "GeneralSun",
    "moon": "GeneralMoonRest",
    "read": "StatusReading",
    "dm": "Status_PrivateMessage",
    "flash": "StatusFlashOfInspiration",
    "vacation": "GeneralVacation",
}

STATUS_API = "/open-apis/personal_settings/v1/system_statuses"

# 状态默认 30 分钟自动过期，电脑合盖后不会挂着过时的数字骗同事
DEFAULT_TTL = 30 * 60


def char_width(s: str) -> int:
    """按飞书规则算宽度：一个汉字算 2 个字符。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def fit_title(title: str) -> str:
    """把标题塞进 20 字符上限。超长先删空格，还超就硬截断。"""
    title = " ".join(str(title).split())
    if char_width(title) <= TITLE_MAX:
        return title
    squeezed = title.replace(" ", "")
    if char_width(squeezed) <= TITLE_MAX:
        return squeezed
    out, used = [], 0
    for ch in squeezed:
        w = 2 if ord(ch) > 127 else 1
        if used + w > TITLE_MAX:
            break
        out.append(ch)
        used += w
    return "".join(out)


def resolve_icon(icon: str | None) -> str:
    """接受别名、官方名或 None。给错了直接报错，别悄悄退化成默认值。"""
    if not icon:
        return "GeneralSun"
    key = ALIASES.get(icon.lower(), icon)
    if key not in ICONS:
        raise ValueError(
            f"未知图标 {icon!r}。可用别名：{', '.join(sorted(ALIASES))}；"
            f"或 18 个官方名之一：{', '.join(ICONS)}"
        )
    return key


def lark_call(lark_cli: str, method: str, path: str, data: dict,
              params: dict | None = None) -> dict:
    """调一次 lark-cli，失败就抛。update.py 和 StatusWriter 共用。"""
    cmd = [lark_cli, "api", method, path, "--as", "bot",
           "--data", json.dumps(data, ensure_ascii=False)]
    if params:
        cmd += ["--params", json.dumps(params)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        res = json.loads(proc.stdout or proc.stderr)
    except ValueError:
        raise RuntimeError(f"{method} {path} 返回的不是 JSON：{(proc.stdout or proc.stderr)[:300]}")
    if not res.get("ok"):
        raise RuntimeError(f"{method} {path} 失败：{json.dumps(res.get('error'), ensure_ascii=False)}")
    return res


@dataclass
class StatusConfig:
    """飞书这段的全部配置。setup.py 会帮你填后两个。"""

    lark_cli: str = "lark-cli"
    system_status_id: str = ""
    user_open_id: str = ""
    ttl: int = DEFAULT_TTL

    @classmethod
    def load(cls, path: str = "config.json") -> "StatusConfig":
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (FileNotFoundError, ValueError):
            raw = {}
        return cls(
            lark_cli=raw.get("lark_cli", "lark-cli"),
            system_status_id=str(raw.get("system_status_id") or ""),
            user_open_id=str(raw.get("user_open_id") or ""),
            ttl=int(raw.get("ttl") or DEFAULT_TTL),
        )

    @property
    def ready(self) -> bool:
        return bool(self.system_status_id and self.user_open_id)


class StatusWriter:
    """把一行字写进飞书个人状态栏。不关心这行字是怎么算出来的。"""

    def __init__(self, cfg: StatusConfig, state_file: str = ".last_state", dry_run: bool = False):
        self.cfg = cfg
        self.state_file = state_file
        self.dry_run = dry_run

    # ---------- 对外只有这两个方法 ----------

    def push(self, title: str, icon: str | None = None) -> dict:
        """写一条状态。返回做了什么的回执，便于测试和 dry-run。"""
        title = fit_title(title)
        icon = resolve_icon(icon)
        state = f"{title}|{icon}"

        if self.dry_run:
            return {"dry_run": True, "title": title, "icon": icon, "changed": state != self._last_state()}

        if not self.cfg.ready:
            raise RuntimeError("config.json 缺少 system_status_id / user_open_id，先运行 setup.py")

        now = int(time.time())
        base = f"{STATUS_API}/{self.cfg.system_status_id}"
        params = {"user_id_type": "open_id"}
        changed = state != self._last_state()

        if changed:
            # 第 1 步：改名称。只做这一步客户端不会刷新，必须配合下面的关-开
            lark_call(self.cfg.lark_cli, "PATCH", base, {
                "system_status": {"title": title, "icon_key": icon},
                "update_fields": ["TITLE", "ICON"],
            })
            # 第 2 步：关掉
            lark_call(self.cfg.lark_cli, "POST", base + "/batch_close",
                      {"user_list": [self.cfg.user_open_id]}, params)

        # 第 3 步（也是文字没变时唯一的一步）：重开，并续上过期时间
        lark_call(self.cfg.lark_cli, "POST", base + "/batch_open", {
            "user_list": [{"user_id": self.cfg.user_open_id, "end_time": str(now + self.cfg.ttl)}],
        }, params)

        self._save_state(state)
        return {"title": title, "icon": icon, "changed": changed}

    def refresh(self) -> dict:
        """只续期，不改文字。文字没变时用它，省两次请求。"""
        if self.dry_run:
            return {"dry_run": True, "refreshed": True}
        if not self.cfg.ready:
            raise RuntimeError("config.json 缺少 system_status_id / user_open_id，先运行 setup.py")
        now = int(time.time())
        base = f"{STATUS_API}/{self.cfg.system_status_id}"
        lark_call(self.cfg.lark_cli, "POST", base + "/batch_open", {
            "user_list": [{"user_id": self.cfg.user_open_id, "end_time": str(now + self.cfg.ttl)}],
        }, {"user_id_type": "open_id"})
        return {"refreshed": True}

    def clear(self) -> dict:
        """关掉状态。用于所有场景都没有内容时。"""
        if self.dry_run:
            return {"dry_run": True, "cleared": True}
        if not self.cfg.ready:
            raise RuntimeError("config.json 缺少 system_status_id / user_open_id，先运行 setup.py")
        base = f"{STATUS_API}/{self.cfg.system_status_id}"
        lark_call(self.cfg.lark_cli, "POST", base + "/batch_close",
                  {"user_list": [self.cfg.user_open_id]}, {"user_id_type": "open_id"})
        self._save_state("")
        return {"cleared": True}

    # ---------- 内部 ----------

    def _last_state(self) -> str:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""

    def _save_state(self, state: str) -> None:
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(state)
        os.replace(tmp, self.state_file)
