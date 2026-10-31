"""场景的契约。写一个新场景 = 实现这个接口，20 行足够。

    class Fish:
        name = "fish"

        def render(self, now: int) -> tuple[str, str] | None:
            return "🐟 已摸鱼 47 分钟", "Coffee"

返回 None 表示这个场景此刻没有内容可显示（core 会跳过它，轮到下一个启用的场景）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol


class Source(Protocol):
    name: str

    def render(self, now: int) -> tuple[str, str] | None:
        """返回 (显示文字, 图标)。图标可以用 core.ALIASES 里的别名。"""
        ...


class StatefulSource:
    """给需要读本地状态的场景用的基类。子类只要实现 render。"""

    name = "base"

    def __init__(self, state_file: str):
        self.state_file = state_file

    def read_state(self) -> dict:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f) or {}
        except (FileNotFoundError, ValueError):
            return {}

    def write_state(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_file)


def humanize(seconds: float) -> str:
    """把秒数写成人话：47 分钟 / 2 小时 15 分 / 3 天。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rem_min = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时 {rem_min} 分" if rem_min else f"{hours} 小时"
    days, rem_h = divmod(hours, 24)
    return f"{days} 天 {rem_h} 小时" if rem_h else f"{days} 天"


def now_ts() -> int:
    return int(time.time())
