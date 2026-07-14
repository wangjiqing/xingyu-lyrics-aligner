import AppKit
import Combine
import Foundation

@MainActor
final class DesktopJobViewModel: ObservableObject {
    @Published var selectedAudio: URL?
    @Published var lyrics = ""
    @Published var exports = DesktopExports()
    @Published var exportDirectory: URL
    @Published var runtimeReadinessAllowsTask = false
    @Published private(set) var state: DesktopJobUIState = .idle
    @Published private(set) var status: WorkerStatusSnapshot?
    @Published private(set) var events: [WorkerEvent] = []
    @Published private(set) var exportedFiles: [URL] = []
    @Published private(set) var runtimePath = "正在定位……"
    @Published private(set) var userError: String?
    @Published private(set) var taskDiagnostic = ""
    @Published private(set) var startedAt: Date?
    @Published private(set) var elapsedSeconds = 0

    let processService = WorkerProcessService()
    private let workspaceService = JobWorkspaceService()
    private let statusMonitor = StatusMonitor()
    private let artifactService = ArtifactExportService()
    private var runtimeURL: URL?
    private var workspace: JobWorkspace?
    private var monitorTask: Task<Void, Never>?
    private var workspaceTask: Task<Void, Never>?
    private var exportTask: Task<Void, Never>?
    private var shutdownTask: Task<Void, Never>?
    private var elapsedTask: Task<Void, Never>?
    private var activeJobID: String?
    private var activeGeneration = UUID()

    init() {
        exportDirectory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Music/Xingyu Lyrics Aligner", isDirectory: true)
        resolveRuntime()
    }

    var lyricsLineCount: Int { lyrics.split(whereSeparator: \.isNewline).count }
    var lyricsCharacterCount: Int { lyrics.trimmingCharacters(in: .whitespacesAndNewlines).count }
    var canStart: Bool {
        selectedAudio != nil && lyricsCharacterCount > 0 && exports.isValid && runtimeURL != nil
            && runtimeReadinessAllowsTask && !state.isRunning
    }
    var stageDescription: String {
        guard let stage = status?.stage else { return state == .preparing ? "正在准备任务" : "等待开始" }
        return Self.localizedStage(stage)
    }

