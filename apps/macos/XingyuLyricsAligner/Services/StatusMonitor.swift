import Foundation

enum StatusMonitorError: LocalizedError, Equatable, Sendable {
    case persistentInvalidStatus(String)
    case wrongJob(expected: String, actual: String)
    case unsupportedSchema(Int)
    case invalidEvent(String)

    var errorDescription: String? {
        switch self {
        case .persistentInvalidStatus(let detail): "无法读取任务状态：\(detail)"
        case .wrongJob(let expected, let actual): "任务状态不匹配（期望 \(expected)，实际 \(actual)）。"
        case .unsupportedSchema(let version): "不支持的任务状态协议版本：\(version)。"
        case .invalidEvent(let detail): "无法读取任务事件：\(detail)"
        }
    }
}

actor StatusMonitor {
    private let decoder = JSONDecoder()

    func monitor(
        workspace: JobWorkspace,
        pollNanoseconds: UInt64 = 600_000_000,
        maximumConsecutiveFailures: Int = 8,
        onError: @escaping @MainActor @Sendable (StatusMonitorError) -> Void = { _ in },
        onUpdate: @escaping @MainActor @Sendable (WorkerStatusSnapshot?, [WorkerEvent]) -> Void
    ) async {
        var eventOffset: UInt64 = 0
        var eventRemainder = Data()
        var statusFailures = 0
        let statusURL = workspace.jobDirectory.appendingPathComponent("status.json")
        let eventsURL = workspace.jobDirectory.appendingPathComponent("events.jsonl")
        while !Task.isCancelled {
            let statusResult = decodeStatus(at: statusURL, expectedJobID: workspace.id)
            let status: WorkerStatusSnapshot?
            switch statusResult {
            case .success(let snapshot):
                status = snapshot
                statusFailures = 0
            case .failure(let error):
                status = nil
                switch error {
                case .persistentInvalidStatus:
                    statusFailures += 1
                    if statusFailures >= maximumConsecutiveFailures {
                        await onError(error)
                        return
                    }
                default:
                    await onError(error)
                    return
                }
            }

            let eventResult = readNewEvents(
                at: eventsURL, offset: &eventOffset, remainder: &eventRemainder
            )
            let events: [WorkerEvent]
            switch eventResult {
            case .success(let values): events = values
            case .failure(let error):
                await onError(error)
                return
            }
            if status != nil || !events.isEmpty { await onUpdate(status, events) }
            if status?.state.isTerminal == true { return }
            try? await Task.sleep(nanoseconds: pollNanoseconds)
        }
    }

    private func decodeStatus(
        at url: URL, expectedJobID: String
    ) -> Result<WorkerStatusSnapshot?, StatusMonitorError> {
        guard FileManager.default.fileExists(atPath: url.path) else { return .success(nil) }
        do {
            let data = try Data(contentsOf: url)
            guard !data.isEmpty else { return .failure(.persistentInvalidStatus("状态文件为空")) }
            let snapshot = try decoder.decode(WorkerStatusSnapshot.self, from: data)
            if let version = snapshot.statusSchemaVersion, version != 1 {
                return .failure(.unsupportedSchema(version))
            }
            if let actual = snapshot.jobId, actual != expectedJobID {
                return .failure(.wrongJob(expected: expectedJobID, actual: actual))
            }
            return .success(snapshot)
        } catch {
            return .failure(.persistentInvalidStatus(error.localizedDescription))
        }
    }

    private func readNewEvents(
        at url: URL, offset: inout UInt64, remainder: inout Data
    ) -> Result<[WorkerEvent], StatusMonitorError> {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attributes[.size] as? NSNumber else { return .success([]) }
        if size.uint64Value < offset {
            offset = 0
            remainder.removeAll(keepingCapacity: true)
        }
        do {
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            try handle.seek(toOffset: offset)
            let fresh = try handle.readToEnd() ?? Data()
            offset += UInt64(fresh.count)
            guard !fresh.isEmpty else { return .success([]) }
            remainder.append(fresh)
            let newline = UInt8(ascii: "\n")
            guard let lastNewline = remainder.lastIndex(of: newline) else { return .success([]) }
            let complete = remainder[...lastNewline]
            remainder = Data(remainder[remainder.index(after: lastNewline)...])
            var events: [WorkerEvent] = []
            for line in complete.split(separator: newline) where !line.isEmpty {
                do { events.append(try decoder.decode(WorkerEvent.self, from: Data(line))) }
                catch { return .failure(.invalidEvent(error.localizedDescription)) }
            }
            return .success(events)
        } catch {
            return .failure(.invalidEvent(error.localizedDescription))
        }
    }
}
