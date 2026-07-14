import Foundation
import Darwin

@MainActor
final class WorkerProcessService: ObservableObject {
    @Published private(set) var pid: Int32?
    @Published private(set) var diagnosticLog = ""
    private var process: Process?
    private let maximumLogCharacters = 24_000
    private var stdoutPending = Data()
    private var stderrPending = Data()

    var isRunning: Bool { process?.isRunning == true }

    func start(
        python: URL,
        jobsDirectory: URL,
        musicDirectory: URL,
        developmentArgumentsOverride: [String]? = nil,
        onExit: @escaping @MainActor @Sendable (Int32) -> Void
    ) throws {
        guard process == nil else { return }
        let task = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        task.executableURL = python
        task.arguments = developmentArgumentsOverride ?? [
            "-m", "xingyu_lyrics_aligner.cli", "worker", "run", "--once",
            "--jobs-dir", jobsDirectory.path,
            "--music-dir", musicDirectory.path,
            "--device", "cpu",
        ]
        task.standardOutput = stdout
        task.standardError = stderr
        task.currentDirectoryURL = jobsDirectory.deletingLastPathComponent()
        var environment = ProcessInfo.processInfo.environment
        for (key, value) in ManagedDesktopPaths().processEnvironment(runtimeExecutable: python) {
            environment[key] = value
        }
        task.environment = environment

        let consume: @Sendable (FileHandle, Bool) -> Void = { [weak self] handle, isError in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor [weak self] in self?.consumeDiagnostic(data, isError: isError) }
        }
        stdout.fileHandleForReading.readabilityHandler = { consume($0, false) }
        stderr.fileHandleForReading.readabilityHandler = { consume($0, true) }
        task.terminationHandler = { [weak self] terminated in
            stdout.fileHandleForReading.readabilityHandler = nil
            stderr.fileHandleForReading.readabilityHandler = nil
            Task { @MainActor [weak self] in
                self?.pid = nil
                self?.process = nil
                onExit(terminated.terminationStatus)
            }
        }
        try task.run()
        if setpgid(task.processIdentifier, task.processIdentifier) != 0 {
            let failure = errno
            let alreadyExited = failure == ESRCH && !task.isRunning
            let alreadyGrouped = getpgid(task.processIdentifier) == task.processIdentifier
            if !alreadyExited && !alreadyGrouped {
                task.terminate()
                throw NSError(
                    domain: "XingyuLyricsAligner.ProcessGroup", code: Int(failure),
                    userInfo: [NSLocalizedDescriptionKey: "无法建立受控 Worker 进程组。"]
                )
            }
        }
        process = task
        pid = task.processIdentifier
    }

    func forceTerminate() {
        guard let process else { return }
        let group = -process.processIdentifier
        if kill(group, SIGTERM) != 0, errno == ESRCH { return }
    }

    func forceKill() {
        guard let process else { return }
        _ = kill(-process.processIdentifier, SIGKILL)
    }

    func shutdown(graceNanoseconds: UInt64 = 2_000_000_000) async {
        forceTerminate()
        try? await Task.sleep(nanoseconds: graceNanoseconds)
        if isRunning { forceKill() }
    }

    private func appendDiagnostic(_ text: String) {
        diagnosticLog.append(text)
        if diagnosticLog.count > maximumLogCharacters {
            diagnosticLog = String(diagnosticLog.suffix(maximumLogCharacters))
        }
    }

    private func consumeDiagnostic(_ data: Data, isError: Bool) {
        if isError { stderrPending.append(data) } else { stdoutPending.append(data) }
        var pending = isError ? stderrPending : stdoutPending
        var suffixCount = 0
        while suffixCount <= min(3, pending.count),
              String(data: Data(pending.dropLast(suffixCount)), encoding: .utf8) == nil {
            suffixCount += 1
        }
        guard suffixCount <= min(3, pending.count),
              let text = String(data: Data(pending.dropLast(suffixCount)), encoding: .utf8) else { return }
        pending = suffixCount == 0 ? Data() : Data(pending.suffix(suffixCount))
        if isError { stderrPending = pending } else { stdoutPending = pending }
        appendDiagnostic(text)
    }
}
