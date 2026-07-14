import Foundation

enum RuntimeMode: String, Codable, Sendable { case development = "DEVELOPMENT", bundled = "BUNDLED" }

struct RuntimeLocation: Equatable, Sendable {
    let python: URL
    let mode: RuntimeMode
    let runtimeRoot: URL?
}

enum RuntimeLocatorError: LocalizedError {
    case configuredRuntimeMissing(String)
    case bundledRuntimeMissing(String)
    case repositoryRuntimeMissing

    var errorDescription: String? {
        switch self {
        case .configuredRuntimeMissing(let path): "XINGYU_ALIGNER_PYTHON 指向的文件不可执行：\(path)"
        case .bundledRuntimeMissing(let path): "App 内嵌 Runtime 缺失或不可执行：\(path)"
        case .repositoryRuntimeMissing: "未找到可用 Python Runtime，且不会回退到系统 Python。"
        }
    }
}

struct RuntimeLocator {
    var environment: [String: String] = ProcessInfo.processInfo.environment
    var currentDirectory: URL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    var bundleResources: URL? = Bundle.main.resourceURL

    func locate() throws -> RuntimeLocation {
        let forcedBundled = environment["XINGYU_RUNTIME_MODE"] == RuntimeMode.bundled.rawValue
        if forcedBundled {
            if let bundled = bundledRuntime() { return bundled }
            throw RuntimeLocatorError.bundledRuntimeMissing(bundledPython.path)
        }
#if DEBUG
        if let configured = try configuredRuntime() { return configured }
        if let repository = repositoryRuntime() { return repository }
        if let bundled = bundledRuntime() { return bundled }
#else
        if let bundled = bundledRuntime() { return bundled }
        if let configured = try configuredRuntime() { return configured }
#endif
        throw RuntimeLocatorError.repositoryRuntimeMissing
    }

    private var bundledPython: URL {
        (bundleResources ?? URL(fileURLWithPath: "/missing-resources"))
            .appendingPathComponent("runtime/bin/python3")
    }

    private func bundledRuntime() -> RuntimeLocation? {
        let python = bundledPython.standardizedFileURL
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return nil }
        return RuntimeLocation(
            python: python,
            mode: .bundled,
            runtimeRoot: python.deletingLastPathComponent().deletingLastPathComponent()
        )
    }

    private func configuredRuntime() throws -> RuntimeLocation? {
        guard let configured = environment["XINGYU_ALIGNER_PYTHON"], !configured.isEmpty else {
            return nil
        }
        let url = URL(fileURLWithPath: configured).standardizedFileURL
        guard FileManager.default.isExecutableFile(atPath: url.path) else {
            throw RuntimeLocatorError.configuredRuntimeMissing(url.path)
        }
        return RuntimeLocation(python: url, mode: .development, runtimeRoot: nil)
    }

    private func repositoryRuntime() -> RuntimeLocation? {
        var starts = [currentDirectory, Bundle.main.bundleURL]
        if let root = environment["XINGYU_ALIGNER_REPOSITORY_ROOT"] {
            starts.insert(URL(fileURLWithPath: root), at: 0)
        }
        for start in starts {
            var root = start
            for _ in 0..<10 {
                let candidate = root.appendingPathComponent(".venv/bin/python")
                if FileManager.default.isExecutableFile(atPath: candidate.path) {
                    return RuntimeLocation(python: candidate, mode: .development, runtimeRoot: nil)
                }
                let parent = root.deletingLastPathComponent()
                if parent == root { break }
                root = parent
            }
        }
        return nil
    }
}

// Compatibility wrapper retained for Phase C tests and development callers.
struct DevelopmentRuntimeLocator {
    var environment: [String: String] = ProcessInfo.processInfo.environment
    var currentDirectory: URL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)

    func locate() throws -> URL {
        try RuntimeLocator(
            environment: environment,
            currentDirectory: currentDirectory,
            bundleResources: nil
        ).locate().python
    }
}
