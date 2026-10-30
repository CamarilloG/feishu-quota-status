#!/bin/bash
# 编译菜单栏应用并装到 ~/Applications/QuotaBar.app（ad-hoc 签名，不需要 Xcode）
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$(cd .. && pwd)"
LABEL="${LAUNCHD_LABEL:-io.github.camarillog.feishu-quota-status}"
APP="$HOME/Applications/QuotaBar.app"
mkdir -p build "$APP/Contents/MacOS"
cat > build/Paths.swift <<SWIFT
let projectDir = "$PROJECT_DIR"
let launchdLabel = "$LABEL"
SWIFT
swiftc -O -parse-as-library -swift-version 5 -target arm64-apple-macosx14.0 \
  QuotaBar.swift build/Paths.swift -o build/QuotaBar
cp build/QuotaBar "$APP/Contents/MacOS/QuotaBar"
cp Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"
echo "installed $APP"
