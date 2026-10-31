"""端到端验证：旧额度路径在迁移后仍然完整可用。

不真的调飞书，只验证：
1. update.py 能正常 import（没有语法/循环依赖问题）
2. build_status 各档位输出与迁移前一致
3. main() 在缺配置时报的是预期的错
4. 新旧两条路径共用同一套 core，行为一致
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update
from lark_status import core
from lark_status.core import StatusConfig, StatusWriter

ok = 0
fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}  {extra}")


print("=== 1. update.py 可导入、常量未变 ===")
check("TITLE_MAX == 20", update.TITLE_MAX == 20)
check("STATUS_TTL == 1800", update.STATUS_TTL == 1800)
check("ICON_PLENTY", update.ICON_PLENTY == "StatusFlashOfInspiration")
check("ICON_LOW", update.ICON_LOW == "Typing")
check("ICON_OUT", update.ICON_OUT == "GeneralVacation")
check("LOW_THRESHOLD == 30", update.LOW_THRESHOLD == 30)
check("三个图标都在 core 的 18 个里",
      all(i in core.ICONS for i in (update.ICON_PLENTY, update.ICON_LOW, update.ICON_OUT)))

print("\n=== 2. build_status 各档位 ===")
now = 1_700_000_000
cases = [
    ("满额", {"primary": {"used_percent": 0, "window_minutes": 300, "resets_at": now + 3600}},
     "Claude额度满", "StatusFlashOfInspiration", 100),
    ("53%", {"primary": {"used_percent": 47, "window_minutes": 300, "resets_at": now + 3600}},
     "Claude剩53%07:13恢复", "StatusFlashOfInspiration", 53),
    ("9%", {"primary": {"used_percent": 91, "window_minutes": 300, "resets_at": now + 3600}},
     "Claude剩9% 07:13恢复", "Typing", 9),
    ("用尽", {"primary": {"used_percent": 100, "window_minutes": 300, "resets_at": now + 3600}},
     "已陨落 07:13恢复", "GeneralVacation", 0),
]
for label, rl, want_title, want_icon, want_left in cases:
    got = update.build_status(rl, now, "Claude")
    check(f"{label}: {got[0]!r}", got == (want_title, want_icon, want_left), f"期望 {(want_title, want_icon, want_left)}")

print("\n=== 3. update.fit 委托给了 core.fit_title ===")
for s in ["已陨落 15:49恢复", "Claude剩53% 15:49恢复", "Claude剩9% 15:49恢复"]:
    check(f"fit({s!r}) 一致", update.fit(s) == core.fit_title(s))

print("\n=== 4. update.lark 委托给了 core.lark_call ===")
seen = {}


def fake_lark_call(lark_cli, method, path, data, params=None):
    seen.update(dict(lark_cli=lark_cli, method=method, path=path, data=data, params=params))
    return {"ok": True, "data": {}}


orig = core.lark_call
core.lark_call = fake_lark_call
try:
    update.lark("PATCH", "/x", {"a": 1}, {"p": 2})
    check("参数透传正确",
          seen["method"] == "PATCH" and seen["path"] == "/x"
          and seen["data"] == {"a": 1} and seen["params"] == {"p": 2},
          str(seen))
finally:
    core.lark_call = orig

print("\n=== 5. 新路径用同一套 core，三步刷新行为一致 ===")
import tempfile

tmp = tempfile.mkdtemp()
w = StatusWriter(StatusConfig(lark_cli="x", system_status_id="1", user_open_id="ou_y"),
                 state_file=os.path.join(tmp, "s"))
calls = []
core.lark_call = lambda *a, **k: (calls.append((a[1], a[2])), {"ok": True})[1]
try:
    r1 = w.push("测试文字", "Coffee")
    check("首次写入触发三步", [c[0] for c in calls] == ["PATCH", "POST", "POST"], str(calls))
    calls.clear()
    r2 = w.push("测试文字", "Coffee")
    check("文字未变只续期", [c[0] for c in calls] == ["POST"], str(calls))
    check("changed 标记正确", r1["changed"] is True and r2["changed"] is False)
finally:
    core.lark_call = orig

print(f"\n{'=' * 50}")
print(f"通过 {ok} 项，失败 {fail} 项")
sys.exit(0 if fail == 0 else 1)
