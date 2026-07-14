import Foundation

struct AsyncProcessResult: Sendable {
    let status: Int32
    let reason: Process.TerminationReason
    let stdout: Data
    let stderr: Data
    let stdoutTruncated: Bool
    let stderrTruncated: Bool
}

enum AsyncProcessError: LocalizedError {
    case timedOut

    var errorDescription: String? { "子进程执行超时。" }
}

actor AsyncProcessRunner {
    private let limit: Int

    init(maximumBytes: Int = 2 * 1024 * 1024) { limit = maximumBytes }

    func run(
        executable: URL,
        arguments: [String],
        environment: [String: String],
        timeout: Duration = .seconds(30)
    ) async throws -> AsyncProcessResult {
        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.environment = environment
        process.standardOutput = stdout
        process.standardError = stderr
        let outCapture = BoundedProcessCapture(limit: limit)
        let errCapture = BoundedProcessCapture(limit: limit)
        stdout.fileHandleForReading.readabilityHandler = { outCapture.append($0.availableData) }
        stderr.fileHandleForReading.readabilityHandler = { errCapture.append($0.availableData) }
        try process.run()
        do {
            try await withThrowingTaskGroup(of: Void.self) { group in
                group.addTask {
                    while process.isRunning {
                        try Task.checkCancellation()
                        try await Task.sleep(for: .milliseconds(20))
                    }
                }
                group.addTask {
                    try await Task.sleep(for: timeout)
                    throw AsyncProcessError.timedOut
                }
                _ = try await group.next()
                group.cancelAll()
            }
        } catch {
            if process.isRunning { process.terminate() }
            try? await Task.sleep(for: .milliseconds(300))
            if process.isRunning { process.interrupt() }
            stdout.fileHandleForReading.readabilityHandler = nil
            stderr.fileHandleForReading.readabilityHandler = nil
            throw error
        }
        stdout.fileHandleForReading.readabilityHandler = nil
        stderr.fileHandleForReading.readabilityHandler = nil
        outCapture.append(stdout.fileHandleForReading.availableData)
        errCapture.append(stderr.fileHandleForReading.availableData)
        let outValue = outCapture.value()
        let errValue = errCapture.value()
        return AsyncProcessResult(
            status: process.terminationStatus, reason: process.terminationReason,
            stdout: outValue.0, stderr: errValue.0,
            stdoutTruncated: outValue.1, stderrTruncated: errValue.1
        )
    }

}

private final class BoundedProcessCapture: @unchecked Sendable {
    private let lock = NSLock()
    private let limit: Int
    private var data = Data()
    private var truncated = false

    init(limit: Int) { self.limit = limit }

    func append(_ chunk: Data) {
        guard !chunk.isEmpty else { return }
        lock.lock(); defer { lock.unlock() }
        data.append(chunk)
        if data.count > limit {
            data = Data(data.suffix(limit))
            truncated = true
            while !data.isEmpty && (data[0] & 0xC0) == 0x80 { data.removeFirst() }
        }
    }

    func value() -> (Data, Bool) {
        lock.lock(); defer { lock.unlock() }
        return (data, truncated)
    }
}
