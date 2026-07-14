import Foundation
import Darwin
import XCTest
@testable import XingyuLyricsAligner

final class ModelAndLyricsTests: XCTestCase {
    func testReadinessModelsAndUnknownStateDecode() throws {
        let json = #"{"schemaVersion":1,"runtime":{"python":{"available":true,"version":"3.11","path":"/python"},"ffmpeg":{"available":true,"path":"/ffmpeg","version":"8"},"ffprobe":{"available":true,"path":"/ffprobe","version":"8"},"developmentRuntime":true},"models":[{"id":"alignment.zh.whisperx","displayName":"中文歌词对齐模型","category":"ALIGNMENT","required":true,"estimatedDownloadBytes":1276,"state":"REVISION_MISMATCH","installedRevision":"old","expectedRevision":"new","path":"/model","license":{"name":"Apache-2.0","url":"https://example"},"problems":["revision_mismatch"]},{"id":"future","displayName":"Future","category":"SEPARATION","required":false,"estimatedDownloadBytes":1,"state":"FUTURE_STATE","installedRevision":null,"expectedRevision":"r","path":"/future","license":{"name":"Unknown","url":"https://example"},"problems":[]}],"readyForAlignment":false,"readyForSeparation":false}"#
        let report = try JSONDecoder().decode(DesktopReadinessReport.self, from: Data(json.utf8))
        XCTAssertEqual(report.alignmentModel?.state, .revisionMismatch)
        XCTAssertEqual(report.separationModel?.state, .unknown("FUTURE_STATE"))
        XCTAssertFalse(report.readyForAlignment)
    }

