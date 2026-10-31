#!/bin/bash
# 安装两个 LaunchAgent：每 10 分钟跑一次 update.py；登录时打开菜单栏应用。
# 当前 shell 里的 HTTPS_PROXY / HTTP_PROXY 会被带进 launchd 环境。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="${LAUNCHD_LABEL:-io.github.camarillog.feishu-quota-status}"
AGENTS="$HOME/Library/LaunchAgents"
UID_DOMAIN="gui/$(id -u)"

if ! /usr/bin/python3 -c "import json,sys; c=json.load(open('$DIR/config.json')); sys.exit(0 if str(c.get('system_status_id','')).isdigit() else 1)" 2>/dev/null; then
  echo "config.json 还没配好，先运行：python3 setup.py" >&2
  exit 1
fi

proxy_env=""
for k in HTTPS_PROXY HTTP_PROXY; do
  if [ -n "${!k:-}" ]; then proxy_env+="    <key>$k</key><string>${!k}</string>"$'\n'; fi
done

mkdir -p "$AGENTS"
cat > "$AGENTS/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>$DIR/update.py</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
$proxy_env  </dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/update.log</string>
  <key>StandardErrorPath</key><string>$DIR/update.log</string>
</dict>
</plist>
EOF

LAUNCHD_LABEL="$LABEL" "$DIR/menubar/build.sh"

cat > "$AGENTS/$LABEL.menubar.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL.menubar</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>-a</string><string>$HOME/Applications/QuotaBar.app</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

for l in "$LABEL" "$LABEL.menubar"; do
  launchctl bootout "$UID_DOMAIN/$l" 2>/dev/null || true
  launchctl bootstrap "$UID_DOMAIN" "$AGENTS/$l.plist"
done
echo "装好了：$LABEL（每 10 分钟）+ 菜单栏 QuotaBar"
