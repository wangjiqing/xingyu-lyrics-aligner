import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var viewModel: DesktopJobViewModel
    @ObservedObject var environment: EnvironmentReadinessViewModel
    @State private var advancedExpanded = false
    @State private var diagnosticsExpanded = false
    @State private var dropTargeted = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                runtimeCard
                audioCard
                lyricsCard
                exportsCard
                destinationCard
                executionCard
            }
            .padding(24)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task { syncReadiness() }
        .onChange(of: environment.state) { _, _ in syncReadiness() }
        .onChange(of: viewModel.exports) { _, _ in syncReadiness() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("星语歌词对齐器").font(.largeTitle.bold())
            Text("本地完成可信歌词对齐与音轨导出").foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Text(environment.report?.runtime.developmentRuntime == false ? "Bundled Runtime" : "Development Runtime")
                    .foregroundStyle(environment.report?.runtime.developmentRuntime == false ? .green : .orange)
                Text("Unsigned · 未经 Apple 公证")
                    .foregroundStyle(.orange)
            }
            .font(.caption.bold())
        }
    }

    private var runtimeCard: some View {
        GroupBox("运行环境") {
            VStack(alignment: .leading, spacing: 8) {
                if environment.state == .checking {
                    HStack { ProgressView().controlSize(.small); Text("正在检查运行环境……") }
                }
                readinessLine(
                    "Python 运行环境",
                    ready: environment.report?.runtime.python.available == true,
                    detail: environment.report?.runtime.python.version ?? viewModel.runtimePath
                )
                readinessLine(
                    environment.report?.runtime.developmentRuntime == false ? "FFmpeg（App 内嵌）" : "FFmpeg（开发环境提供）",
                    ready: environment.report?.runtime.ffmpeg.available == true,
                    detail: environment.report?.runtime.ffmpeg.path
                )
                readinessLine(
                    environment.report?.runtime.developmentRuntime == false ? "FFprobe（App 内嵌）" : "FFprobe（开发环境提供）",
                    ready: environment.report?.runtime.ffprobe.available == true,
                    detail: environment.report?.runtime.ffprobe.path
                )
                if let model = environment.report?.alignmentModel {
                    modelReadiness(model, installTitle: "安装必要模型")
                }
                if let model = environment.report?.separationModel {
                    modelReadiness(model, installTitle: "安装人声分离模型")
                }
                if let event = environment.installEvent {
                    installProgress(event)
                }
                if let error = environment.errorMessage {
                    Text(error).foregroundStyle(.red).font(.caption).textSelection(.enabled)
                }
                HStack {
                    Button("重新检查") { Task { await environment.check() } }
                        .disabled(environment.installInProgress || viewModel.state.isRunning)
                    if environment.installInProgress {
                        Button("取消安装", role: .destructive) { environment.cancelInstall() }
                    }
                }
            }
        }
    }

    private var audioCard: some View {
        GroupBox("1. 选择音频") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button("选择音频…", action: chooseAudio)
                    if let audio = viewModel.selectedAudio {
                        VStack(alignment: .leading) {
                            Text(audio.lastPathComponent).fontWeight(.medium)
                            Text(audio.path).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            Text(audioDescription(audio)).font(.caption2).foregroundStyle(.tertiary)
                        }
                    } else {
                        Text("支持 MP3、M4A、WAV、FLAC；也可拖放单个文件")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(12)
                .background(dropTargeted ? Color.accentColor.opacity(0.15) : Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted, perform: handleDrop)
            }
        }
        .disabled(viewModel.state.isRunning || environment.installInProgress)
    }

    private var lyricsCard: some View {
        GroupBox("2. 可信歌词") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Button("导入 TXT/LRC…", action: chooseLyrics)
                    Button("清空") { viewModel.lyrics = "" }
                    Spacer()
                    Text("\(viewModel.lyricsLineCount) 行 · \(viewModel.lyricsCharacterCount) 字")
                        .font(.caption).foregroundStyle(.secondary)
                }
                TextEditor(text: $viewModel.lyrics)
                    .font(.body.monospaced())
                    .frame(minHeight: 180)
                    .border(Color(nsColor: .separatorColor))
                Text("请粘贴或导入已经确认可信的歌词。LRC 导入会去除标准时间标签和纯元数据标签。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .disabled(viewModel.state.isRunning || environment.installInProgress)
    }

    private var exportsCard: some View {
        GroupBox("3. 导出项目") {
            VStack(alignment: .leading, spacing: 8) {
                Toggle("行级歌词 LRC", isOn: $viewModel.exports.lrc)
                Toggle("字级歌词 SWLRC", isOn: $viewModel.exports.swlrc)
                Divider()
                Toggle("人声 vocals.wav", isOn: $viewModel.exports.vocals)
                Toggle("伴奏 accompaniment.wav", isOn: $viewModel.exports.accompaniment)
                if (viewModel.exports.vocals || viewModel.exports.accompaniment)
                    && !environment.separationReady
                {
                    Text("人声分离模型或 Demucs 运行包尚未就绪，请先在运行环境区域安装或修复。")
                        .font(.caption).foregroundStyle(.orange)
                }
                DisclosureGroup("高级产物", isExpanded: $advancedExpanded) {
                    Toggle("对齐详细数据 alignment.json", isOn: $viewModel.exports.alignmentJSON)
                    Toggle("质量报告 report.json", isOn: $viewModel.exports.reportJSON)
                }
                if !viewModel.exports.isValid {
                    Text("必须至少启用 LRC 或 SWLRC。").foregroundStyle(.red).font(.caption)
                }
            }
            .disabled(viewModel.state.isRunning)
        }
    }

    private var destinationCard: some View {
        GroupBox("4. 导出目录") {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(viewModel.exportDirectory.path).lineLimit(1).textSelection(.enabled)
                    Spacer()
                    Button("选择目录…", action: chooseDestination)
                }
                Text("会创建以音频名命名的子目录；其中同名的标准产物会被本次结果覆盖。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .disabled(viewModel.state.isRunning || environment.installInProgress)
    }

    private var executionCard: some View {
        GroupBox("5. 执行") {
            VStack(alignment: .leading, spacing: 10) {
                if viewModel.state.isRunning {
                    HStack {
                        ProgressView().controlSize(.small)
                        Text(viewModel.state == .cancellationRequested ? "正在请求取消……" : viewModel.stageDescription)
                        Spacer()
                        Text(elapsedText).monospacedDigit()
                    }
                    if let attempt = viewModel.status?.attempt?.number {
                        Text("Attempt \(attempt)").font(.caption).foregroundStyle(.secondary)
                    }
                    Button("请求取消", role: .destructive) { viewModel.requestCancellation() }
                        .disabled(viewModel.state == .cancellationRequested)
                } else {
                    resultSummary
                    HStack {
                        Button("开始处理") { viewModel.start() }
                            .buttonStyle(.borderedProminent)
                            .disabled(!viewModel.canStart)
                        if !viewModel.exportedFiles.isEmpty {
                            Button("在 Finder 中打开") { viewModel.openExportDirectory() }
                        }
                        if viewModel.state != .idle {
                            Button("处理下一首") { viewModel.resetForNextSong() }
                        }
                    }
                }

                if let error = viewModel.userError {
                    Text(error).foregroundStyle(.red).textSelection(.enabled)
                    if let action = viewModel.status?.error?.suggestedAction {
                        Text(action).font(.caption).foregroundStyle(.secondary)
                    }
                }
                warnings
                DisclosureGroup("事件与诊断", isExpanded: $diagnosticsExpanded) {
                    DiagnosticView(
                        service: viewModel.processService,
                        events: viewModel.events,
                        taskDiagnostic: viewModel.taskDiagnostic
                    )
                }
            }
        }
    }

    @ViewBuilder private var resultSummary: some View {
        switch viewModel.state {
        case .succeeded: Label("处理成功", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        case .needsReview: Label("处理完成，但结果建议人工检查", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
        case .failed: Label("处理失败", systemImage: "xmark.circle.fill").foregroundStyle(.red)
        case .cancelled: Label("任务已取消", systemImage: "stop.circle.fill")
        case .abandoned: Label("任务异常中断", systemImage: "bolt.trianglebadge.exclamationmark.fill").foregroundStyle(.red)
        default: Text("准备就绪").foregroundStyle(.secondary)
        }
        if !viewModel.exportedFiles.isEmpty {
            ForEach(viewModel.exportedFiles, id: \.path) { Text("• \($0.lastPathComponent)").font(.caption) }
        }
    }

    @ViewBuilder private var warnings: some View {
        let warnings = viewModel.status?.warnings ?? []
        if !warnings.isEmpty {
            VStack(alignment: .leading) {
                Text("警告").font(.headline)
                ForEach(warnings, id: \.self) { Text("• \($0)").font(.caption).foregroundStyle(.orange) }
            }
        }
    }

    private var elapsedText: String {
        String(format: "%02d:%02d", viewModel.elapsedSeconds / 60, viewModel.elapsedSeconds % 60)
    }

    private func chooseAudio() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.mp3, .mpeg4Audio, .wav, .audio]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url { viewModel.selectAudio(url) }
    }

    private func chooseLyrics() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.plainText, UTType(filenameExtension: "lrc") ?? .data]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url { viewModel.importLyrics(from: url) }
    }

    private func chooseDestination() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        if panel.runModal() == .OK, let url = panel.url { viewModel.exportDirectory = url }
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        guard providers.count == 1, let provider = providers.first else { return false }
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
            let url: URL?
            if let data = item as? Data { url = URL(dataRepresentation: data, relativeTo: nil) }
            else { url = item as? URL }
            if let url { Task { @MainActor in viewModel.selectAudio(url) } }
        }
        return true
    }

    private func audioDescription(_ url: URL) -> String {
        let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentTypeKey])
        let size = values?.fileSize.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? "未知大小"
        return "\(url.pathExtension.uppercased()) · \(size)"
    }

    private func syncReadiness() {
        viewModel.runtimeReadinessAllowsTask = environment.canRun(exports: viewModel.exports)
    }

    private func readinessLine(_ title: String, ready: Bool, detail: String?) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Image(systemName: ready ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(ready ? .green : .secondary)
            Text(title)
            Spacer()
            if let detail { Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
        }
    }

    @ViewBuilder private func modelReadiness(
        _ model: ModelReadiness,
        installTitle: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            readinessLine(
                model.displayName,
                ready: model.state == .installed && model.problems.isEmpty,
                detail: model.state.rawValue
            )
            Text("用途：\(model.category == "ALIGNMENT" ? "生成 LRC / SWLRC" : "导出人声与伴奏")")
                .font(.caption).foregroundStyle(.secondary)
            Text("预计下载：\(ByteCountFormatter.string(fromByteCount: model.estimatedDownloadBytes, countStyle: .file)) · \(model.license.name)")
                .font(.caption).foregroundStyle(.secondary)
            if model.state != .installed {
                Button(installTitle) { environment.install(modelID: model.id) }
                    .disabled(environment.installInProgress || viewModel.state.isRunning)
            }
            if !model.problems.isEmpty {
                Text(model.problems.map(problemDescription).joined(separator: "，"))
                    .font(.caption2).foregroundStyle(.orange)
            }
        }
        .padding(.vertical, 3)
    }

    @ViewBuilder private func installProgress(_ event: ModelInstallEvent) -> some View {
        VStack(alignment: .leading) {
            Text(installEventText(event)).font(.caption.bold())
            if let downloaded = event.downloadedBytes {
                if let total = event.totalBytes, total > 0 {
                    ProgressView(value: Double(downloaded), total: Double(total))
                    Text("\(byteText(downloaded)) / \(byteText(total))").font(.caption.monospacedDigit())
                } else {
                    ProgressView()
                    Text("已下载 \(byteText(downloaded))").font(.caption.monospacedDigit())
                }
            }
        }
    }

    private func installEventText(_ event: ModelInstallEvent) -> String {
        switch event.eventType {
        case .installStarted: "正在准备模型安装"
        case .downloadProgress: "正在下载模型"
        case .verifying: "正在校验模型"
        case .installing: "正在安装模型"
        case .installSucceeded: "模型安装成功"
        case .installFailed: "模型安装失败"
        case .installCancelled: "模型安装已取消"
        case .unknown(let value): "模型安装事件：\(value)"
        }
    }

    private func byteText(_ value: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }

    private func problemDescription(_ problem: String) -> String {
        switch problem {
        case "demucs_package_missing": "模型权重已安装，但 Development Runtime 缺少 Demucs Python 包"
        case "whisperx_package_missing": "模型已安装，但 Development Runtime 缺少 WhisperX Python 包"
        case "revision_mismatch": "已安装模型 revision 与 manifest 不匹配"
        case "install_state_missing": "模型安装状态文件缺失"
        case "install_state_invalid": "模型安装状态文件损坏"
        default: problem
        }
    }
}

private struct DiagnosticView: View {
    @ObservedObject var service: WorkerProcessService
    let events: [WorkerEvent]
    let taskDiagnostic: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let pid = service.pid { Text("PID: \(pid)").font(.caption) }
            ForEach(events.suffix(30)) { event in
                Text("[\(event.type)] \(event.message)").font(.caption.monospaced())
            }
            if !service.diagnosticLog.isEmpty {
                Divider()
                Text(service.diagnosticLog).font(.caption.monospaced()).textSelection(.enabled)
            }
            if !taskDiagnostic.isEmpty {
                Divider()
                Text(taskDiagnostic).font(.caption.monospaced()).textSelection(.enabled)
            }
        }
    }
}
