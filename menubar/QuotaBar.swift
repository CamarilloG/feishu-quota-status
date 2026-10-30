// 菜单栏显示 Claude / Codex 剩余额度，并可切换飞书状态显示哪一边。
// 只读 status.json、只改 config.json 的 source；取数和更新飞书仍由 update.py（launchd）负责。
// projectDir / launchdLabel 由 build.sh 生成在 Paths.swift 里。
import AppKit
import SwiftUI

let baseDir = URL(fileURLWithPath: projectDir)
let statusURL = baseDir.appendingPathComponent("status.json")
let configURL = baseDir.appendingPathComponent("config.json")
let logURL = baseDir.appendingPathComponent("update.log")
let names = ["claude": "Claude", "codex": "Codex"]
let displayTZ: TimeZone = {
    let cfg = (try? Data(contentsOf: configURL)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    let hours = (cfg?["utc_offset_hours"] as? Double) ?? 8
    return TimeZone(secondsFromGMT: Int(hours * 3600))!
}()

struct Window: Decodable {
    let window_minutes: Int?
    let used_percent: Double
    let resets_at: Double?
}

struct SourceStatus: Decodable {
    let title: String
    let icon: String
    let left: Int
    let windows: [Window]
}

struct Status: Decodable {
    let updated_at: Double
    let source: String
    let sources: [String: SourceStatus?]
}

func format(_ epoch: Double?, _ pattern: String) -> String {
    guard let epoch else { return "?" }
    let f = DateFormatter()
    f.timeZone = displayTZ
    f.dateFormat = pattern
    return f.string(from: Date(timeIntervalSince1970: epoch))
}

func windowLine(_ w: Window) -> String {
    let short = (w.window_minutes ?? 0) <= 300
    let label = short ? "5小时" : "本周"
    let now = Date().timeIntervalSince1970
    if let r = w.resets_at, r <= now { return "\(label)  已恢复" }
    let left = max(0, Int((100 - w.used_percent).rounded()))
    return "\(label)  剩\(left)% · \(format(w.resets_at, short ? "HH:mm" : "MM/dd HH:mm"))恢复"
}

@MainActor
final class Model: ObservableObject {
    @Published var status: Status?
    private var timer: Timer?

    init() {
        load()
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { _ in
            Task { @MainActor in self.load() }
        }
    }

    func load() {
        guard let data = try? Data(contentsOf: statusURL),
              let s = try? JSONDecoder().decode(Status.self, from: data) else { return }
        status = s
    }

    var menuTitle: String {
        guard let s = status, let cur = s.sources[s.source] ?? nil else { return "额度 --" }
        let letter = s.source == "claude" ? "C" : "X"
        return cur.left == 0 ? "\(letter) 陨落" : "\(letter) \(cur.left)%"
    }

    var symbol: String {
        guard let s = status, let cur = s.sources[s.source] ?? nil else { return "questionmark.circle" }
        if cur.left == 0 { return "beach.umbrella" }
        return cur.left < 30 ? "keyboard" : "bolt.fill"
    }

    func setSource(_ source: String) {
        var cfg = (try? Data(contentsOf: configURL))
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        cfg["source"] = source
        try? JSONSerialization.data(withJSONObject: cfg, options: [.prettyPrinted, .sortedKeys])
            .write(to: configURL, options: .atomic)
        refreshNow()
    }

    func refreshNow() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = ["kickstart", "-k", "gui/\(getuid())/\(launchdLabel)"]
        try? p.run()
        p.waitUntilExit()
        // update.py 跑完通常要几秒，稍后重读
        for delay in [3.0, 8.0, 15.0] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { self.load() }
        }
    }
}

@main
struct QuotaBarApp: App {
    @StateObject private var model = Model()

    var body: some Scene {
        MenuBarExtra {
            if let s = model.status {
                ForEach(["claude", "codex"], id: \.self) { key in
                    Section(names[key]! + (s.source == key ? "（飞书显示中）" : "")) {
                        if let src = s.sources[key] ?? nil {
                            ForEach(Array(src.windows.enumerated()), id: \.offset) { _, w in
                                Text(windowLine(w))
                            }
                        } else {
                            Text("暂无数据")
                        }
                    }
                }
                Divider()
                // 不用 Picker：菜单里的 Picker 会在没点击时回调 setter，把切换改回去
                ForEach(["claude", "codex"], id: \.self) { key in
                    Button((s.source == key ? "✓ " : "    ") + "飞书显示 " + names[key]!) {
                        if s.source != key { model.setSource(key) }
                    }
                }
                Text("更新于 \(format(s.updated_at, "MM/dd HH:mm"))")
            } else {
                Text("还没有 status.json")
            }
            Button("立即刷新") { model.refreshNow() }
            Button("打开日志") { NSWorkspace.shared.open(logURL) }
            Divider()
            Button("退出") { NSApp.terminate(nil) }
        } label: {
            Label(model.menuTitle, systemImage: model.symbol)
                .labelStyle(.titleAndIcon)
        }
    }
}
