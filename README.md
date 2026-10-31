# feishu-quota-status 😵‍💫

> **把 AI 额度、摸鱼时长、CI 状态塞进你的飞书状态栏。**

**额度见底，人已瘫坐。至少让同事知道，你不是在摸鱼，是 AI 先躺了。**

<!--
  首屏图位（占位，请替换）：
  建议截一张飞书聊天窗口的图，你的头像旁边挂着「🏖️ 已陨落 15:49恢复」，
  下面同事回一句「你怎么了？」。
  这种图比任何功能列表都有效——它是个梗，不是广告。
  图放这里：
  <img src="docs/status-demo.png" width="640" alt="飞书状态栏显示 AI 额度已用尽">
-->

```
🏖️ 已陨落 15:49恢复        ← 别找我，我和 AI 一起倒下了
⚡ Claude剩53% 15:49恢复     ← 还能打
⌨️ Claude剩9% 15:49恢复      ← 省着点用，手打代码中

🐟 已摸鱼 47 分钟            ← 离开工位多久了
🍅 专注中 剩 12 分钟          ← 现在不方便被打断
❌ CI 构建挂了               ← 别以为我在忙，是流水线挂了
```

飞书状态栏有几个反直觉的坑：**改文字必须"改名 → 关闭 → 重开"三步**、**名称上限 20 字符且汉字算 2**、**图标只有 18 个 emoji 一个用不了**。这个项目把它们封进一个 `core`，然后给你几个开箱即用的场景。

装完立刻能看到东西，不写代码。想加自己的场景，去看 `lark_status/sources/fish.py`——那 36 行就是全部文档。

> 原本的额度功能**完全不受影响**：`update.py` 和 macOS 菜单栏照旧工作。新东西全是加法。
> 现在也**不再只支持 macOS**：凭证读取按平台分支，Linux / Windows 都能跑。

---

## 快速开始

```bash
pip install -e .
lark-status setup        # 复用你已有的 system_status_id，不会重复创建
lark-status now          # 看看现在会显示什么
lark-status tick         # 真跑一轮
```

已经装过旧版的，`setup` 会检测到现有配置并跳过创建，不会影响你正在用的状态。

## 内置场景

顺序即优先级，写在 `config.json` 的 `sources` 里。某个场景没内容就自动让给下一个，全都没内容就关掉状态：

```json
"sources": ["pomodoro", "fish", "quota", "ci"]
```

### ⚡ quota — AI 订阅额度

原功能，见下面「它在干嘛」。

### 🍅 pomodoro — 番茄钟

```bash
lark-status pomodoro start      # 25 分钟
lark-status pomodoro start 50   # 50 分钟
lark-status pomodoro stop
```

倒计时归零显示「专注结束」，不会自动消失——得你自己 stop，同事才知道你空出来了。

### 🐟 fish — 摸鱼计时器

```bash
lark-status fish start     # 起身走人
lark-status fish stop      # 回来了，顺手清零
```

跨天也算得对。超过 2 小时图标从 `Coffee` 换成 `StatusEnjoyLife`（更张扬）。

### ❌ ci — 构建状态

```json
"ci": { "repo": "you/repo", "branch": "main" }
```

**只有不绿的时候才占位置**——成功了返回 `None`，不会因为"CI 又绿了"白占一行。公开仓库免 token。

## 加自己的场景

场景就是「给我一个时间戳，还我一行字」：

```python
# lark_status/sources/coffee.py
from ..source import StatefulSource

class Coffee(StatefulSource):
    name = "coffee"

    def render(self, now):
        cups = self.read_state().get("cups", 0)
        if cups < 3:
            return None                        # 没内容，让给下一个
        return f"☕️ 已灌 {cups} 杯", "Coffee"    # 图标用别名就行
```

在 `runner.py` 的 `build_sources()` 加一行注册，再写进 `config.json` 的 `sources`。就这样。

`render` 抛异常不会拖垮别的场景，返回 `None` 表示"此刻没我什么事"。

## 试的时候不用连飞书

```bash
lark-status now              # 每个场景单独算出什么，谁会被显示
lark-status tick --dry-run   # 完整走一遍，只算不写
```

## 开发

```bash
python -m pytest tests -q
```

31 个测试，覆盖字符宽度、18 个图标、三步刷新、同文只续期、场景边界。不联网、不需要凭证。

---

## 它在干嘛（原额度功能，未改动）

| 剩余额度 | 飞书图标 | 文字 | 精神状态 |
|---|---|---|---|
| ≥ 30% | ⚡ 灵感闪电 | `Claude剩53% 15:49恢复` | 意气风发 |
| 1% – 29% | ⌨️ 打字 | `Claude剩9% 15:49恢复` | 开始心慌 |
| 0% | 🏖️ 度假 | `已陨落 15:49恢复` | 眩晕瘫坐 |

- 有 5 小时窗口时看 5 小时窗口，显示恢复**时刻**；只有周额度（比如某些 Pro 套餐）就看周窗口，显示恢复**日期**。
- 任一窗口用完就算「已陨落」，恢复时间取用完的那个窗口里最晚的。
- 时区可配，默认 UTC+8。
- 电脑合盖了？状态 30 分钟后自己过期，不会挂着过时的数字骗人。

## 数据从哪来

