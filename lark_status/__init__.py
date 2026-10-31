"""把一行字写进飞书状态栏。显示什么由场景决定，场景可以自己加。"""

from .core import (
    ALIASES,
    ICONS,
    StatusConfig,
    StatusWriter,
    char_width,
    fit_title,
    lark_call,
    resolve_icon,
)
from .source import Source, StatefulSource, humanize

__all__ = [
    "ALIASES",
    "ICONS",
    "StatusConfig",
    "StatusWriter",
    "char_width",
    "fit_title",
    "lark_call",
    "resolve_icon",
    "Source",
    "StatefulSource",
    "humanize",
]
__version__ = "0.2.0"
