import Foundation

enum ReadinessServiceError: LocalizedError {
    case processFailed(Int32, String)
    case unsupportedSchema(Int)

    var errorDescription: String? {
        switch self {
        case .processFailed(let code, let message): "运行环境检查失败（exit \(code)）：\(message)"
        case .unsupportedSchema(let version): "不支持 readiness schema \(version)。"
        }
    }
}

actor RuntimeReadinessService {
    private let runner = AsyncProcessRunner()

    func check(python: URL, dataRoot: URL) async throws -> DesktopReadinessReport {
        let arguments = [
                "-m", "xingyu_lyrics_aligner.cli", "desktop", "readiness",
                "--data-dir", dataRoot.path, "--json",
        ]
        var environment = ProcessInfo.processInfo.environment
        for (key, value) in ManagedDesktopPaths(root: dataRoot).processEnvironment(runtimeExecutable: python) {
            environment[key] = value
        }
        let result = try await runner.run(executable: python, arguments: arguments, environment: environment)
        let diagnostic = String(decoding: result.stderr, as: UTF8.self)
        guard result.status == 0 else { throw ReadinessServiceError.processFailed(result.status, diagnostic) }
        let report = try JSONDecoder().decode(DesktopReadinessReport.self, from: result.stdout)
        guard report.schemaVersion == 1 else { throw ReadinessServiceError.unsupportedSchema(report.schemaVersion) }
        return report
    }
}
