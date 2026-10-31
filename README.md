# feishu-quota-status 😵‍💫

> **飞书状态栏订阅额度** · Your Claude / Codex quota, live in your Feishu status.
>
> 额度见底，人已瘫坐。至少让同事知道，你不是在摸鱼，是 AI 先躺了。

```
⚡ Claude剩53% 15:49恢复      ← 还能打
⌨️ Claude剩9% 15:49恢复       ← 省着点用，手打代码中
🏖️ 已陨落 15:49恢复           ← 别找我，我和 AI 一起倒下了
```

每 10 分钟把 Claude（或 Codex）订阅的剩余额度写进你的**飞书个人状态**，同事点开你头像就知道：
你现在是满血 10x 工程师，还是额度清零、瘫在工位上等 5 小时窗口重置的普通人。

顺手送一个 macOS **菜单栏小玩意儿**，两边额度一眼看全，一键切换飞书显示谁。

---

## 它在干嘛

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

写飞书走的是**飞书系统状态** API（`personal_settings/v1/system_statuses`）：改名 → 关闭 → 重开，客户端才会刷新文字。

## 需要什么

- macOS（菜单栏应用要 14+；只要命令行工具，**不用装 Xcode**）
- Python 3（系统自带的 `/usr/bin/python3` 就行，零第三方依赖）
- [lark-cli](https://open.feishu.cn)，已登录，用的是**企业自建应用**
- Claude Pro / Max 订阅，并且在终端登录过一次 `claude`（只看 Codex 的话不需要）

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
  "utc_offset_hours": 8
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

Puts your **Claude / Codex subscription quota** into your **Feishu (Lark) status**, refreshed every 10 minutes, plus a tiny macOS menu bar app.

- ⚡ ≥30% left · ⌨️ 1–29% · 🏖️ `已陨落` ("fallen") with the reset time
- Claude: queries `/api/oauth/usage` with the token from the terminal `claude` login in your keychain, and polls more often while you're actively using Claude. When the token expires, it lets the official `claude` CLI refresh it (one tiny haiku request, no saved session) instead of calling the token endpoint itself. Codex: parses `~/.codex/sessions` logs.
- Setup: grant the two `personal_settings` scopes to your Feishu app → `python3 setup.py` → `claude` (log in once) → `./install.sh`.
- Uses undocumented endpoints; may break. Not affiliated with Anthropic, OpenAI, or ByteDance.

## License

[MIT](LICENSE)