    func selectAudio(_ url: URL) {
        guard Self.supportedAudioExtensions.contains(url.pathExtension.lowercased()) else {
            userError = "请选择 MP3、M4A、WAV 或 FLAC 音频文件。"
            return
        }
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &directory), !directory.boolValue else {
            userError = "音频路径不是普通文件。"
            return
        }
        selectedAudio = url
        exportedFiles = []
        userError = nil
        taskDiagnostic = ""
    }

    func importLyrics(from url: URL) {
        do {
            let text = try String(contentsOf: url, encoding: .utf8)
            lyrics = LyricsImportService.normalizedLyrics(from: text, fileExtension: url.pathExtension)
            userError = nil
        } catch {
            userError = "无法读取歌词文件：\(error.localizedDescription)"
        }
    }

    func start() {
        guard let audio = selectedAudio, let runtimeURL else { return }
        let normalized = lyrics.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, exports.isValid else {
            userError = "请输入至少一行可信歌词，并启用 LRC 或 SWLRC。"
            return
        }
        state = .preparing
        status = nil
        events = []
        exportedFiles = []
        userError = nil
        taskDiagnostic = ""
        cancelAsyncWork()
        startedAt = Date()
        startElapsedClock()
        let generation = UUID()
        activeGeneration = generation
        workspaceTask = Task { [weak self] in
            guard let self else { return }
            do {
                let workspace = try await self.workspaceService.create(audio: audio, lyrics: normalized, exports: self.exports)
                guard !Task.isCancelled, self.activeGeneration == generation else {
                    await self.workspaceService.removeIncomplete(workspace)
                    return
                }
                self.workspace = workspace
                self.activeJobID = workspace.id
                self.state = .running
                self.startMonitor(workspace: workspace, audio: audio, generation: generation)
                let jobsRoot = workspace.jobDirectory.deletingLastPathComponent()
                let musicRoot = workspace.musicDirectory.deletingLastPathComponent()
                try self.processService.start(
                    python: runtimeURL,
                    jobsDirectory: jobsRoot,
                    musicDirectory: musicRoot
                ) { [weak self] code in
                    self?.workerExited(code: code, jobID: workspace.id, generation: generation)
                }
            } catch is CancellationError {
                guard self.activeGeneration == generation else { return }
                self.state = .idle
                self.finishClock()
            } catch {
                guard self.activeGeneration == generation else { return }
                self.fail("无法启动任务：\(error.localizedDescription)")
            }
        }
    }

    func requestCancellation() {
        if state == .preparing {
            workspaceTask?.cancel()
            activeGeneration = UUID()
            state = .cancelled
            finishClock()
            return
        }
        guard state == .running, let workspace else { return }
        state = .cancellationRequested
        Task { [weak self] in
            do { try await self?.workspaceService.requestCancellation(for: workspace) }
            catch { self?.userError = "无法写入取消请求：\(error.localizedDescription)" }
        }
    }

    func openExportDirectory() {
        let target = exportedFiles.first?.deletingLastPathComponent() ?? exportDirectory
        NSWorkspace.shared.open(target)
    }

    func resetForNextSong() {
        cancelAsyncWork()
        activeGeneration = UUID()
        activeJobID = nil
        workspace = nil
        selectedAudio = nil
        lyrics = ""
        status = nil
        events = []
        exportedFiles = []
        userError = nil
        startedAt = nil
        elapsedSeconds = 0
        state = .idle
    }

    func shutdown() {
        cancelAsyncWork()
        activeGeneration = UUID()
        if let workspace { Task { try? await workspaceService.requestCancellation(for: workspace) } }
        if processService.isRunning {
            shutdownTask = Task { await processService.shutdown() }
        }
    }

    private func resolveRuntime() {
        do {
            let runtime = try RuntimeLocator().locate()
            runtimeURL = runtime.python
            runtimePath = runtime.python.path
        } catch {
            runtimePath = "不可用"
            userError = error.localizedDescription
        }
    }

    private func startMonitor(workspace: JobWorkspace, audio: URL, generation: UUID) {
        monitorTask?.cancel()
        monitorTask = Task { [weak self] in
            await self?.statusMonitor.monitor(workspace: workspace) { [weak self] error in
                guard let self, self.activeJobID == workspace.id, self.activeGeneration == generation else { return }
                self.fail(error.localizedDescription)
            } onUpdate: { [weak self] snapshot, newEvents in
                guard let self, self.activeJobID == workspace.id, self.activeGeneration == generation else { return }
                self.events.append(contentsOf: newEvents)
                if let snapshot { self.apply(snapshot, workspace: workspace, audio: audio) }
            }
        }
    }

    private func apply(_ snapshot: WorkerStatusSnapshot, workspace: JobWorkspace, audio: URL) {
        status = snapshot
        switch snapshot.state {
        case .queued, .running:
            if state != .cancellationRequested { state = .running }
        case .succeeded:
            complete(.succeeded, snapshot: snapshot, workspace: workspace, audio: audio)
        case .needsReview:
            complete(.needsReview, snapshot: snapshot, workspace: workspace, audio: audio)
        case .failed:
            state = .failed
            finishClock()
            userError = snapshot.error?.message ?? snapshot.errorMessage ?? "Worker 处理失败。"
            loadTaskDiagnostic(snapshot: snapshot, workspace: workspace)
        case .cancelled:
            state = .cancelled
            finishClock()
        case .abandoned:
            state = .abandoned
            finishClock()
            userError = "任务异常中断，请查看诊断日志。"
        case .unknown(let value):
            userError = "Worker 返回未知状态：\(value)"
        }
    }

    private func complete(
        _ finalState: DesktopJobUIState,
        snapshot: WorkerStatusSnapshot,
        workspace: JobWorkspace,
        audio: URL
    ) {
        state = finalState
        finishClock()
        guard let result = snapshot.result else {
            userError = "终态缺少 result。"
            return
        }
        let selection = exports
        let destination = exportDirectory
        let generation = activeGeneration
        exportTask?.cancel()
        exportTask = Task { [weak self] in
            do {
                let files = try await self?.artifactService.export(
                    result: result,
                    workspace: workspace,
                    selection: selection,
                    destinationRoot: destination,
                    songName: audio.deletingPathExtension().lastPathComponent
                ) ?? []
                guard let self, !Task.isCancelled, self.activeGeneration == generation,
                      self.activeJobID == workspace.id else { return }
                self.exportedFiles = files
            } catch {
                guard let self, !Task.isCancelled, self.activeGeneration == generation else { return }
                self.userError = "产物导出失败：\(error.localizedDescription)"
            }
        }
    }

    private func workerExited(code: Int32, jobID: String, generation: UUID) {
        guard activeJobID == jobID, activeGeneration == generation, !state.isTerminal else { return }
        if code != 0 { fail("Worker 异常退出（exit \(code)），且未形成终态。") }
        else {
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(2))
                guard let self, self.activeJobID == jobID, self.activeGeneration == generation,
                      self.state.isRunning else { return }
                self.fail("Worker 已退出，但 status.json 尚未形成终态。")
            }
        }
    }

    private func fail(_ message: String) {
        state = .failed
        userError = message
        finishClock()
    }

    private func startElapsedClock() {
        elapsedTask?.cancel()
        elapsedSeconds = 0
        elapsedTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self, self.state.isRunning else { return }
                self.elapsedSeconds += 1
            }
        }
    }

    private func finishClock() { elapsedTask?.cancel() }

    private func loadTaskDiagnostic(snapshot: WorkerStatusSnapshot, workspace: JobWorkspace) {
        guard let relative = snapshot.error?.attemptStderrPath ?? snapshot.error?.stderrPath,
              !relative.hasPrefix("/"), !relative.split(separator: "/").contains("..")
        else { return }
        let unresolved = workspace.jobDirectory.appendingPathComponent(relative).standardizedFileURL
        guard let unresolvedValues = try? unresolved.resourceValues(forKeys: [.isSymbolicLinkKey]),
              unresolvedValues.isSymbolicLink != true else { return }
        let root = workspace.jobDirectory.standardizedFileURL.resolvingSymlinksInPath()
        let url = unresolved.resolvingSymlinksInPath()
        guard url.path.hasPrefix(root.path + "/"),
              let values = try? url.resourceValues(forKeys: [.isRegularFileKey]),
              values.isRegularFile == true else { return }
        let generation = activeGeneration
        Task { [weak self] in
            let text = await Task.detached(priority: .utility) {
                (try? String(contentsOf: url, encoding: .utf8)) ?? ""
            }.value
            guard let self, self.activeGeneration == generation else { return }
            self.taskDiagnostic = String(text.suffix(24_000))
        }
    }

    private func cancelAsyncWork() {
        workspaceTask?.cancel()
        monitorTask?.cancel()
        exportTask?.cancel()
        shutdownTask?.cancel()
        elapsedTask?.cancel()
    }

    static let supportedAudioExtensions = Set(["mp3", "m4a", "wav", "flac"])
    static func localizedStage(_ value: String) -> String {
        [
            "VALIDATING_REQUEST": "正在校验任务",
            "PREPARING_AUDIO": "正在准备音频",
            "SEPARATING_VOCALS": "正在分离人声与伴奏",
            "LOADING_ALIGNMENT_MODEL": "正在加载对齐模型",
            "ALIGNING": "正在执行歌词对齐",
            "EXPORTING_OUTPUTS": "正在生成结果文件",
            "QUALITY_CHECKING": "正在检查对齐质量",
            "FINALIZING": "正在整理任务结果",
        ][value] ?? "正在处理（\(value)）"
    }
}

private extension DesktopJobUIState {
    var isTerminal: Bool {
        [.succeeded, .needsReview, .failed, .cancelled, .abandoned].contains(self)
    }
}
