import Foundation

enum WorkspaceError: LocalizedError {
    case invalidExports
    case sourceMissing

    var errorDescription: String? {
        switch self {
        case .invalidExports: "必须至少导出 LRC 或 SWLRC。"
        case .sourceMissing: "选择的音频文件不存在或不是普通文件。"
        }
    }
}

actor JobWorkspaceService {
    let rootDirectory: URL
    private let fileManager = FileManager.default

    init(rootDirectory: URL? = nil) {
        if let rootDirectory {
            self.rootDirectory = rootDirectory
        } else {
            let applicationSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            self.rootDirectory = applicationSupport
                .appendingPathComponent("XingyuLyricsAligner", isDirectory: true)
                .appendingPathComponent("Development", isDirectory: true)
        }
    }

    func create(audio source: URL, lyrics: String, exports: DesktopExports) throws -> JobWorkspace {
        guard exports.isValid else { throw WorkspaceError.invalidExports }
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: source.path, isDirectory: &isDirectory), !isDirectory.boolValue else {
            throw WorkspaceError.sourceMissing
        }

        let jobID = "desktop-\(UUID().uuidString.lowercased())"
        let jobsRoot = rootDirectory.appendingPathComponent("Jobs", isDirectory: true)
        let musicRoot = rootDirectory.appendingPathComponent("Music", isDirectory: true)
        let jobDirectory = jobsRoot.appendingPathComponent(jobID, isDirectory: true)
        let musicDirectory = musicRoot.appendingPathComponent(jobID, isDirectory: true)
        let resultDirectory = jobDirectory.appendingPathComponent("result", isDirectory: true)
        do {
            try Task.checkCancellation()
            try fileManager.createDirectory(at: jobDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: musicDirectory, withIntermediateDirectories: true)
            try fileManager.createDirectory(at: resultDirectory, withIntermediateDirectories: true)

            let ext = source.pathExtension.isEmpty ? "audio" : source.pathExtension
            let copiedAudio = musicDirectory.appendingPathComponent("source.\(ext)")
            try fileManager.copyItem(at: source, to: copiedAudio)
            try Task.checkCancellation()
            let lyricsURL = jobDirectory.appendingPathComponent("trusted-lyrics.txt")
            try lyrics.write(to: lyricsURL, atomically: true, encoding: .utf8)

            let request = DesktopWorkerRequest(
            schemaVersion: 3,
            taskType: "DESKTOP_LYRIC_PROCESSING",
            jobId: jobID,
            audioPath: copiedAudio.path,
            trustedLyricsPath: lyricsURL.path,
            outputDir: resultDirectory.path,
            language: "zh",
            device: "cpu",
            exports: exports
        )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let requestData = try encoder.encode(request)
            let requestURL = jobDirectory.appendingPathComponent("request.json")
            try requestData.write(to: requestURL, options: .atomic)
            try Task.checkCancellation()
            // READY is deliberately the final filesystem mutation of task creation.
            try Data().write(to: jobDirectory.appendingPathComponent("READY"), options: .atomic)
            return JobWorkspace(
            id: jobID,
            jobDirectory: jobDirectory,
            musicDirectory: musicDirectory,
            resultDirectory: resultDirectory,
            requestURL: requestURL,
            audioURL: copiedAudio
            )
        } catch {
            try? fileManager.removeItem(at: jobDirectory)
            try? fileManager.removeItem(at: musicDirectory)
            throw error
        }
    }

    func removeIncomplete(_ workspace: JobWorkspace) {
        let ready = workspace.jobDirectory.appendingPathComponent("READY")
        guard !fileManager.fileExists(atPath: ready.path) else { return }
        try? fileManager.removeItem(at: workspace.jobDirectory)
        try? fileManager.removeItem(at: workspace.musicDirectory)
    }

    func requestCancellation(for workspace: JobWorkspace) throws {
        try Data().write(
            to: workspace.jobDirectory.appendingPathComponent("CANCEL_REQUESTED"),
            options: .atomic
        )
    }
}
