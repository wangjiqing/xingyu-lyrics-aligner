import Foundation

@MainActor
final class EnvironmentReadinessViewModel: ObservableObject {
    @Published private(set) var state: EnvironmentReadinessState = .checking
    @Published private(set) var report: DesktopReadinessReport?
    @Published private(set) var installEvent: ModelInstallEvent?
    @Published private(set) var errorMessage: String?

    let installService = ModelInstallProcessService()
    private let readinessService = RuntimeReadinessService()
    private let paths = ManagedDesktopPaths()
    private var python: URL?

    init() {
        Task { await check() }
    }

    var installInProgress: Bool { state == .installing }
    var alignmentReady: Bool { report?.readyForAlignment == true }
    var separationReady: Bool { report?.readyForSeparation == true }

    func check() async {
        state = .checking
        errorMessage = nil
        installEvent = nil
        do {
            let runtime = try RuntimeLocator().locate()
            self.python = runtime.python
            let report = try await readinessService.check(python: runtime.python, dataRoot: paths.root)
            self.report = report
            classify(report)
        } catch {
            state = .failed
            errorMessage = error.localizedDescription
        }
    }

    func install(modelID: String) {
        guard let python, !installInProgress else { return }
        state = .installing
        installEvent = nil
        errorMessage = nil
        do {
            try installService.start(
                python: python,
                modelID: modelID,
                dataRoot: paths.root
            ) { [weak self] event in
                self?.installEvent = event
                if event.eventType == .installFailed { self?.errorMessage = event.message }
            } onExit: { [weak self] code in
                guard let self else { return }
                if code != 0, self.installEvent?.eventType != .installCancelled {
                    self.errorMessage = self.errorMessage ?? "模型安装进程异常退出（exit \(code)）。"
                }
                Task { await self.check() }
            }
        } catch {
            state = .failed
            errorMessage = error.localizedDescription
        }
    }

    func cancelInstall() {
        installService.cancel()
    }

    func shutdown() {
        installService.terminateForAppExit()
    }

    func canRun(exports: DesktopExports) -> Bool {
        Self.canRun(exports: exports, report: report, installing: installInProgress)
    }

    static func canRun(
        exports: DesktopExports,
        report: DesktopReadinessReport?,
        installing: Bool
    ) -> Bool {
        guard let report, report.readyForAlignment, !installing else { return false }
        return (!exports.vocals && !exports.accompaniment) || report.readyForSeparation
    }

    private func classify(_ report: DesktopReadinessReport) {
        if !report.runtime.python.available || !report.runtime.ffmpeg.available
            || !report.runtime.ffprobe.available
        {
            state = .failed
        } else if !report.readyForAlignment {
            state = .missingRequiredModels
        } else if !report.readyForSeparation {
            state = .missingOptionalModels
        } else {
            state = .ready
        }
    }
}
