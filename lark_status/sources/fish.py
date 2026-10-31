"""摸鱼计时器：统计你离开工位多久了。

用法：
    lark-status fish start     # 起身走人
    lark-status fish stop      # 回来了，顺手把这一趟清零

状态里显示的是「从上次 start 到现在」的时长，跨天也算得对。
"""

from __future__ import annotations

from ..source import StatefulSource, humanize, now_ts


class Fish(StatefulSource):
    name = "fish"

    def start(self, now: int | None = None) -> dict:
        now = now or now_ts()
        state = self.read_state()
        state["since"] = now
        state["sessions"] = state.get("sessions", 0) + 1
        state["total"] = state.get("total", 0)
        self.write_state(state)
        return state

    def stop(self, now: int | None = None) -> dict:
        now = now or now_ts()
        state = self.read_state()
        since = state.get("since")
        if since:
            state["total"] = state.get("total", 0) + (now - since)
            state.pop("since", None)
            self.write_state(state)
        return state

    def render(self, now: int) -> tuple[str, str] | None:
        state = self.read_state()
        since = state.get("since")
        if not since:
            return None
        minutes = (now - since) / 60
        # 摸鱼超过 2 小时就换个说法，同事一看就懂
        icon = "Coffee" if minutes < 120 else "StatusEnjoyLife"
        return f"🐟 已摸鱼 {humanize(now - since)}", icon