| | 来源 | 刷新 |
|---|---|---|
| **Claude** | 本机终端 `claude` 的登录 token → `api.anthropic.com/api/oauth/usage` | 跟着你用 Claude 的节奏：10 分钟内有会话活动就每 10 分钟查，2 小时内有活动每 30 分钟查，再久不查，用最后的数据推算 |
| **Codex** | `~/.codex/sessions` 里的会话日志（`rate_limits` + 「hit your usage limit」报错） | Codex 跑着就有新数据 |

> 为什么 Claude 不用 statusline？因为桌面 App 不跑 statusline。`claude_statusline.py` 还是留着了，终端党可以接上当备用数据源。

## 需要什么

- Python 3（系统自带的 `/usr/bin/python3` 就行，零第三方依赖）
- [lark-cli](https://open.feishu.cn)，已登录，用的是**企业自建应用**
- Claude Pro / Max 订阅，并且在终端登录过一次 `claude`（只看 Codex 的话不需要）
- macOS 菜单栏应用要 14+；只要命令行工具的话**不用装 Xcode**

## 上手

**1. 给飞书应用开权限**（开发者后台 → 权限管理，开完记得发版）

- `personal_settings:status:system_status_update`：创建、修改系统状态
- `personal_settings:status:system_status_operate`：给用户开启、关闭系统状态

**2. 初始化**：查出你的 open_id，在企业里建一个系统状态，写进 `config.json`

```bash
python3 setup.py            # 优先级默认 9，和已有系统状态冲突就加 --priority 8
```

**3. 登录 Claude**（只看 Codex 的话跳过）

```bash
claude                      # 走一遍登录，token 会存进钥匙串
```

**4. 装上**：两个 LaunchAgent（定时任务 + 开机启动菜单栏），并编译菜单栏应用

```bash
./install.sh                # 当前 shell 的 HTTPS_PROXY 会被带进去，开代理的同学不用额外配
```

完事。菜单栏出现 `⚡ C 53%`，飞书头像旁边出现你的额度。

## 配置 `config.json`

```json
{
  "source": "claude",                       // 飞书显示谁：claude / codex（菜单栏也能切）
  "lark_cli": "/opt/homebrew/bin/lark-cli",
  "claude_cli": "claude",                   // 用来续期 token 的官方 CLI
  "system_status_id": "…",                  // setup.py 填
  "user_open_id": "ou_…",                   // setup.py 填
  "utc_offset_hours": 8,

  "sources": ["pomodoro", "fish", "quota", "ci"],   // 新增：场景优先级
  "ci": { "repo": "you/repo", "branch": "main" }    // 新增：CI 场景
}
```

图标、档位阈值、查询节奏在 `update.py` 顶部的常量里，自己改。

## 菜单栏 QuotaBar

- 标题：`⚡ C 53%` / `⌨️ X 9%` / `🏖️ C 陨落`（C = Claude，X = Codex）
- 点开：两边的 5 小时 / 本周余量和恢复时间、切换飞书显示、立即刷新、打开日志
- 改了代码重新编译：`menubar/build.sh`

## ⚠️ 先说清楚

- **系统状态是全企业共享的定义**：每个企业最多 10 个，管理员后台看得见。但它只会显示在被开启的人身上，也就是你自己。
- **飞书只认 18 个官方状态图标**，表情回复里那堆骷髅、吐血都用不了（试过了，不行 💀）。
- **状态名称最多 20 个字符**（一个汉字算 2 个）。超长会自动去掉空格，所以你可能会看到 `Claude剩53%15:49恢复`。
- `/api/oauth/usage` 和 Claude Code 的 OAuth client **都不是公开文档接口**，哪天变了就会挂。
- token 快过期时，脚本**不自己续期**：`platform.claude.com` 有 Cloudflare 拦非官方客户端（error 1010），硬绕不体面。它会跑一次官方 `claude -p ok --model haiku --no-session-persistence`，让 CLI 自己续期、自己写钥匙串。大约 8 小时一次，每次吃一丁点额度。脚本全程只读钥匙串。
- 和 Anthropic、OpenAI、飞书都没有任何关系。纯属打工人自救。

## 卸载

```bash
./uninstall.sh              # 删 LaunchAgent 和菜单栏应用；config 和飞书里的系统状态保留
```

---

## English TL;DR

**Put your Claude / Codex quota, idle time, or CI status into your Feishu (Lark) status bar.**

The original quota feature works exactly as before (`update.py` + macOS menubar, untouched). New in 0.2: the status-bar plumbing is extracted into `lark_status/core.py`, with pluggable sources (quota / pomodoro / idle timer / CI) and cross-platform credential handling.

- ⚡ ≥30% left · ⌨️ 1–29% · 🏖️ `已陨落` ("fallen") with the reset time
- Claude: queries `/api/oauth/usage` with the token from the terminal `claude` login in your keychain, and polls more often while you're actively using Claude. When the token expires, it lets the official `claude` CLI refresh it (one tiny haiku request, no saved session) instead of calling the token endpoint itself. Codex: parses `~/.codex/sessions` logs.
- Setup: grant the two `personal_settings` scopes to your Feishu app → `python3 setup.py` → `claude` (log in once) → `./install.sh`.
- Uses undocumented endpoints; may break. Not affiliated with Anthropic, OpenAI, or ByteDance.

## License

[MIT](LICENSE)
