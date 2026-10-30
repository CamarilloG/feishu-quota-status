#!/bin/bash
# 卸载 LaunchAgent 和菜单栏应用。config.json、日志、飞书里的系统状态都不动。
set -uo pipefail
LABEL="${LAUNCHD_LABEL:-io.github.camarillog.feishu-quota-status}"
AGENTS="$HOME/Library/LaunchAgents"
for l in "$LABEL" "$LABEL.menubar"; do
  launchctl bootout "gui/$(id -u)/$l" 2>/dev/null
  rm -f "$AGENTS/$l.plist"
done
pkill -x QuotaBar 2>/dev/null
rm -rf "$HOME/Applications/QuotaBar.app"
echo "卸载完成"