    func testInstallEventsWithAndWithoutTotalAndUnknownFallback() throws {
        let withTotal = try JSONDecoder().decode(
            ModelInstallEvent.self,
            from: Data(#"{"type":"DOWNLOAD_PROGRESS","modelId":"alignment.zh.whisperx","downloadedBytes":50,"totalBytes":100}"#.utf8)
        )
        XCTAssertEqual(withTotal.eventType, .downloadProgress)
        XCTAssertEqual(withTotal.totalBytes, 100)
        let withoutTotal = try JSONDecoder().decode(
            ModelInstallEvent.self,
            from: Data(#"{"type":"DOWNLOAD_PROGRESS","modelId":"id","downloadedBytes":50,"totalBytes":null}"#.utf8)
        )
        XCTAssertNil(withoutTotal.totalBytes)
        let unknown = try JSONDecoder().decode(
            ModelInstallEvent.self,
            from: Data(#"{"type":"FUTURE_EVENT","modelId":"id"}"#.utf8)
        )
        XCTAssertEqual(unknown.eventType, .unknown("FUTURE_EVENT"))
    }

    func testRunningStatusUnknownStageAndRuntimeDecode() throws {
        let json = #"{"state":"RUNNING","stage":"FUTURE_STAGE","progress":{"kind":"INDETERMINATE","current":null,"total":null,"fraction":null},"runtime":{"workerVersion":"0.6.1","pythonVersion":"3.11.15","platform":"Darwin-arm64"}}"#
        let value = try JSONDecoder().decode(WorkerStatusSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(value.state, .running)
        XCTAssertEqual(value.stage, "FUTURE_STAGE")
        XCTAssertEqual(value.runtime?.platform, "Darwin-arm64")
        XCTAssertNil(value.error)
    }

    func testArtifactsNeedsReviewAndCompleteProgressDecode() throws {
        let json = #"{"state":"NEEDS_REVIEW","progress":{"kind":"COMPLETE","current":1,"total":1,"fraction":1.0},"warnings":["check"],"result":{"artifactsSchemaVersion":1,"artifacts":[{"id":"lyrics.lrc","kind":"LRC","relativePath":"result/lyrics.lrc","mediaType":"text/plain","exportable":true,"temporary":false}]}}"#
        let value = try JSONDecoder().decode(WorkerStatusSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(value.state, .needsReview)
        XCTAssertEqual(value.progress?.fraction, 1)
        XCTAssertEqual(value.result?.artifacts?.first?.kind, .lrc)
    }

    func testStructuredErrorWithMissingOptionalFields() throws {
        let json = #"{"state":"FAILED","error":{"code":"OUTPUT_MISSING","message":"missing"}}"#
        let value = try JSONDecoder().decode(WorkerStatusSnapshot.self, from: Data(json.utf8))
        XCTAssertEqual(value.error?.code, "OUTPUT_MISSING")
        XCTAssertNil(value.attempt)
    }

    func testRequestEncodingVariants() throws {
        for exports in [
            DesktopExports(),
            DesktopExports(lrc: true, swlrc: false),
            DesktopExports(lrc: false, swlrc: true),
            DesktopExports(lrc: true, swlrc: true, vocals: true, accompaniment: true),
        ] {
            XCTAssertTrue(exports.isValid)
            let request = DesktopWorkerRequest(
                schemaVersion: 3, taskType: "DESKTOP_LYRIC_PROCESSING", jobId: "id",
                audioPath: "/music/a.wav", trustedLyricsPath: "/jobs/id/trusted.txt",
                outputDir: "/jobs/id/result", language: "zh", device: "cpu", exports: exports
            )
            let object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any]
            XCTAssertEqual(object?["audioPath"] as? String, "/music/a.wav")
        }
        XCTAssertFalse(DesktopExports(lrc: false, swlrc: false, vocals: true).isValid)
    }

    func testLRCAndPlainTextImport() {
        let lrc = "[ar:歌手]\n[00:01.20][00:02.20]第一句\n\n[01:03:04.500]中文歌词\n[bad]保留"
        XCTAssertEqual(
            LyricsImportService.normalizedLyrics(from: lrc, fileExtension: "lrc"),
            "第一句\n中文歌词\n[bad]保留"
        )
        XCTAssertEqual(LyricsImportService.normalizedLyrics(from: " 普通 TXT\n第二行 ", fileExtension: "txt"), "普通 TXT\n第二行")
    }
}

@MainActor
final class ReadinessGatingTests: XCTestCase {
    func testManagedDevelopmentPathCanFindHomebrewMediaTools() {
        let paths = ManagedDesktopPaths(root: URL(fileURLWithPath: "/tmp/app data"))
        let path = paths.environment["PATH"]

        XCTAssertNotNil(path)
        XCTAssertTrue(path?.split(separator: ":").contains("/opt/homebrew/bin") == true)
        XCTAssertTrue(path?.split(separator: ":").contains("/usr/local/bin") == true)
        XCTAssertTrue(path?.split(separator: ":").contains("/usr/bin") == true)

        let runtimePath = paths.processEnvironment(
            runtimeExecutable: URL(fileURLWithPath: "/repo/.venv/bin/python")
        )["PATH"]
        XCTAssertEqual(runtimePath?.split(separator: ":").first, "/repo/.venv/bin")
    }

    private func report(alignment: Bool, separation: Bool) throws -> DesktopReadinessReport {
        let json = """
        {"schemaVersion":1,"runtime":{"python":{"available":true},"ffmpeg":{"available":true},"ffprobe":{"available":true}},"models":[],"readyForAlignment":\(alignment),"readyForSeparation":\(separation)}
        """
        return try JSONDecoder().decode(DesktopReadinessReport.self, from: Data(json.utf8))
    }

    func testRequiredModelBlocksAllLyricsTasks() throws {
        XCTAssertFalse(EnvironmentReadinessViewModel.canRun(
            exports: DesktopExports(), report: try report(alignment: false, separation: true), installing: false
        ))
    }

    func testOptionalModelDoesNotBlockLyricsButBlocksTracks() throws {
        let readiness = try report(alignment: true, separation: false)
        XCTAssertTrue(EnvironmentReadinessViewModel.canRun(
            exports: DesktopExports(), report: readiness, installing: false
        ))
        XCTAssertFalse(EnvironmentReadinessViewModel.canRun(
            exports: DesktopExports(vocals: true), report: readiness, installing: false
        ))
    }

    func testSeparationReadyAllowsTracksAndInstallBlocksEverything() throws {
        let readiness = try report(alignment: true, separation: true)
        XCTAssertTrue(EnvironmentReadinessViewModel.canRun(
            exports: DesktopExports(accompaniment: true), report: readiness, installing: false
        ))
        XCTAssertFalse(EnvironmentReadinessViewModel.canRun(
            exports: DesktopExports(), report: readiness, installing: true
        ))
    }
}

final class WorkspaceAndArtifactTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    func testWorkspaceCopiesUnicodeAudioWritesRequestAndReadyLast() async throws {
        let source = root.appendingPathComponent("中文 song.wav")
        try Data("audio".utf8).write(to: source)
        let service = JobWorkspaceService(rootDirectory: root.appendingPathComponent("workspace"))
        let first = try await service.create(audio: source, lyrics: "星语\n发光", exports: DesktopExports())
        let second = try await service.create(audio: source, lyrics: "星语", exports: DesktopExports())
        XCTAssertNotEqual(first.id, second.id)
        XCTAssertEqual(try String(contentsOf: first.audioURL, encoding: .utf8), "audio")
        XCTAssertFalse((try first.audioURL.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink ?? true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: first.jobDirectory.appendingPathComponent("trusted-lyrics.txt").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: first.jobDirectory.appendingPathComponent("READY").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: first.requestURL.path))
        XCTAssertTrue((try FileManager.default.contentsOfDirectory(atPath: first.jobDirectory.path)).allSatisfy { !$0.contains("tmp") })
    }

    func testArtifactExportSelectionPathsAndOverwrite() async throws {
        let job = root.appendingPathComponent("job")
        let resultDirectory = job.appendingPathComponent("result")
        try FileManager.default.createDirectory(at: resultDirectory, withIntermediateDirectories: true)
        try Data("new lrc".utf8).write(to: resultDirectory.appendingPathComponent("lyrics.lrc"))
        try Data("swlrc".utf8).write(to: resultDirectory.appendingPathComponent("lyrics.swlrc"))
        let workspace = JobWorkspace(
            id: "id", jobDirectory: job, musicDirectory: root, resultDirectory: resultDirectory,
            requestURL: job.appendingPathComponent("request.json"), audioURL: root.appendingPathComponent("song.wav")
        )
        let artifacts = [
            WorkerArtifact(id: "lrc", kind: .lrc, relativePath: "result/lyrics.lrc", mediaType: "text/plain", exportable: true, temporary: false),
            WorkerArtifact(id: "swlrc", kind: .swlrc, relativePath: "result/lyrics.swlrc", mediaType: "text/plain", exportable: true, temporary: false),
        ]
        let result = WorkerResult(success: true, files: nil, warnings: nil, artifactsSchemaVersion: 1, artifacts: artifacts)
        let destination = root.appendingPathComponent("exports")
        let existing = destination.appendingPathComponent("歌曲/lyrics.lrc")
        try FileManager.default.createDirectory(at: existing.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("old".utf8).write(to: existing)
        let exported = try await ArtifactExportService().export(
            result: result, workspace: workspace,
            selection: DesktopExports(lrc: true, swlrc: false),
            destinationRoot: destination, songName: "歌曲"
        )
        XCTAssertEqual(exported.map(\.lastPathComponent), ["lyrics.lrc"])
        XCTAssertEqual(try String(contentsOf: existing, encoding: .utf8), "new lrc")
    }

    func testArtifactExportRejectsUnsafeAndMissingPaths() async throws {
        let job = root.appendingPathComponent("job")
        try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        let workspace = JobWorkspace(id: "id", jobDirectory: job, musicDirectory: root, resultDirectory: job, requestURL: job, audioURL: job)
        for path in ["/tmp/evil", "../evil", "result/missing.lrc"] {
            let artifact = WorkerArtifact(id: "lrc", kind: .lrc, relativePath: path, mediaType: "text/plain", exportable: true, temporary: false)
            let result = WorkerResult(success: true, files: nil, warnings: nil, artifactsSchemaVersion: 1, artifacts: [artifact])
            do {
                _ = try await ArtifactExportService().export(result: result, workspace: workspace, selection: DesktopExports(), destinationRoot: root, songName: "song")
                XCTFail("Expected unsafe or missing path failure")
            } catch { }
        }
    }

    func testArtifactExportRejectsDuplicateAndSymlinkSource() async throws {
        let job = root.appendingPathComponent("job")
        let resultDirectory = job.appendingPathComponent("result")
        try FileManager.default.createDirectory(at: resultDirectory, withIntermediateDirectories: true)
        let outside = root.appendingPathComponent("outside.lrc")
        try Data("outside".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(
            at: resultDirectory.appendingPathComponent("lyrics.lrc"), withDestinationURL: outside
        )
        let workspace = JobWorkspace(id: "id", jobDirectory: job, musicDirectory: root, resultDirectory: resultDirectory, requestURL: job, audioURL: outside)
        let artifact = WorkerArtifact(id: "lrc", kind: .lrc, relativePath: "result/lyrics.lrc", mediaType: "text/plain", exportable: true, temporary: false)
        let result = WorkerResult(success: true, files: nil, warnings: nil, artifactsSchemaVersion: 1, artifacts: [artifact, artifact])
        await XCTAssertThrowsErrorAsync {
            _ = try await ArtifactExportService().export(result: result, workspace: workspace, selection: DesktopExports(), destinationRoot: self.root, songName: "song")
        }
    }
}

private func XCTAssertThrowsErrorAsync(_ expression: () async throws -> Void) async {
    do { try await expression(); XCTFail("Expected an error") } catch { }
}

@MainActor
final class MonitorAndRuntimeTests: XCTestCase {
    func testAsyncProcessRunnerDrainsLargeConcurrentOutputAndKeepsUTF8Tail() async throws {
        let script = "python3 - <<'PY'\nimport sys\nsys.stdout.buffer.write(b'x'*1100000 + '中文'.encode())\nsys.stderr.buffer.write(b'y'*1100000 + '诊断'.encode())\nPY"
        let result = try await AsyncProcessRunner(maximumBytes: 1_048_576).run(
            executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", script],
            environment: ["PATH": "/usr/bin:/bin"], timeout: .seconds(10)
        )
        XCTAssertEqual(result.status, 0)
        XCTAssertTrue(result.stdoutTruncated && result.stderrTruncated)
        XCTAssertTrue(String(decoding: result.stdout, as: UTF8.self).hasSuffix("中文"))
        XCTAssertTrue(String(decoding: result.stderr, as: UTF8.self).hasSuffix("诊断"))
    }

    func testAsyncProcessRunnerTimesOut() async {
        do {
            _ = try await AsyncProcessRunner().run(
                executable: URL(fileURLWithPath: "/bin/sleep"), arguments: ["5"],
                environment: [:], timeout: .milliseconds(50)
            )
            XCTFail("Expected timeout")
        } catch { XCTAssertTrue(error is AsyncProcessError) }
    }

    func testAsyncProcessRunnerCancellationAndNonzeroExit() async throws {
        let runner = AsyncProcessRunner()
        let nonzero = try await runner.run(
            executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "echo error >&2; exit 7"],
            environment: [:]
        )
        XCTAssertEqual(nonzero.status, 7)
        XCTAssertTrue(String(decoding: nonzero.stderr, as: UTF8.self).contains("error"))
        let task = Task {
            try await runner.run(executable: URL(fileURLWithPath: "/bin/sleep"), arguments: ["5"], environment: [:])
        }
        task.cancel()
        do { _ = try await task.value; XCTFail("Expected cancellation") }
        catch { XCTAssertTrue(error is CancellationError) }
    }
    func testRuntimeLocatorDoesNotFallBackToSystemPython() {
        let locator = DevelopmentRuntimeLocator(environment: [:], currentDirectory: URL(fileURLWithPath: "/tmp/no-repository"))
        XCTAssertThrowsError(try locator.locate())
    }

    func testBundledRuntimeCanBeForcedAndTakesPriority() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let resources = root.appendingPathComponent("Resources")
        let python = resources.appendingPathComponent("runtime/bin/python3")
        try FileManager.default.createDirectory(
            at: python.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try Data("#!/bin/sh\n".utf8).write(to: python)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: python.path)
        defer { try? FileManager.default.removeItem(at: root) }

        let location = try RuntimeLocator(
            environment: ["XINGYU_RUNTIME_MODE": "BUNDLED"],
            currentDirectory: URL(fileURLWithPath: "/tmp/no-repository"),
            bundleResources: resources
        ).locate()

        XCTAssertEqual(location.mode, .bundled)
        XCTAssertEqual(location.python, python)
    }

    func testMissingForcedBundledRuntimeHasClearError() {
        let locator = RuntimeLocator(
            environment: ["XINGYU_RUNTIME_MODE": "BUNDLED"],
            currentDirectory: URL(fileURLWithPath: "/tmp/no-repository"),
            bundleResources: URL(fileURLWithPath: "/tmp/missing bundle")
        )
        XCTAssertThrowsError(try locator.locate()) { error in
            XCTAssertTrue(error.localizedDescription.contains("内嵌 Runtime"))
        }
    }

    func testBundledProcessEnvironmentUsesOnlyBundleToolsAndDropsTokens() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let runtime = root.appendingPathComponent("runtime")
        let bin = runtime.appendingPathComponent("bin")
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        for name in ["python3", "ffmpeg", "ffprobe"] {
            let file = bin.appendingPathComponent(name)
            try Data("binary".utf8).write(to: file)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: file.path)
        }
        defer { try? FileManager.default.removeItem(at: root) }
        let environment = ProcessEnvironmentBuilder(
            paths: ManagedDesktopPaths(root: root.appendingPathComponent("App Data")),
            runtimeExecutable: bin.appendingPathComponent("python3"),
            inherited: ["HF_TOKEN": "secret", "UNRELATED": "kept"]
        ).build()

        XCTAssertEqual(environment["XINGYU_ALIGNER_FFMPEG"], bin.appendingPathComponent("ffmpeg").path)
        XCTAssertEqual(environment["XINGYU_ALIGNER_FFPROBE"], bin.appendingPathComponent("ffprobe").path)
        XCTAssertEqual(environment["PYTHONHOME"], runtime.path)
        XCTAssertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        XCTAssertNil(environment["HF_TOKEN"])
        XCTAssertEqual(environment["UNRELATED"], "kept")
        XCTAssertFalse(environment["PATH"]?.contains("homebrew") == true)
    }

    func testStatusMonitorWaitsConsumesCompleteEventsOnceAndStopsAtTerminal() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let job = root.appendingPathComponent("job")
        try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let workspace = JobWorkspace(id: "id", jobDirectory: job, musicDirectory: root, resultDirectory: job, requestURL: job, audioURL: job)
        var received: [WorkerEvent] = []
        let monitor = StatusMonitor()
        let task = Task { @MainActor in
            await monitor.monitor(workspace: workspace, pollNanoseconds: 20_000_000) { _, events in
                received.append(contentsOf: events)
            }
        }
        try await Task.sleep(for: .milliseconds(30))
        try Data("{\"eventId\":\"1\",\"type\":\"TASK_ACCEPTED\",\"message\":\"ok\"}\n{\"eventId\":\"2\"".utf8)
            .write(to: job.appendingPathComponent("events.jsonl"))
        try await Task.sleep(for: .milliseconds(40))
        try Data(#"{"state":"SUCCEEDED","progress":{"kind":"COMPLETE","current":1,"total":1,"fraction":1}}"#.utf8)
            .write(to: job.appendingPathComponent("status.json"), options: .atomic)
        await task.value
        XCTAssertEqual(received.map(\.eventId), ["1"])
    }

    func testStatusMonitorReportsPersistentInvalidStatus() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let job = root.appendingPathComponent("job")
        try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("not-json".utf8).write(to: job.appendingPathComponent("status.json"))
        let workspace = JobWorkspace(id: "job", jobDirectory: job, musicDirectory: root, resultDirectory: job, requestURL: job, audioURL: job)
        var reported: StatusMonitorError?
        await StatusMonitor().monitor(
            workspace: workspace, pollNanoseconds: 1_000_000, maximumConsecutiveFailures: 2
        ) { error in
            reported = error
        } onUpdate: { _, _ in }
        guard case .persistentInvalidStatus = reported else {
            return XCTFail("Expected persistent invalid status error")
        }
    }

