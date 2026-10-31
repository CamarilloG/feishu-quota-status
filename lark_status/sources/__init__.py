"""内置场景。加新场景就在这注册，然后写进 config.json 的 sources 列表。"""

from .ci import CI
from .fish import Fish
from .pomodoro import Pomodoro
from .quota import Quota

__all__ = ["CI", "Fish", "Pomodoro", "Quota"]
