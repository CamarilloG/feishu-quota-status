"""番茄钟：让同事知道你现在能不能被打断。

用法：
    lark-status pomodoro start          # 默认 25 分钟
    lark-status pomodoro start -- 50    # 50 分钟
    lark-status pomodoro stop           # 提前结束

倒计时归零后显示「专注结束」，不会自动消失——你得自己 stop，这样同事才知道你空出来了。
"""

from __future__ import annotations

from ..source import StatefulSource, humanize, now_ts


class Pomodoro(StatefulSource):
    name = "pomodoro"

    def start(self, minutes: int = 25, now: int | None = None) -> dict:
        now = now or now_ts()
        state = {"started": now, "ends": now + minutes * 60, "minutes": minutes}
        self.write_state(state)
        return state

    def stop(self, now: int | None = None) -> dict:
        self.write_state({})
        return {}

    def render(self, now: int) -> tuple[str, str] | None:
        state = self.read_state()
        ends = state.get("ends")
        if not ends:
            return None
        left = ends - now
        if left <= 0:
            over = humanize(-left)
            return f"🍅 专注结束 {over}前", "GeneralSun"
        return f"🍅 专注中 剩 {humanize(left)}", "GeneralMoonRest"