    func testStatusMonitorRecoversFromTruncatedEventsAndSplitUnicode() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let job = root.appendingPathComponent("job")
        try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let eventsURL = job.appendingPathComponent("events.jsonl")
        let workspace = JobWorkspace(id: "job", jobDirectory: job, musicDirectory: root, resultDirectory: job, requestURL: job, audioURL: job)
        var received: [WorkerEvent] = []
        let task = Task { @MainActor in
            await StatusMonitor().monitor(workspace: workspace, pollNanoseconds: 5_000_000) { error in
                XCTFail(error.localizedDescription)
            } onUpdate: { snapshot, events in
                received.append(contentsOf: events)
                if events.count == 1 {
                    try? Data((#"{"eventId":"2","type":"WARNING","message":"中文"}"# + "\n").utf8)
                        .write(to: eventsURL)
                    try? Data(#"{"state":"SUCCEEDED"}"#.utf8)
                        .write(to: job.appendingPathComponent("status.json"), options: .atomic)
                }
            }
        }
        let complete = #"{"eventId":"1","type":"WARNING","message":"第一条"}"# + "\n"
        let partial = Data((complete + #"{"eventId":"partial","message":"中"#).utf8)
        try partial.write(to: eventsURL)
        await task.value
        XCTAssertEqual(received.map(\.eventId), ["1", "2"])
    }
}

@MainActor
final class ProcessServiceTests: XCTestCase {
    func testProcessCapturesOutputAndExit() async throws {
        let service = WorkerProcessService()
        let root = FileManager.default.temporaryDirectory
        let exited = expectation(description: "exit")
        try service.start(
            python: URL(fileURLWithPath: "/bin/echo"), jobsDirectory: root, musicDirectory: root,
            developmentArgumentsOverride: ["hello"]
        ) { code in
            XCTAssertEqual(code, 0)
            exited.fulfill()
        }
        await fulfillment(of: [exited], timeout: 2)
        XCTAssertTrue(service.diagnosticLog.contains("hello"))
    }

    func testProcessMissingExecutableAndForceTerminate() async throws {
        let missing = WorkerProcessService()
        XCTAssertThrowsError(try missing.start(
            python: URL(fileURLWithPath: "/missing/python"), jobsDirectory: .temporaryDirectory,
            musicDirectory: .temporaryDirectory, developmentArgumentsOverride: []
        ) { _ in })

        let service = WorkerProcessService()
        let exited = expectation(description: "terminated")
        try service.start(
            python: URL(fileURLWithPath: "/bin/sleep"), jobsDirectory: .temporaryDirectory,
            musicDirectory: .temporaryDirectory, developmentArgumentsOverride: ["10"]
        ) { _ in exited.fulfill() }
        XCTAssertNotNil(service.pid)
        service.forceTerminate()
        await fulfillment(of: [exited], timeout: 2)
    }

    func testProcessReportsNonzeroExit() async throws {
        let service = WorkerProcessService()
        let exited = expectation(description: "nonzero")
        try service.start(
            python: URL(fileURLWithPath: "/usr/bin/false"),
            jobsDirectory: .temporaryDirectory,
            musicDirectory: .temporaryDirectory,
            developmentArgumentsOverride: []
        ) { code in
            XCTAssertNotEqual(code, 0)
            exited.fulfill()
        }
        await fulfillment(of: [exited], timeout: 2)
    }

    func testForceTerminateKillsWorkerProcessGroupChild() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let childPID = root.appendingPathComponent("child.pid")
        let script = root.appendingPathComponent("worker.sh")
        try Data("#!/bin/sh\nsleep 30 &\necho $! > \"$1\"\nwait\n".utf8).write(to: script)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let service = WorkerProcessService()
        let exited = expectation(description: "process group exited")
        try service.start(
            python: script, jobsDirectory: root, musicDirectory: root,
            developmentArgumentsOverride: [childPID.path]
        ) { _ in exited.fulfill() }
        for _ in 0..<50 where !FileManager.default.fileExists(atPath: childPID.path) {
            try await Task.sleep(for: .milliseconds(10))
        }
        let pid = Int32(try String(contentsOf: childPID).trimmingCharacters(in: .whitespacesAndNewlines))
        XCTAssertNotNil(pid)
        service.forceTerminate()
        await fulfillment(of: [exited], timeout: 3)
        if let pid { XCTAssertEqual(kill(pid, 0), -1) }
    }
}
