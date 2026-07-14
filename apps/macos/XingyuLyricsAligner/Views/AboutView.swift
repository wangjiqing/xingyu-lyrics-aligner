import AppKit
import SwiftUI

struct AboutView: View {
    private let appVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.7.0"
    private let buildNumber = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
    private let runtime = RuntimeManifestDisplay.load()

    var body: some View {
        VStack(spacing: 14) {
            if let icon = NSApplication.shared.applicationIconImage {
                Image(nsImage: icon)
                    .resizable()
                    .frame(width: 96, height: 96)
                    .accessibilityHidden(true)
            }
            Text("星语歌词对齐器").font(.title.bold())
            Text("版本 \(appVersion)（\(buildNumber)）")
            Text("本地歌词对齐与音轨分离工具")
                .foregroundStyle(.secondary)
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                GridRow { Text("平台"); Text("Apple Silicon · macOS 14+") }
                GridRow { Text("App Runtime"); Text(runtime == nil ? "Development Runtime" : "Bundled Runtime") }
                GridRow { Text("Engine"); Text("xingyu-lyrics-aligner \(runtime?.packageVersion ?? "Development Runtime")") }
                GridRow { Text("Runtime Version"); Text(runtime?.runtimeVersion ?? "Development") }
            }
            .font(.callout)
            Text("此候选构建未使用 Apple Developer ID 签名，也未经过 Apple notarization。")
                .font(.caption)
                .foregroundStyle(.orange)
                .multilineTextAlignment(.center)
            HStack {
                if let licenseURL = URL(string: "https://github.com/wangjiqing/xingyu-lyrics-aligner/blob/main/LICENSE") {
                    Link("项目许可证", destination: licenseURL)
                }
                Button("第三方许可证") { openBundledLicense(named: nil) }
                Button("模型许可证说明") { openBundledLicense(named: "model-licenses.md") }
            }
        }
        .padding(28)
        .frame(width: 520)
    }

    private func openBundledLicense(named name: String?) {
        guard let resources = Bundle.main.resourceURL else { return }
        let licenses = resources.appendingPathComponent("runtime/licenses", isDirectory: true)
        let target = name.map { licenses.appendingPathComponent($0) } ?? licenses
        guard FileManager.default.fileExists(atPath: target.path) else { return }
        NSWorkspace.shared.open(target)
    }
}

private struct RuntimeManifestDisplay: Decodable {
    let runtimeVersion: String
    let packageVersion: String

    static func load() -> Self? {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("runtime/runtime-manifest.json"),
              let data = try? Data(contentsOf: url)
        else { return nil }
        return try? JSONDecoder().decode(Self.self, from: data)
    }
}
