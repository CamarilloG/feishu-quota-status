"""调度：按 config 里 sources 的顺序问每个场景「现在显示什么」，取第一个有答案的。

顺序是有意义的——写在前面 = 优先级高。比如：

    "sources": ["pomodoro", "fish", "quota", "ci"]

就是「专注中」盖住一切，其次摸鱼，再其次额度。CI 成功了会返回 None，自然不占位置。
"""

from __future__ import annotations

import json
import os
import time

from .sources.ci import CI
from .sources.fish import Fish
from .sources.pomodoro import Pomodoro
from .sources.quota import Quota

DEFAULT_ORDER = ["pomodoro", "fish", "quota", "ci"]


def build_sources(cfg: dict, state_dir: str) -> dict:
    """按 config 造出所有场景实例。没配置的场景也造，只是 render 会返回 None。"""
    def sfile(name: str) -> str:
        return os.path.join(state_dir, f"{name}.json")

    # claude_cli 在顶层（和 update.py 共用一个配置项），也允许 quota 内覆盖
    quota_cfg = dict(cfg.get("quota") or {})
    if "claude_cli" not in quota_cfg and cfg.get("claude_cli"):
        quota_cfg["claude_cli"] = cfg["claude_cli"]

    return {
        "pomodoro": Pomodoro(sfile("pomodoro")),
        "fish": Fish(sfile("fish")),
        "quota": Quota(quota_cfg),
        "ci": CI(cfg.get("ci") or {}),
    }


def pick(sources: dict, order: list[str], now: int) -> tuple[str, tuple[str, str]] | None:
    """返回 (场景名, (文字, 图标))，全都没有内容时返回 None。"""
    for name in order:
        src = sources.get(name)
        if not src:
            continue
        try:
            out = src.render(now)
        except Exception as exc:
            print(f"[{name}] 出错，跳过：{exc}")
            continue
        if out:
            title, icon = out
            return name, (title, icon)
    return None


def load_config(path: str = "config.json") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, ValueError):
        return {}


def tick(cfg_path: str = "config.json", state_dir: str = "state", dry_run: bool = False) -> dict:
    """跑一轮：选出该显示什么，然后写进去。返回回执。"""
    from .core import StatusConfig, StatusWriter

    cfg = load_config(cfg_path)
    order = cfg.get("sources") or list(DEFAULT_ORDER)
    os.makedirs(state_dir, exist_ok=True)

    sources = build_sources(cfg, state_dir)
    now = int(time.time())
    picked = pick(sources, order, now)

    writer = StatusWriter(
        StatusConfig.load(cfg_path),
        state_file=os.path.join(state_dir, "last_state"),
        dry_run=dry_run,
    )

    if picked is None:
        if not dry_run:
            writer.clear()
        return {"shown": None, "cleared": True}

    name, (title, icon) = picked
    result = writer.push(title, icon)
    return {"shown": name, **result}
