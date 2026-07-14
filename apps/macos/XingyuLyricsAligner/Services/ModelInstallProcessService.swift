import Foundation

@MainActor
final class ModelInstallProcessService: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var diagnosticLog = ""
    private var process: Process?
    private var pending = Data()
    private var diagnosticPending = Data()

    func start(
        python: URL,
        modelID: String,
        dataRoot: URL,
        onEvent: @escaping @MainActor @Sendable (ModelInstallEvent) -> Void,
        onExit: @escaping @MainActor @Sendable (Int32) -> Void
    ) throws {
        guard process == nil else { return }
        pending = Data()
        diagnosticLog = ""
        diagnosticPending = Data()
        let task = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        task.executableURL = python
        task.arguments = [
            "-m", "xingyu_lyrics_aligner.cli", "models", "install", modelID,
            "--data-dir", dataRoot.path, "--json-events",
        ]
        task.standardOutput = stdout
        task.standardError = stderr
        var environment = ProcessInfo.processInfo.environment
        for (key, value) in ManagedDesktopPaths(root: dataRoot)
            .processEnvironment(runtimeExecutable: python)
        {
            environment[key] = value
        }
        task.environment = environment
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor [weak self] in self?.consume(data, onEvent: onEvent) }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.diagnosticPending.append(data)
                var suffix = 0
                while suffix <= min(3, self.diagnosticPending.count),
                      String(data: Data(self.diagnosticPending.dropLast(suffix)), encoding: .utf8) == nil {
                    suffix += 1
                }
                guard suffix <= min(3, self.diagnosticPending.count),
                      let decoded = String(data: Data(self.diagnosticPending.dropLast(suffix)), encoding: .utf8)
                else { return }
                self.diagnosticPending = suffix == 0 ? Data() : Data(self.diagnosticPending.suffix(suffix))
                self.diagnosticLog += decoded
                if self.diagnosticLog.utf8.count > 64 * 1024 {
                    self.diagnosticLog = String(self.diagnosticLog.suffix(32 * 1024))
                }
            }
        }
        task.terminationHandler = { [weak self] process in
            stdout.fileHandleForReading.readabilityHandler = nil
            stderr.fileHandleForReading.readabilityHandler = nil
            Task { @MainActor [weak self] in
                self?.process = nil
                self?.isRunning = false
                onExit(process.terminationStatus)
            }
        }
        try task.run()
        process = task
        isRunning = true
    }

    func cancel() {
        process?.interrupt()
    }

    func terminateForAppExit() {
        process?.terminate()
    }

    private func consume(
        _ data: Data,
        onEvent: @escaping @MainActor @Sendable (ModelInstallEvent) -> Void
    ) {
        pending.append(data)
        let newline = UInt8(ascii: "\n")
        while let index = pending.firstIndex(of: newline) {
            let line = pending[..<index]
            pending.removeSubrange(...index)
            if let event = try? JSONDecoder().decode(ModelInstallEvent.self, from: Data(line)) {
                onEvent(event)
            }
        }
    }
}
